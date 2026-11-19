"""Ingestion des actualités, reprise du notebook v2 (sections 0.3 et 1) : GDELT DOC, flux RSS, replay GKG.

Les fonctions sont synchrones (requests, gdeltdoc) ; `MediaAgent` les lance dans un fil avec asyncio.to_thread.
Chacune renvoie une liste d'articles au schéma commun et complète `report` avec l'état de sa source.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import re
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from src.config import settings
from src.utils.http import http_get
from src.utils.text import norm_key, url_hash

log = logging.getLogger("supplychain.media")

# Requête GDELT unique : (un de ces mots-clés) ET (un de ces termes d'ancrage). En anglais : GDELT traduit 65 langues.
GDELT_KEYWORDS = ["strike", "shortage", "bankruptcy", "cyberattack", "sanction"]
GDELT_ANCHORS = ["supply chain", "factory", "port"]

EVENT_KEYWORDS = {
    "greve":        ["strike", "walkout", "industrial action", "grève", "débrayage", "streik", "staking"],
    "catastrophe":  ["earthquake", "flood", "typhoon", "hurricane", "wildfire", "storm", "explosion",
                     "séisme", "inondation", "incendie", "tempête", "ouragan", "typhon", "erdbeben", "hochwasser"],
    "sanction":     ["sanction", "export ban", "export control", "embargo", "blacklist", "entity list",
                     "export restriction", "interdiction d'exportation", "contrôle des exportations",
                     "exportverbot", "seizure", "takes control"],
    "faillite":     ["bankruptcy", "insolvency", "chapter 11", "receivership", "faillite",
                     "redressement judiciaire", "liquidation judiciaire", "insolvenz"],
    "cyberattaque": ["cyberattack", "cyber attack", "ransomware", "hacked", "data breach", "cyberattaque",
                     "rançongiciel", "cyberangriff"],
    "penurie":      ["shortage", "supply disruption", "production halt", "halts production", "cuts output",
                     "halves production", "pénurie", "arrêt de production", "rupture d'approvisionnement",
                     "lieferengpass", "produktionsstopp"],
    "logistique":   ["port closure", "port congestion", "canal blocked", "vessel stuck", "container ship",
                     "fermeture du port", "blocage du port", "hafen gesperrt"],
}
# Ancrage supply chain : évite « grève des enseignants » ou « faillite d'un club de foot »
SUPPLY_ANCHORS = ["supply chain", "supplier", "factory", "plant", "port", "semiconductor", "chip",
                  "automaker", "fournisseur", "usine", "puce", "constructeur", "zulieferer", "werk"]

# Flux RSS (presse économique européenne et presse spécialisée supply chain). Les adresses changent parfois :
# un flux en erreur est signalé, jamais bloquant. Une valeur peut être une liste d'adresses de rechange, essayées
# dans l'ordre. `python scripts/check_feeds.py` teste tous les flux depuis votre poste.
RSS_FEEDS = {
    "supplychaindive":    "https://www.supplychaindive.com/feeds/news/",     # remplace latribune_industrie (HTTP 404)
    "freightwaves":       "https://www.freightwaves.com/feed",
    "lemonde_economie":   "https://www.lemonde.fr/economie/rss_full.xml",
    "bfm_economie":       "https://www.bfmtv.com/rss/economie/",
    "tagesschau_wirtschaft": "https://www.tagesschau.de/wirtschaft/index~rss2.xml",
    "dw_business":        "https://rss.dw.com/rdf/rss-en-bus",
    "nos_economie":       "https://feeds.nos.nl/nosnieuwseconomie",
    "bbc_business":       "https://feeds.bbci.co.uk/news/business/rss.xml",
    "guardian_business":  "https://www.theguardian.com/business/rss",
    "euractiv":           "https://www.euractiv.com/feed/",
    "theloadstar":        "https://theloadstar.com/feed/",
    "splash247":          "https://splash247.com/feed/",
}


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


@dataclass
class Article:
    """Schéma commun d'un article, quelle que soit la source. source_id = <source>:<identifiant>."""
    source_id: str
    title: str
    source_type: str = "replay"
    url: str = ""
    text: str = ""
    published_at: Optional[datetime] = None
    domain: Optional[str] = None
    language: Optional[str] = None
    source_country: Optional[str] = None
    # champs calculés par la chaîne NLP
    content: str = field(default="", repr=False)
    cluster_id: str = ""


def parse_dt(value) -> Optional[datetime]:
    """Date en UTC à partir d'un datetime, d'un struct_time, d'un texte ISO ou d'une date RSS. None si illisible."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, time.struct_time):
            dt = datetime(*value[:6], tzinfo=timezone.utc)
        else:
            s = str(value).strip()
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                dt = parsedate_to_datetime(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def finalize_articles(articles: list[Article]) -> list[Article]:
    """Force le schéma commun : lignes sans titre retirées, source_id unique."""
    out, seen = [], set()
    for a in articles:
        a.title, a.text = str(a.title or "").strip(), str(a.text or "").strip()
        if not a.title or not a.source_id or a.source_id in seen:
            continue
        seen.add(a.source_id)
        out.append(a)
    return out


def articles_as_of(articles: list[Article], as_of: str) -> list[Article]:
    """Vue « jour J » : uniquement les articles publiés jusqu'à `as_of` inclus (pas de fuite du futur)."""
    limit = datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return [a for a in articles if a.published_at is not None and a.published_at < limit]


# ----------------------------------------------------------------------------- cache disque à durée courte
GDELT_CACHE_TTL_S = 15 * 60          # une même requête n'est pas renvoyée à l'API pendant 15 minutes
GDELT_COOLDOWN_S = 5 * 60            # après une limite de débit, GDELT n'est pas rappelé pendant 5 minutes
GOOGLE_NEWS_URL = "https://news.google.com/rss/search"


def _cache_file(kind: str, key: str) -> Path:
    return settings.cache_dir / kind / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json")


def cache_get(kind: str, key: str, ttl_s: float) -> Optional[tuple[list["Article"], float]]:
    """Articles en cache et leur âge en secondes, ou None si le cache est absent, périmé ou illisible."""
    path = _cache_file(kind, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["saved_at"])
        if age < 0 or age > ttl_s:
            return None
        return [Article(**{**a, "published_at": parse_dt(a.get("published_at"))}) for a in payload["articles"]], age
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cache_put(kind: str, key: str, articles: list["Article"]) -> None:
    """Écrit le cache. Une erreur d'écriture (disque en lecture seule) ne fait jamais échouer la collecte."""
    rows = [{"source_id": a.source_id, "source_type": a.source_type, "url": a.url, "title": a.title, "text": a.text,
             "published_at": a.published_at.isoformat() if a.published_at else None, "domain": a.domain,
             "language": a.language, "source_country": a.source_country} for a in articles]
    try:
        path = _cache_file(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"saved_at": time.time(), "articles": rows}, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("cache %s non écrit : %s", kind, type(e).__name__)


# ----------------------------------------------------------------------------- GDELT DOC 2.0 (live)
def _or_group(terms) -> str:
    return "(" + " OR ".join(f'"{t}"' if " " in t else t for t in terms) + ") "


def ingest_gdelt_live(start: datetime, end: datetime, keywords=GDELT_KEYWORDS, anchors=GDELT_ANCHORS,
                      max_records: Optional[int] = None, countries=None, retry_pause: Optional[float] = None,
                      call_timeout: float = 60, report: Optional[dict] = None, use_cache: bool = True) -> list[Article]:
    """Collecte GDELT en une seule requête (la limite de débit s'applique par adresse IP).

    Cache disque de 15 minutes : des clics répétés ne renvoient pas la requête à l'API.
    Limite de débit : une pause, puis un seul nouvel essai ; en cas d'échec, `rate_limited` vaut True dans le
    rapport et GDELT n'est plus rappelé pendant 5 minutes. Tout autre échec : liste vide et status "failed".
    """
    report = {} if report is None else report
    max_records = max_records or settings.gdelt_max
    retry_pause = settings.gdelt_retry_pause_s if retry_pause is None else retry_pause
    key = json.dumps({"k": list(keywords), "a": list(anchors), "c": countries, "n": int(max_records),
                      "jours": round((end - start).total_seconds() / 86400)}, sort_keys=True)
    if use_cache:
        hit = cache_get("gdelt", key, GDELT_CACHE_TTL_S)
        if hit is not None:
            arts = [a for a in hit[0] if a.published_at is None or a.published_at >= start]
            report["gdelt"] = {"status": "ok", "requetes": 0, "cache": True, "age_cache_s": round(hit[1]), "articles": len(arts)}
            return arts
        cooldown = cache_get("gdelt_cooldown", key, GDELT_COOLDOWN_S)
        if cooldown is not None:
            report["gdelt"] = {"status": "failed", "requetes": 0, "reponses": 0, "articles": 0, "rate_limited": True,
                               "detail": f"limite de débit il y a {round(cooldown[1])} s : GDELT n'est pas rappelé avant {GDELT_COOLDOWN_S // 60} min"}
            return []
    if not _has("gdeltdoc"):
        report["gdelt"] = {"status": "unavailable", "detail": "paquet gdeltdoc non installé"}
        return []
    from gdeltdoc import Filters, GdeltDoc
    try:
        from gdeltdoc.errors import RateLimitError
    except Exception:                                   # anciennes versions de gdeltdoc
        class RateLimitError(Exception):
            pass

    def failed(detail: str) -> list[Article]:
        log.warning("GDELT : %s", detail)
        report["gdelt"] = {"status": "failed", "requetes": 1, "reponses": 0, "articles": 0, "detail": detail}
        return []

    try:
        # keyword doit rester une liste : une chaîne serait mise entre guillemets par gdeltdoc (expression exacte)
        f = Filters(keyword=list(keywords), start_date=start, end_date=end,
                    num_records=min(int(max_records), 250), country=countries)
        f.query_params.insert(1, _or_group(anchors))    # groupe d'ancrage (ET implicite) juste après les mots-clés
    except Exception as e:
        return failed(f"filtre invalide ({e})")

    gd, raw = GdeltDoc(), None
    pool = ThreadPoolExecutor(max_workers=1)            # gdeltdoc n'impose aucun délai maximal : délai de garde
    try:
        for attempt in (1, 2):
            try:
                raw = pool.submit(gd.article_search, f).result(timeout=call_timeout)
                break
            except RateLimitError:
                if attempt == 2:
                    failed("limite de débit, même après une pause. Réessayer plus tard ou depuis un autre poste.")
                    report["gdelt"]["rate_limited"] = True
                    if use_cache:
                        cache_put("gdelt_cooldown", key, [])
                    return []
                log.warning("GDELT : limite de débit, pause de %s s puis nouvel essai", retry_pause)
                time.sleep(retry_pause)
            except FutureTimeout:
                return failed(f"pas de réponse en {call_timeout} s")
            except Exception as e:                      # réseau, requête refusée, réponse non JSON...
                return failed(f"{type(e).__name__} : {str(e)[:120]}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    rows = raw.to_dict("records") if raw is not None else []
    capped = len(rows) >= min(int(max_records), 250)
    report["gdelt"] = {"status": "ok", "requetes": 1, "reponses": 1, "articles": len(rows), "plafond_atteint": capped}
    out = []
    for r in rows:
        url = r.get("url")
        if not url:
            continue
        try:
            published = datetime.strptime(str(r.get("seendate")), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            published = None
        out.append(Article(source_id="gdelt:" + url_hash(url), source_type="gdelt", url=url, title=str(r.get("title") or ""),
                           published_at=published, domain=r.get("domain"), language=r.get("language"),
                           source_country=r.get("sourcecountry")))
    out = finalize_articles(out)
    if use_cache:
        cache_put("gdelt", key, out)
    return out


# ----------------------------------------------------------------------------- Google News RSS (repli de GDELT)
def ingest_google_news(start: datetime, end: datetime, keywords=GDELT_KEYWORDS, anchors=GDELT_ANCHORS,
                       max_records: Optional[int] = None, report: Optional[dict] = None, use_cache: bool = True,
                       reason: str = "") -> list[Article]:
    """Recherche Google News en RSS sur les mêmes mots-clés que GDELT. Données réelles ; même cache de 15 minutes.

    Ne sert que de repli quand GDELT refuse la requête (limite de débit). Les liens sont ceux de Google News.
    """
    report = {} if report is None else report
    max_records = max_records or settings.gdelt_max
    if not _has("feedparser"):
        report["google_news"] = {"status": "unavailable", "detail": "paquet feedparser non installé"}
        return []
    import feedparser
    days = max(1, round((end - start).total_seconds() / 86400))
    query = f"{_or_group(keywords)}{_or_group(anchors)}when:{days}d"
    if use_cache:
        hit = cache_get("google_news", query, GDELT_CACHE_TTL_S)
        if hit is not None:
            report["google_news"] = {"status": "ok", "requetes": 0, "cache": True, "age_cache_s": round(hit[1]),
                                     "articles": len(hit[0]), "motif": reason}
            return hit[0]
    info: dict = {}
    r = http_get(GOOGLE_NEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}, info=info)
    if r is None:
        report["google_news"] = {"status": "failed", "requetes": 1, "articles": 0, "motif": reason,
                                 "detail": f"HTTP {info['status']}" if info.get("status") else info.get("error") or "pas de réponse"}
        return []
    try:
        parsed = feedparser.parse(r.content)
        if not parsed.get("version"):
            raise ValueError("la réponse n'est pas un flux RSS")
        entries = parsed.entries
    except Exception:
        report["google_news"] = {"status": "failed", "requetes": 1, "articles": 0, "motif": reason, "detail": "flux illisible"}
        return []
    rows = []
    for e in entries[:int(max_records)]:
        link, title = e.get("link"), _strip_html(e.get("title"))
        if not link or not title:
            continue
        source = (e.get("source") or {}).get("title") if isinstance(e.get("source"), dict) else None
        if source and title.endswith(" - " + source):       # Google ajoute « - Nom du média » à la fin du titre
            title = title[: -len(" - " + source)].strip()
        published = parse_dt(e.get("published_parsed") or e.get("published"))
        if published is not None and published < start:
            continue
        rows.append(Article(source_id="gnews:" + url_hash(e.get("id") or link), source_type="google_news", url=link,
                            title=title, published_at=published, domain=source, language="English"))
    out = finalize_articles(rows)
    report["google_news"] = {"status": "ok", "requetes": 1, "articles": len(out), "motif": reason}
    if use_cache:
        cache_put("google_news", query, out)
    return out


def ingest_gdelt_with_fallback(start: datetime, end: datetime, countries=None, report: Optional[dict] = None,
                               use_cache: bool = True) -> list[Article]:
    """GDELT d'abord ; si GDELT refuse pour limite de débit, Google News RSS sur les mêmes mots-clés.

    Les deux états restent dans le rapport : `gdelt` en échec, `google_news` en repli. Le résultat est donc marqué
    incomplet (degraded) : Google News ne couvre pas les 65 langues de GDELT.
    """
    report = {} if report is None else report
    arts = ingest_gdelt_live(start, end, countries=countries, report=report, use_cache=use_cache)
    if report.get("gdelt", {}).get("rate_limited"):
        arts = ingest_google_news(start, end, report=report, use_cache=use_cache, reason="repli : GDELT en limite de débit")
    return arts


# ----------------------------------------------------------------------------- flux RSS (live)
def _strip_html(s) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


_FILTER_TERMS = [norm_key(t) for ts in EVENT_KEYWORDS.values() for t in ts] + [norm_key(t) for t in SUPPLY_ANCHORS]


def is_supply_related(text: str) -> bool:
    t = norm_key(text)
    return any(re.search(rf"(?<!\w){re.escape(term)}", t) for term in _FILTER_TERMS)


def ingest_rss(feeds: Optional[dict] = None, since: Optional[datetime] = None, keep_filter: bool = True,
               report: Optional[dict] = None) -> list[Article]:
    """Collecte RSS. Refus du site (403, 404) : on passe au flux suivant. Trois pannes réseau de suite : on arrête."""
    report = {} if report is None else report
    feeds = RSS_FEEDS if feeds is None else feeds
    if not _has("feedparser"):
        report["rss"] = {"status": "unavailable", "detail": "paquet feedparser non installé"}
        return []
    import feedparser
    rows, net_failures, answered, errors = [], 0, 0, {}
    for name, urls in feeds.items():
        if net_failures >= 3:
            log.warning("RSS : trois pannes réseau de suite, réseau probablement coupé. Flux restants ignorés.")
            break
        info: dict = {}
        r = None
        for url in ([urls] if isinstance(urls, str) else list(urls)):     # adresses de rechange, dans l'ordre
            info = {}
            r = http_get(url, info=info)
            if r is not None or not info.get("status"):                   # réponse obtenue, ou panne réseau : on arrête
                break
        if r is None:
            if info.get("status"):                  # le site a répondu : problème propre à ce flux
                errors[name] = f"HTTP {info['status']}"
                net_failures = 0
            else:                                   # aucune réponse : panne réseau
                errors[name] = info.get("error") or "pas de réponse"
                net_failures += 1
            continue
        net_failures = 0
        try:
            parsed = feedparser.parse(r.content)
            if not parsed.get("version"):           # ni RSS ni Atom : page HTML (filtre anti-robot), XML cassé
                raise ValueError("la réponse n'est pas un flux RSS")
            entries = parsed.entries
        except Exception:
            errors[name] = "flux illisible"
            continue
        answered += 1
        for e in entries:
            link, title = e.get("link"), _strip_html(e.get("title"))
            if not link or not title:
                continue
            summary = _strip_html(e.get("summary"))
            if keep_filter and not is_supply_related(title + " " + summary):
                continue
            published = parse_dt(e.get("published_parsed") or e.get("updated_parsed") or e.get("published") or e.get("updated"))
            if since is not None and published is not None and published < since:
                continue
            rows.append(Article(source_id=f"rss:{name}:{url_hash(link)}", source_type="rss", url=link, title=title,
                                text=summary, published_at=published, domain=name))
    report["rss"] = {"status": "ok" if answered == len(feeds) else "partial" if answered else "failed",
                     "flux": len(feeds), "reponses": answered, "articles": len(rows), "echecs": errors}
    return finalize_articles(rows)


# ----------------------------------------------------------------------------- replay GKG 2.1
GKG_COLS = ["GKGRECORDID", "DATE", "SourceCollectionIdentifier", "SourceCommonName", "DocumentIdentifier",
            "Counts", "V2Counts", "Themes", "V2Themes", "Locations", "V2Locations", "Persons", "V2Persons",
            "Organizations", "V2Organizations", "V2Tone", "Dates", "GCAM", "SharingImage", "RelatedImages",
            "SocialImageEmbeds", "SocialVideoEmbeds", "Quotations", "AllNames", "Amounts", "TranslationInfo", "Extras"]
GKG_BASE = "http://data.gdeltproject.org/gdeltv2/"
_SEARCH_COLS = ["V2Organizations", "AllNames", "DocumentIdentifier", "Extras"]


def _read_gkg_zip(content: bytes) -> Optional[list[dict]]:
    """Lit un fichier .gkg.csv.zip (octets). Renvoie None si le fichier est illisible ; saute les lignes mal formées."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            with z.open(z.namelist()[0]) as fh:
                rows = []
                for line in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                    parts = line.rstrip("\r\n").split("\t")
                    if len(parts) == len(GKG_COLS):
                        rows.append(dict(zip(GKG_COLS, parts)))
                return rows
    except Exception as e:
        log.warning("fichier GKG illisible : %s : %s", type(e).__name__, str(e)[:80])
        return None


def _gkg_to_articles(rows: list[dict], patterns: list[str]) -> list[Article]:
    rx = re.compile("|".join(re.escape(p.lower()) for p in patterns))
    out = []
    for r in rows:
        if not rx.search(" ".join(r.get(c, "") for c in _SEARCH_COLS).lower()):
            continue
        m = re.search(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", r.get("Extras", ""))
        title = html.unescape(m.group(1)) if m and m.group(1) else r["DocumentIdentifier"]   # pas de titre : l'URL
        lang = re.search(r"srclc:(\w+)", r.get("TranslationInfo", ""))
        try:
            published = datetime.strptime(r["DATE"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            published = None
        out.append(Article(source_id="gkg:" + r["GKGRECORDID"], source_type="gkg", url=r["DocumentIdentifier"],
                           title=title, published_at=published, domain=r.get("SourceCommonName"),
                           language=lang.group(1) if lang else "eng"))
    return out


def ingest_gkg_replay(start: str, end: str, patterns: list[str], step_minutes: int = 15, include_translated: bool = True,
                      max_files: int = 200, cache_dir: Optional[Path] = None, local_dir: Optional[Path] = None,
                      report: Optional[dict] = None) -> list[Article]:
    """Rejoue une période passée à partir des fichiers bruts GKG 2.1 (un fichier toutes les 15 minutes).

    start, end : dates "AAAA-MM-JJ" (end inclus). local_dir : dossier de *.gkg.csv.zip déjà téléchargés.
    Un fichier absent chez GDELT (404) n'est pas une panne. Trois échecs réseau de suite : arrêt.
    """
    report = {} if report is None else report
    cache_dir = Path(cache_dir or settings.cache_dir / "gkg")
    t0 = datetime.fromisoformat(start)
    t1 = datetime.fromisoformat(end) + (timedelta(days=1) if len(str(end)) <= 10 else timedelta(0))
    suffixes = [".gkg.csv.zip"] + ([".translation.gkg.csv.zip"] if include_translated else [])
    if local_dir is not None:
        lo, hi = t0.strftime("%Y%m%d%H%M%S"), t1.strftime("%Y%m%d%H%M%S")
        jobs = [(p.name, p) for p in sorted(Path(local_dir).glob("*.gkg.csv.zip")) if lo <= p.name[:14] < hi]
    else:
        cache_dir.mkdir(parents=True, exist_ok=True)
        jobs, ts = [], t0
        while ts < t1:
            jobs += [(f"{ts:%Y%m%d%H%M%S}{suf}", None) for suf in suffixes]
            ts += timedelta(minutes=step_minutes)
    requested, truncated = len(jobs), len(jobs) > max_files
    jobs = jobs[:max_files]

    found: list[Article] = []
    stats: Counter = Counter()
    net_failures = 0
    for i, (name, path) in enumerate(jobs):
        path = path or cache_dir / name
        if path.exists():
            content = path.read_bytes()
            stats["cache"] += 1
        else:
            if net_failures >= 3:
                stats["non_tentes"] = len(jobs) - i
                break
            info: dict = {}
            r = http_get(GKG_BASE + name, timeout=60, retries=2, info=info)
            if r is None and info.get("status") == 404:      # trou de 15 minutes chez GDELT : pas une panne
                stats["absents"] += 1
                continue
            if r is None:
                stats["echecs_reseau"] += 1
                net_failures += 1
                continue
            net_failures = 0
            content = r.content
            path.write_bytes(content)
            stats["telecharges"] += 1
        rows = _read_gkg_zip(content)
        if rows is None:
            stats["illisibles"] += 1
            continue
        found += _gkg_to_articles(rows, patterns)
    out = finalize_articles(found)
    read = stats["cache"] + stats["telecharges"] - stats["illisibles"]
    incomplete = truncated or stats["echecs_reseau"] or stats["non_tentes"] or stats["illisibles"]
    report["gkg"] = {"status": "failed" if read == 0 else "partial" if incomplete else "ok",
                     "fichiers_demandes": requested, "fichiers_lus": read, "absents": stats["absents"],
                     "echecs_reseau": stats["echecs_reseau"], "illisibles": stats["illisibles"],
                     "periode_tronquee": bool(truncated or stats["non_tentes"]), "articles": len(out)}
    return out
