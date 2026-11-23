"""Chaîne NLP de l'agent médias, reprise du notebook v2 (sections 2 à 5) sans pandas.

Stratégie hybride : baseline déterministe (spaCy + EntityRuler ou expressions régulières, mots-clés,
TF-IDF + régression logistique), et LLM local optionnel guidé par un prompt strict, avec repli automatique.
Quatre champs sont toujours calculés par le code, jamais par le LLM : date, coordonnées, identifiants, media.
L'agent qualifie l'événement ; il ne calcule aucun score de gravité (rôle du moteur de graphe).
"""
from __future__ import annotations

import csv
import html
import json
import logging
import re
import time
from collections import Counter
from datetime import timedelta
from typing import Optional

from src.agents.media_sources import EVENT_KEYWORDS, Article
from src.config import settings
from src.schemas.events import (MEDIA_EVENT_TYPES, EntityRef, EventInfo, EventMeta, Location, MediaRef,
                                NormalizedEvent)
from src.utils.llm import LLMError, call_llm, llm_available, parse_llm_json
from src.utils.text import contains_term, norm_key, normalize_url

log = logging.getLogger("supplychain.media")

ROLES = ["touché", "mentionné"]
SPACY_MODEL = "xx_ent_wiki_sm"
_ORG_STOP = {norm_key(x) for x in ["Entity List", "Goods Availability Act", "Ministry of Commerce"]}
_LABEL_TO_TYPE = {"ORG": "entreprise", "LOC": "lieu", "GPE": "lieu", "PORT": "port"}

# Jeu d'amorçage du notebook v2 : 64 phrases écrites à la main, 8 par type. Il sert à faire tourner la chaîne,
# pas à mesurer une performance. Il ne contient aucune phrase sur les crises rejouées (pas de fuite).
SEED_EXAMPLES = {
    "greve": [
        "Dockworkers begin an indefinite strike at the container terminal",
        "Union calls a 48-hour walkout at the car assembly plant",
        "Rail freight drivers vote for industrial action over pay",
        "Les salariés de l'usine votent la grève illimitée",
        "Débrayage massif chez l'équipementier automobile après l'échec des négociations",
        "Streik legt das Werk des Zulieferers lahm",
        "Port workers walk off the job, halting cargo handling",
        "Truck drivers strike blocks deliveries to factories",
    ],
    "catastrophe": [
        "Magnitude 7 earthquake forces chip fabs to evacuate",
        "Severe floods submerge industrial park and close factories",
        "Typhoon makes landfall, plants suspend operations",
        "Huge fire destroys warehouse of electronics supplier",
        "Un séisme endommage plusieurs usines de composants",
        "Inondations : la zone industrielle sous les eaux, production à l'arrêt",
        "Hurricane shuts down quartz mines and nearby plants",
        "Explosion at chemical plant kills workers and halts output",
    ],
    "sanction": [
        "Washington adds chipmaker to trade blacklist, restricting exports",
        "New export controls target advanced semiconductor equipment",
        "EU imposes sanctions on metals producer",
        "Government bans exports of rare earth magnets without licence",
        "Pékin impose des restrictions à l'exportation de terres rares",
        "Le gouvernement place l'entreprise sous tutelle au nom de la sécurité nationale",
        "Embargo on steel imports comes into force",
        "Company added to the Entity List over national security concerns",
    ],
    "faillite": [
        "Auto parts supplier files for bankruptcy protection",
        "Battery maker enters insolvency proceedings after funding collapse",
        "Seat manufacturer placed in receivership",
        "L'équipementier est placé en redressement judiciaire",
        "Liquidation judiciaire prononcée pour le fabricant de pièces",
        "Zulieferer meldet Insolvenz an",
        "Supplier files for Chapter 11 amid falling orders",
        "Creditors push tyre maker into administration",
    ],
    "cyberattaque": [
        "Ransomware attack forces carmaker to shut down IT systems",
        "Hackers breach supplier network, production systems offline",
        "Cyberattack halts operations at logistics group",
        "Une cyberattaque paralyse les usines du constructeur",
        "Rançongiciel : l'équipementier coupe ses serveurs",
        "Cyberangriff legt Produktion beim Autobauer lahm",
        "Data breach at parts maker exposes customer files",
        "Factory lines stopped after malware infects control systems",
    ],
    "penurie": [
        "Chip shortage forces automaker to cut output at two plants",
        "Carmaker halts production line because of missing components",
        "Supplier warns it cannot guarantee deliveries of parts",
        "Pénurie de composants : l'usine réduit sa production de moitié",
        "Arrêt de production d'une semaine faute de pièces",
        "Lieferengpass bei Halbleitern stoppt die Bänder",
        "Magnet shortage idles SUV assembly plant for a week",
        "Automakers warn of supply disruption as stocks run low",
    ],
    "logistique": [
        "Container ship runs aground and blocks canal traffic",
        "Port congestion delays cargo for weeks",
        "Port closed to vessels after bridge collapse",
        "Shipping lines reroute vessels around the cape, adding two weeks",
        "Fermeture du port : les navires déroutés",
        "Low water on the Rhine restricts barge traffic",
        "Rail line closure cuts freight link to the terminal",
        "Border delays leave trucks queuing for days",
    ],
    "aucun": [
        "City council approves new bike lanes downtown",
        "Football club wins the national championship",
        "Carmaker unveils new electric SUV at motor show",
        "Le groupe annonce de bons résultats trimestriels",
        "Company appoints new chief financial officer",
        "Museum opens exhibition on modern art",
        "Supplier opens new research centre and hires engineers",
        "Shares rise after strong quarterly earnings",
    ],
}

LLM_SYSTEM_PROMPT = """Tu es l'agent Médias d'un système d'alerte sur les risques de chaîne d'approvisionnement.
Tu reçois des articles de presse qui décrivent UN SEUL événement. Tu renvoies UN SEUL objet JSON.

FORMAT DE SORTIE OBLIGATOIRE
Exactement ces 5 clés, dans cet ordre, sans aucune autre clé :
{
  "event": {"id": "<identifiant fourni>", "type": "<type>", "label": "<phrase>"},
  "date": "AAAA-MM-JJ",
  "location": {"name": "<lieu>" ou null, "lat": null, "lon": null},
  "entities": [{"id": null, "name": "<entreprise>", "role": "touché" ou "mentionné"}],
  "media": [{"titre": "<titre>", "date": "<date>", "source_id": "<source_id>"}]
}

RÈGLES
1. Réponds uniquement avec l'objet JSON. Aucun texte avant ou après, aucune balise Markdown, aucun commentaire.
2. event.id : recopie l'identifiant fourni, sans le modifier.
3. event.type : une seule valeur de cette liste fermée :
   greve (arrêt de travail), catastrophe (catastrophe naturelle ou accident industriel),
   sanction (sanction, restriction d'exportation, saisie ou mise sous tutelle par un État),
   faillite (faillite, insolvabilité), cyberattaque, penurie (pénurie de composants, arrêt ou baisse de production),
   logistique (perturbation d'un port, d'une route maritime ou d'un transport),
   aucun (aucune perturbation d'une chaîne d'approvisionnement).
4. event.label : une seule phrase en français, 120 caractères au maximum, qui résume l'événement.
5. date : la date de publication de l'article le plus ancien, au format AAAA-MM-JJ.
6. location.name : le lieu où l'événement se produit (site ou port, sinon ville, sinon pays), écrit comme dans les
   articles. null si aucun lieu n'est cité. lat et lon valent toujours null : le système les calcule.
7. entities : uniquement les entreprises nommées dans les articles. Jamais de gouvernement, de ministère, de pays ni
   de personne. role = "touché" si l'entreprise subit directement l'événement, sinon "mentionné".
   id vaut toujours null : le système l'attribue. Liste vide si aucune entreprise n'est citée.
8. media : un objet par article fourni. Recopie titre, date et source_id sans les modifier. N'ajoute aucun article.
9. N'invente rien. N'utilise aucune connaissance extérieure aux articles fournis.
   Une information absente des articles vaut null ou une liste vide."""

BROAD_CONFIDENCE = 0.40       # confiance d'un événement rattaché par un indice large (même valeur que le moteur)
MAX_BROAD_NODES = 8           # un indice très large (un grand pays) ne rattache pas plus de 8 nœuds
_classifier = None
_NLP_CACHE: dict = {}
_classifier_desc = ""


def keyword_classify(text: str) -> tuple[str, int, list[str]]:
    """Renvoie (type, nombre de mots-clés trouvés, mots-clés trouvés). Les mots-clés servent d'explication."""
    t = norm_key(text)
    hits = {cat: [kw for kw in kws if re.search(rf"(?<!\w){re.escape(norm_key(kw))}", t)]
            for cat, kws in EVENT_KEYWORDS.items()}
    best = max(hits, key=lambda c: len(hits[c]))
    return (best, len(hits[best]), hits[best]) if hits[best] else ("aucun", 0, [])


def _training_set() -> tuple[list[str], list[str], str]:
    """Échantillon annoté par l'équipe s'il existe (data/annotated/articles_annotes.csv), sinon jeu d'amorçage."""
    path = settings.data_dir / "annotated" / "articles_annotes.csv"
    if path.exists():
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("text") and r.get("label") in MEDIA_EVENT_TYPES]
            if len(rows) >= 20 and len({r["label"] for r in rows}) >= 2:
                return [r["text"] for r in rows], [r["label"] for r in rows], f"échantillon annoté ({len(rows)} articles)"
            log.warning("Échantillon annoté trop petit ou à une seule classe : jeu d'amorçage utilisé.")
        except Exception as e:
            log.warning("Échantillon annoté illisible (%s) : jeu d'amorçage utilisé.", type(e).__name__)
    texts = [t for ts in SEED_EXAMPLES.values() for t in ts]
    labels = [lab for lab, ts in SEED_EXAMPLES.items() for _ in ts]
    return texts, labels, f"jeu d'amorçage ({len(texts)} phrases, non représentatif)"


def get_classifier():
    """TF-IDF sur n-grammes de caractères + régression logistique, entraîné une seule fois."""
    global _classifier, _classifier_desc
    if _classifier is None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        texts, labels, _classifier_desc = _training_set()
        _classifier = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, preprocessor=norm_key),
            LogisticRegression(C=10, max_iter=2000, class_weight="balanced"))
        _classifier.fit(texts, labels)
    return _classifier


def tfidf_classify(texts: list[str]) -> list[tuple[str, float]]:
    clf = get_classifier()
    proba = clf.predict_proba(list(texts))
    return [(str(clf.classes_[p.argmax()]), round(float(p.max()), 3)) for p in proba]


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", html.unescape(str(t))).strip()
    return re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", t) if len(t) > 60 else t     # « Titre - Reuters »


class MediaNLP:
    """Chaîne articles -> événements, paramétrée par les référentiels du graphe (entreprises et lieux)."""

    def __init__(self, companies: list[dict], places: list[dict], soft_terms: Optional[list[dict]] = None,
                 node_names: Optional[dict[str, str]] = None):
        self.soft_terms = soft_terms or []            # indices larges : matières premières, mots-clés sectoriels, pays
        self.node_names = node_names or {}
        self.companies = {c["id"]: c for c in companies}
        self.places = {p["name"]: p for p in places}
        self.company_index = {norm_key(n): c["id"] for c in companies for n in [c["name"], *c.get("aliases", [])]}
        self.place_index = {norm_key(n): p["name"] for p in places for n in [p["name"], *p.get("aliases", [])]}
        self._nlp = None
        self.ner_desc = "non chargé"
        self.journal: list[dict] = []

    # ------------------------------------------------------------------ 2. prétraitement et déduplication
    def preprocess(self, articles: list[Article]) -> list[Article]:
        """Nettoyage, champ `content`, puis doublons exacts (même URL ou même titre) : on garde le plus ancien."""
        far = lambda a: (a.published_at is None, a.published_at.timestamp() if a.published_at else 0.0)
        out, urls, titles = [], set(), set()
        for a in sorted(articles, key=far):
            a.title = clean_title(a.title)
            a.text = re.sub(r"\s+", " ", a.text or "").strip()
            a.content = (a.title + ". " + a.text).strip().rstrip(".") + "."
            ukey, tkey = normalize_url(a.url) if a.url else a.source_id, norm_key(a.title)
            if ukey in urls or tkey in titles:
                continue
            urls.add(ukey)
            titles.add(tkey)
            out.append(a)
        return out

    def deduplicate(self, articles: list[Article]) -> list[Article]:
        """Deux articles sont reliés si leurs titres se ressemblent (cosinus >= seuil) et s'ils sont proches dans le
        temps. Les groupes sont les composantes connexes : un groupe = un événement. Aucun article n'est supprimé."""
        n = len(articles)
        if n > 1:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(
                [norm_key(a.title) for a in articles])
            sim = cosine_similarity(X)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        window = timedelta(hours=settings.window_hours)
        for i in range(n):
            for j in range(i + 1, n):
                ti, tj = articles[i].published_at, articles[j].published_at
                if ti is not None and tj is not None and (tj - ti) > window:
                    break                                   # triés par date : inutile d'aller plus loin
                if sim[i][j] >= settings.sim_threshold:
                    parent[find(j)] = find(i)
        roots = [find(i) for i in range(n)]
        order = {r: k for k, r in enumerate(dict.fromkeys(roots), start=1)}
        for a, r in zip(articles, roots):
            a.cluster_id = f"evt_{order[r]:04d}"
        return articles

    # ------------------------------------------------------------------ 3. entités
    def _patterns(self) -> list[dict]:
        pats = []
        for c in self.companies.values():
            for alias in [c["name"], *c.get("aliases", [])]:
                pats.append({"label": "ORG", "pattern": alias, "id": c["id"]})
        for p in self.places.values():
            for alias in [p["name"], *p.get("aliases", [])]:
                pats.append({"label": "PORT" if p["kind"] == "port" else "LOC", "pattern": alias, "id": p["name"]})
        name = {"IS_TITLE": True, "OP": "+"}
        pats += [
            {"label": "PORT", "pattern": [{"LOWER": "port"}, {"LOWER": "of"}, name]},
            {"label": "PORT", "pattern": [{"LOWER": "port"}, {"LOWER": {"IN": ["de", "du", "d'"]}}, name]},
            {"label": "PORT", "pattern": [{"LOWER": "hafen"}, {"LOWER": "von", "OP": "?"}, name]},
        ]
        return pats

    def _load_nlp(self):
        """spaCy + EntityRuler si disponible. Le modèle n'est jamais téléchargé au vol : sans lui, chaîne vide +
        EntityRuler (référentiels seulement). Sans spaCy : expressions régulières sur les alias."""
        if self._nlp is not None or self.ner_desc != "non chargé":
            return self._nlp
        key = json.dumps(self._patterns(), sort_keys=True, ensure_ascii=False)
        if key in _NLP_CACHE:                            # même référentiel : on réutilise la chaîne déjà chargée
            self._nlp, self.ner_desc = _NLP_CACHE[key]
            return self._nlp
        try:
            import spacy
        except Exception:
            self.ner_desc = "spaCy absent : référentiels par expressions régulières"
            return None
        try:
            nlp = spacy.load(SPACY_MODEL, disable=["lemmatizer"])
            self.ner_desc = f"spaCy {SPACY_MODEL} + EntityRuler"
        except Exception:
            nlp = spacy.blank("xx")
            self.ner_desc = "spaCy vide + EntityRuler (référentiels seulement)"
        ruler = nlp.add_pipe("entity_ruler", before="ner" if "ner" in nlp.pipe_names else None,
                             config={"phrase_matcher_attr": "LOWER"})
        ruler.add_patterns(self._patterns())
        self._nlp = nlp
        _NLP_CACHE[key] = (nlp, self.ner_desc)
        return nlp

    def _fallback_entities(self, text: str) -> list[dict]:
        out, norm = [], norm_key(text)
        for index, kind in ((self.company_index, "entreprise"), (self.place_index, "lieu")):
            for key, ref in index.items():
                for m in re.finditer(rf"(?<!\w){re.escape(key)}(?!\w)", norm):
                    etype = kind if kind == "entreprise" else ("port" if self.places[ref]["kind"] == "port" else "lieu")
                    name = self.companies[ref]["name"] if kind == "entreprise" else ref
                    out.append({"text": name, "type": etype, "start": m.start(), "ref_id": ref, "method": "referentiel"})
        return sorted(out, key=lambda e: e["start"])

    def extract_entities(self, text: str) -> list[dict]:
        """Entités d'un texte : {text, type (entreprise, lieu, port), start, ref_id, method}."""
        nlp = self._load_nlp()
        if nlp is None:
            return self._fallback_entities(text)
        ents = []
        for e in nlp(text[:5000]).ents:
            etype = _LABEL_TO_TYPE.get(e.label_)
            if etype is None or len(e.text.strip()) < 2:
                continue
            if etype == "entreprise" and norm_key(e.text) in _ORG_STOP:
                continue
            from_ruler = bool(e.ent_id_) or e.label_ == "PORT"
            ref = e.ent_id_ or self.company_index.get(norm_key(e.text)) or self.place_index.get(norm_key(e.text))
            ents.append({"text": e.text.strip(), "type": etype, "start": e.start_char, "ref_id": ref or None,
                         "method": "entity_ruler" if from_ruler else "spacy_ner"})
        return ents

    def link_company(self, name: str, threshold: int = 90) -> Optional[str]:
        """Rattache un nom d'entreprise au référentiel : alias exact, puis correspondance floue (rapidfuzz)."""
        key = norm_key(name)
        if key in self.company_index:
            return self.company_index[key]
        if len(key) >= 5:
            try:
                from rapidfuzz import fuzz, process
            except Exception:
                return None
            hit = process.extractOne(key, list(self.company_index), scorer=fuzz.token_sort_ratio)
            if hit and hit[1] >= threshold:
                return self.company_index[hit[0]]
        return None

    def build_mentions(self, articles: list[Article]) -> list[dict]:
        rows = []
        for a in articles:
            for e in self.extract_entities(a.content):
                ref = e["ref_id"]
                if e["type"] == "entreprise" and not ref:
                    ref = self.link_company(e["text"])
                rows.append({"source_id": a.source_id, "cluster_id": a.cluster_id, "entity_text": e["text"],
                             "entity_type": e["type"], "ref_id": ref, "method": e["method"],
                             "in_title": e["start"] < len(a.title)})
        return rows

    # ------------------------------------------------------------------ 4. classification
    def classify(self, articles: list[Article]) -> dict[str, dict]:
        """Par article : mots-clés, TF-IDF + régression logistique, puis décision (la plus fiable d'abord)."""
        out = {}
        lr = tfidf_classify([a.content for a in articles]) if articles else []
        for a, (lr_type, lr_conf) in zip(articles, lr):
            kw_type, kw_hits, kw_terms = keyword_classify(a.content)
            if lr_conf >= settings.min_confidence:
                etype, conf, method = lr_type, lr_conf, "tfidf_lr"
            elif kw_hits > 0:
                etype, conf, method = kw_type, 0.5, "mots-cles"     # 0,5 : convention, les mots-clés n'ont pas de probabilité
            else:
                etype, conf, method = "aucun", 0.5, "defaut"
            out[a.source_id] = {"kw_type": kw_type, "kw_terms": kw_terms, "lr_type": lr_type, "lr_conf": lr_conf,
                                "event_type": etype, "type_conf": conf, "type_method": method,
                                "desaccord": kw_type != lr_type}
        return out

    # ------------------------------------------------------------------ 5. événements
    def _place(self, name: str) -> Location:
        p = self.places[name]
        return Location(name=name, lat=p.get("lat"), lon=p.get("lon"))

    def _pick_location(self, mentions: list[dict]) -> Location:
        """Lieu le plus précis du référentiel, puis cité dans un titre, puis le plus cité ; ordre alphabétique sinon."""
        places = [m for m in mentions if m["entity_type"] in ("lieu", "port") and m["ref_id"] in self.places]
        if not places:
            return Location()
        counts = Counter(m["ref_id"] for m in places)
        in_title = {m["ref_id"] for m in places if m["in_title"]}
        best = max(sorted(counts), key=lambda n: (self.places[n]["precision"], n in in_title, counts[n]))
        return self._place(best)

    def _company_entity(self, ref: str, role: str = "touché") -> EntityRef:
        c = self.companies[ref]
        ident = f"LEI:{c['lei']}" if c.get("lei") else f"SUP:{ref}"       # aucun code LEI inventé
        return EntityRef(id=ident, name=c["name"], role=role)

    def _build_entities(self, mentions: list[dict]) -> list[EntityRef]:
        ents, seen = [], set()
        for m in mentions:
            if m["entity_type"] != "entreprise":
                continue
            linked = m["ref_id"] in self.companies
            key = m["ref_id"] if linked else norm_key(m["entity_text"])
            if key in seen:
                continue
            seen.add(key)
            ents.append(self._company_entity(m["ref_id"]) if linked else EntityRef(id=None, name=m["entity_text"], role="mentionné"))
        return ents

    @staticmethod
    def _missing(location: Location, entities: list[EntityRef]) -> list[str]:
        missing = ["weather", "finance"]                     # blocs des autres agents, complétés par la corrélation
        named = [e for e in entities if e.role != "exposé"]
        if location.name is None:
            missing.append("location")
        elif location.lat is None:
            missing.append("location.lat_lon")
        if not named:
            missing.append("entities")
        elif any(not str(e.id).startswith("LEI:") for e in named):
            missing.append("entities.lei")
        if len(named) < len(entities):
            missing.append("rattachement_exact")             # nœuds rattachés par un indice large seulement
        return missing

    def _assemble(self, cid: str, etype: str, label: str, group: list[Article], location: Location,
                  entities: list[EntityRef], confidence: float, extractor: str, detail: str) -> NormalizedEvent:
        """Assemble l'objet final. date, media et donnees_manquantes viennent toujours du code."""
        dates = [a.published_at for a in group if a.published_at is not None]
        media = [MediaRef(titre=a.title, date=a.published_at.strftime("%Y-%m-%dT%H:%M:%SZ") if a.published_at else None,
                          source_id=a.source_id) for a in group]
        return NormalizedEvent(
            event=EventInfo(id=cid, type=etype, label=label),
            date=min(dates).date().isoformat() if dates else None,       # plus ancien article : date du premier signal
            location=location, entities=entities, media=media,
            donnees_manquantes=self._missing(location, entities),
            meta=EventMeta(agent="media", confidence=confidence, extractor=extractor, detail=detail))

    def broad_links(self, group: list[Article]) -> tuple[list[str], list[str]]:
        """Rattachement élargi : nœuds désignés par une matière première ou un mot-clé sectoriel cités dans les
        articles ; à défaut seulement, par un pays. Renvoie (identifiants de nœuds, indices trouvés)."""
        corpus = norm_key(" ".join(a.content for a in group))
        for kinds in (("matière première", "mot-clé sectoriel"), ("pays",)):
            nodes, clues = [], []
            for t in self.soft_terms:
                if t["kind"] not in kinds:
                    continue
                # pays : mot entier ; matières et mots-clés : début de mot, pour accepter les pluriels
                hit = contains_term(corpus, t["term"]) if t["kind"] == "pays" else \
                    bool(re.search(rf"(?<!\w){re.escape(t['term'])}", corpus))
                if hit:
                    clues.append(f"{t['kind']} « {t['term']} »")
                    nodes += [n for n in t["node_ids"] if n not in nodes]
            if nodes:
                return nodes[:MAX_BROAD_NODES], clues
        return [], []

    def baseline_event(self, cid: str, group: list[Article], mentions: list[dict], cls: dict,
                       broad: bool = False) -> Optional[NormalizedEvent]:
        """Événement d'un groupe par la baseline NLP. None si le groupe est classé « aucun ».

        broad=True : si les articles ne citent ni entreprise ni site du référentiel, l'événement est rattaché aux
        nœuds désignés par un indice large, avec le rôle « exposé » et une confiance de 0,40."""
        votes = Counter(cls[a.source_id]["event_type"] for a in group)
        top = max(votes.values())
        etype = sorted(t for t, v in votes.items() if v == top)[0]
        if etype == "aucun":
            return None
        conf = max(cls[a.source_id]["type_conf"] for a in group if cls[a.source_id]["event_type"] == etype)
        methods = sorted({cls[a.source_id]["type_method"] for a in group if cls[a.source_id]["event_type"] == etype})
        location, entities = self._pick_location(mentions), self._build_entities(mentions)
        detail = "type : " + ", ".join(methods)
        exact = any(e.role == "touché" for e in entities) or \
            (location.name in self.places and self.places[location.name]["precision"] >= 2)
        if broad and not exact:
            nodes, clues = self.broad_links(group)
            if nodes:
                entities += [EntityRef(id=f"NODE:{n}", name=self.node_names.get(n, n), role="exposé") for n in nodes]
                conf = BROAD_CONFIDENCE
                detail += f" ; rattachement élargi (confiance {BROAD_CONFIDENCE:.2f}) par " + ", ".join(clues[:4])
        return self._assemble(cid, etype, group[0].title, group, location, entities, conf, "baseline", detail)

    @staticmethod
    def _llm_user_prompt(cid: str, group: list[Article], max_articles: int = 5, max_chars: int = 1500) -> str:
        arts = [{"source_id": a.source_id, "date": a.published_at.strftime("%Y-%m-%d") if a.published_at else None,
                 "titre": a.title, "texte": str(a.text)[:max_chars]} for a in group[:max_articles]]
        return (f"Identifiant de l'événement : {cid}\n"
                f"Articles ({len(arts)}) au format JSON :\n{json.dumps(arts, ensure_ascii=False, indent=1)}")

    def llm_event(self, cid: str, group: list[Article], mentions: list[dict],
                  timeout: Optional[float] = None) -> tuple[Optional[NormalizedEvent], list[str]]:
        """Événement par le LLM, contrôlé point par point et ancré dans les articles.

        Renvoie (événement ou None si « aucun », corrections appliquées). Lève LLMError si la sortie est inutilisable.
        """
        raw = parse_llm_json(call_llm(LLM_SYSTEM_PROMPT, self._llm_user_prompt(cid, group), timeout=timeout))
        notes: list[str] = []
        missing_keys = [k for k in ("event", "date", "location", "entities", "media") if k not in raw]
        if missing_keys:
            raise LLMError(f"clés manquantes : {missing_keys}")
        event = raw["event"] if isinstance(raw["event"], dict) else {}
        etype = event.get("type")
        if etype not in MEDIA_EVENT_TYPES:
            raise LLMError(f"type hors liste : {etype!r}")
        if etype == "aucun":
            return None, ["classé « aucun » par le LLM"]
        label = re.sub(r"\s+", " ", str(event.get("label") or "")).strip()
        if not label:
            label = group[0].title
            notes.append("label vide : titre du premier article utilisé")
        label = label[:200]
        corpus = norm_key(" ".join(a.content for a in group))

        # Lieu : référentiel d'abord, sinon nom présent dans le texte (sans coordonnées), sinon lieu de la baseline
        loc = raw["location"] if isinstance(raw["location"], dict) else {}
        name = loc.get("name")
        if isinstance(name, str) and name.strip() and contains_term(corpus, name):
            ref = self.place_index.get(norm_key(name))
            location = self._place(ref) if ref else Location(name=name.strip())
        else:
            location = self._pick_location(mentions)
            if isinstance(name, str) and name.strip():
                notes.append(f"lieu « {name} » absent des articles : lieu de la baseline utilisé")

        # Entités : seulement celles écrites dans les articles ; identifiants attribués par le référentiel
        entities, seen = [], set()
        for e in raw["entities"] if isinstance(raw["entities"], list) else []:
            if not isinstance(e, dict) or not isinstance(e.get("name"), str) or not e["name"].strip():
                continue
            ename = e["name"].strip()
            ref = self.link_company(ename)
            aliases = [self.companies[ref]["name"], *self.companies[ref].get("aliases", [])] if ref else [ename]
            if not any(contains_term(corpus, a) for a in aliases):
                notes.append(f"entité « {ename} » absente des articles : écartée")      # anti-hallucination
                continue
            key = ref or norm_key(ename)
            if key in seen:
                continue
            seen.add(key)
            role = e.get("role") if e.get("role") in ROLES else ("touché" if ref else "mentionné")
            entities.append(self._company_entity(ref, role) if ref else EntityRef(id=None, name=ename, role=role))
        try:
            return self._assemble(cid, etype, label, group, location, entities, 0.7, "llm",
                                  " ; ".join(notes) or "sortie conforme"), notes     # 0,7 : convention pour le LLM
        except ValueError as err:
            raise LLMError(f"sortie non conforme au schéma ({str(err)[:80]})")

    def extract_events(self, articles: list[Article], use_llm: Optional[bool] = None,
                       broad: bool = False) -> list[NormalizedEvent]:
        """Articles (schéma commun) -> événements. Ne lève pas d'exception sur une panne du LLM.

        broad : active le rattachement élargi de la baseline (voir `baseline_event`)."""
        use_llm = settings.use_llm if use_llm is None else use_llm
        self.journal = []
        if not articles:
            return []
        arts = self.deduplicate(self.preprocess(articles))
        cls = self.classify(arts)
        mentions = self.build_mentions(arts)

        llm_on = bool(use_llm) and llm_available()
        if use_llm and not llm_on:
            log.warning("LLM injoignable à %s : bascule sur la baseline NLP.", settings.llm_base_url)
        reason = "USE_LLM = False" if not use_llm else "serveur LLM injoignable"

        clusters = list(dict.fromkeys(a.cluster_id for a in arts))
        groups = {cid: [a for a in arts if a.cluster_id == cid] for cid in clusters}
        ments_by = {cid: [m for m in mentions if m["cluster_id"] == cid] for cid in clusters}

        # LLM sur CPU : seuls les groupes les plus pertinents y passent, du plus pertinent au moins pertinent, chacun
        # avec un délai strict, dans un budget global. Tous les autres sont traités par la baseline NLP.
        ranked = sorted(clusters, key=lambda c: self.relevance(groups[c], ments_by[c], cls), reverse=True)
        llm_set = set(ranked[:max(0, settings.llm_max_articles)]) if llm_on else set()
        llm_out: dict[str, tuple] = {}
        net_failures, started = 0, time.monotonic()
        for cid in (c for c in ranked if c in llm_set):
            left = settings.llm_budget_s - (time.monotonic() - started)
            if net_failures >= 2:
                llm_out[cid] = (None, "baseline", "repli sur la baseline : LLM désactivé après deux pannes réseau")
            elif left < 1:
                llm_out[cid] = (None, "baseline", f"repli sur la baseline : budget LLM de {settings.llm_budget_s:g} s épuisé")
            else:
                try:
                    ev, notes = self.llm_event(cid, groups[cid], ments_by[cid], timeout=min(settings.llm_article_timeout_s, left))
                    llm_out[cid] = (ev, "llm", " ; ".join(notes) or "sortie conforme")
                    net_failures = 0
                except LLMError as e:
                    net_failures += int(e.network)
                    llm_out[cid] = (None, "baseline", f"repli sur la baseline : {e}")
                except Exception as e:                   # le LLM ne doit jamais faire planter la chaîne
                    llm_out[cid] = (None, "baseline", f"repli sur la baseline : erreur inattendue {type(e).__name__}")

        events = []
        for cid in clusters:
            group, ments = groups[cid], ments_by[cid]
            if cid in llm_out:
                ev, extractor, detail = llm_out[cid]
            elif llm_on:
                ev, extractor, detail = None, "baseline", (f"baseline : hors des {settings.llm_max_articles} groupes "
                                                           "les plus pertinents confiés au LLM")
            else:
                ev, extractor, detail = None, "baseline", reason
            if extractor == "baseline":
                ev = self.baseline_event(cid, group, ments, cls, broad=broad)
            if ev is None and extractor == "baseline":
                detail += " ; classé « aucun »"
            self.journal.append({"event_id": cid, "extracteur": extractor, "detail": detail})
            if ev is not None:
                events.append(ev)
        return events

    @staticmethod
    def relevance(group: list[Article], mentions: list[dict], cls: dict) -> float:
        """Pertinence d'un groupe pour la supply chain : articles classés comme perturbation (et confiance),
        entreprises, sites et ports du référentiel cités, taille du groupe (couverture presse)."""
        typed = [cls[a.source_id] for a in group if cls[a.source_id]["event_type"] != "aucun"]
        linked = len({m["ref_id"] for m in mentions if m.get("ref_id")})
        return 2.0 * len(typed) + max((c["type_conf"] for c in typed), default=0.0) + 1.5 * min(linked, 4) + 0.5 * len(group)
