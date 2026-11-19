"""Résilience de la collecte médias en live : cache GDELT, repli Google News, flux de rechange. Aucun accès réseau."""
import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

gdeltdoc = pytest.importorskip("gdeltdoc")
pytest.importorskip("feedparser")
from gdeltdoc.errors import RateLimitError  # noqa: E402

from src.agents import media_sources as ms  # noqa: E402

END = datetime.now(timezone.utc)
START = END - timedelta(days=7)
STAMP = (END - timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
PUBDATE = (END - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")

GDELT_ROWS = pd.DataFrame([
    {"url": "https://example.org/strike", "title": "Dockworkers strike closes the port", "seendate": STAMP,
     "domain": "example.org", "language": "English", "sourcecountry": "Netherlands"},
    {"url": "https://example.org/shortage", "title": "Chip shortage halts factory", "seendate": STAMP,
     "domain": "example.org", "language": "English", "sourcecountry": "Germany"}])

GOOGLE_FEED = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>search - Google News</title>
 <item><title>Port strike disrupts supply chain - Example Times</title>
  <link>https://news.google.com/rss/articles/AAA?oc=5</link><guid isPermaLink="false">AAA</guid>
  <pubDate>{PUBDATE}</pubDate><source url="https://example.com">Example Times</source></item>
 <item><title>Factory shortage worsens - Daily Sample</title>
  <link>https://news.google.com/rss/articles/BBB?oc=5</link><guid isPermaLink="false">BBB</guid>
  <pubDate>{PUBDATE}</pubDate><source url="https://sample.com">Daily Sample</source></item>
 <item><title>Old story - Example Times</title><link>https://news.google.com/rss/articles/CCC</link>
  <guid isPermaLink="false">CCC</guid><pubDate>Mon, 01 Jan 2024 08:00:00 GMT</pubDate>
  <source url="https://example.com">Example Times</source></item>
</channel></rss>""".encode()


class Resp:
    def __init__(self, content):
        self.content = content


@pytest.fixture
def gdelt(monkeypatch):
    """Faux client GDELT : `calls` compte les requêtes, `mode` choisit la réponse."""
    state = {"calls": 0, "mode": "ok"}
    def article_search(self, filters):
        state["calls"] += 1
        if state["mode"] == "rate_limit":
            raise RateLimitError("429")
        if state["mode"] == "down":
            raise ConnectionError("réseau coupé")
        return GDELT_ROWS
    monkeypatch.setattr(gdeltdoc.GdeltDoc, "article_search", article_search)
    monkeypatch.setattr(ms.settings, "gdelt_retry_pause_s", 0)
    return state


@pytest.fixture
def google(monkeypatch):
    seen = []
    def http_get(url, params=None, info=None, **k):
        seen.append((url, params))
        return Resp(GOOGLE_FEED)
    monkeypatch.setattr(ms, "http_get", http_get)
    return seen


def test_gdelt_cache_avoids_repeated_calls(gdelt):
    r1, r2 = {}, {}
    first = ms.ingest_gdelt_live(START, END, report=r1)
    again = ms.ingest_gdelt_live(START, END + timedelta(minutes=2), report=r2)      # second clic, deux minutes plus tard
    assert gdelt["calls"] == 1, "la seconde collecte vient du cache disque"
    assert [a.source_id for a in again] == [a.source_id for a in first] and len(first) == 2
    assert r1["gdelt"] == {"status": "ok", "requetes": 1, "reponses": 1, "articles": 2, "plafond_atteint": False}
    assert r2["gdelt"]["cache"] is True and r2["gdelt"]["requetes"] == 0 and r2["gdelt"]["status"] == "ok"
    assert again[0].published_at == first[0].published_at and again[0].source_type == "gdelt"


def test_gdelt_cache_expires_and_can_be_bypassed(gdelt, monkeypatch):
    ms.ingest_gdelt_live(START, END)
    ms.ingest_gdelt_live(START, END, use_cache=False)
    assert gdelt["calls"] == 2
    monkeypatch.setattr(ms, "GDELT_CACHE_TTL_S", 0)                 # cache périmé
    ms.ingest_gdelt_live(START, END)
    assert gdelt["calls"] == 3


def test_cache_is_keyed_by_query(gdelt):
    ms.ingest_gdelt_live(START, END)
    ms.ingest_gdelt_live(START, END, keywords=["earthquake"])
    assert gdelt["calls"] == 2


def test_rate_limit_falls_back_to_google_news(gdelt, google):
    gdelt["mode"] = "rate_limit"
    report = {}
    arts = ms.ingest_gdelt_with_fallback(START, END, report=report)
    assert gdelt["calls"] == 2, "une pause puis un seul nouvel essai"
    assert report["gdelt"]["status"] == "failed" and report["gdelt"]["rate_limited"] is True
    assert report["google_news"]["status"] == "ok" and "limite de débit" in report["google_news"]["motif"]
    assert [a.title for a in arts] == ["Port strike disrupts supply chain", "Factory shortage worsens"], \
        "le nom du média est retiré du titre, l'article hors période est écarté"
    assert all(a.source_id.startswith("gnews:") and a.source_type == "google_news" for a in arts)
    assert arts[0].domain == "Example Times"
    url, params = google[0]
    assert url == ms.GOOGLE_NEWS_URL and params["hl"] == "en-US"
    assert params["q"] == '(strike OR shortage OR bankruptcy OR cyberattack OR sanction) ("supply chain" OR factory OR port) when:7d'


def test_cooldown_after_rate_limit(gdelt, google):
    gdelt["mode"] = "rate_limit"
    ms.ingest_gdelt_with_fallback(START, END, report={})
    report = {}
    arts = ms.ingest_gdelt_with_fallback(START, END, report=report)             # clic suivant
    assert gdelt["calls"] == 2, "GDELT n'est pas rappelé pendant la période de repos"
    assert report["gdelt"]["rate_limited"] and "n'est pas rappelé" in report["gdelt"]["detail"]
    assert len(google) == 1 and report["google_news"]["cache"] is True and len(arts) == 2


def test_no_fallback_when_gdelt_answers_or_network_is_down(gdelt, google):
    report = {}
    ms.ingest_gdelt_with_fallback(START, END, report=report)
    assert "google_news" not in report and google == []
    gdelt["mode"] = "down"
    report = {}
    assert ms.ingest_gdelt_with_fallback(START, END, report=report, use_cache=False) == []
    assert report["gdelt"]["status"] == "failed" and "rate_limited" not in report["gdelt"]
    assert "google_news" not in report, "le repli ne sert que pour la limite de débit"


def test_google_news_failure_is_reported(gdelt, monkeypatch):
    gdelt["mode"] = "rate_limit"
    def refused(url, params=None, info=None, **k):
        info.update(status=503, error=None)
    monkeypatch.setattr(ms, "http_get", refused)
    report = {}
    assert ms.ingest_gdelt_with_fallback(START, END, report=report) == []
    assert report["google_news"] == {"status": "failed", "requetes": 1, "articles": 0,
                                     "motif": "repli : GDELT en limite de débit", "detail": "HTTP 503"}


def test_media_agent_live_with_fallback_is_success_but_degraded(service, gdelt, google, monkeypatch):
    """GDELT en limite de débit : l'agent répond avec des articles réels de Google News et se déclare incomplet."""
    gdelt["mode"] = "rate_limit"
    monkeypatch.setattr(ms, "RSS_FEEDS", {})
    res = asyncio.run(service.agents["media"].run(mode="live"))
    assert res.status == "success" and res.degraded
    assert {k: v["status"] for k, v in res.sources.items()} == {"gdelt": "failed", "google_news": "ok", "rss": "ok"}
    assert all(m.source_id.startswith("gnews:") for e in res.events for m in e.media)
    assert "incomplet" in res.message


def test_default_feeds_no_longer_use_the_dead_url():
    assert "latribune_industrie" not in ms.RSS_FEEDS
    assert ms.RSS_FEEDS["supplychaindive"].startswith("https://www.supplychaindive.com/")
    assert all(isinstance(u, (str, list)) for u in ms.RSS_FEEDS.values())


def test_rss_spare_urls_are_tried_in_order(monkeypatch):
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
      <item><title>Port strike</title><link>https://example.org/a</link></item></channel></rss>"""
    calls = []
    def http_get(url, info=None, **k):
        calls.append(url)
        if "mort" in url:
            info.update(status=404, error=None)
            return None
        return Resp(feed)
    monkeypatch.setattr(ms, "http_get", http_get)
    report = {}
    arts = ms.ingest_rss({"industrie": ["https://example.org/mort", "https://example.org/vivant"]}, report=report)
    assert calls == ["https://example.org/mort", "https://example.org/vivant"]
    assert len(arts) == 1 and report["rss"]["status"] == "ok" and report["rss"]["echecs"] == {}
