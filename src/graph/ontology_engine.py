"""Moteur d'ontologie et de risque (Bloc 4) sur NetworkX.

Rôle : relier les événements des agents aux nœuds du graphe, corréler les sources, calculer le risque direct,
le propager en cascade, émettre des alertes expliquées, et simuler des pannes (« what-if ») sans toucher
à l'état réel.

Règles de calcul (toutes dans ce fichier, pour pouvoir les expliquer en soutenance) :
  déduplication sémantique = articles du même incident fusionnés (TF-IDF + cosinus) avant tout calcul de gravité
  gravité d'un événement   = BASE_SEVERITY[type] x intensité (mesures météo ou finance ; 1 pour un article)
  confiance d'un signal    = 0,55 + 0,10 par source supplémentaire (2 au plus) + 0,25 par agent supplémentaire
  contribution d'un signal = gravité x confiance x fraîcheur
  risque direct d'un nœud  = 1 - produit(1 - contribution)                       (« ou » probabiliste)
  perte d'un intrant       = somme(part de la source x risque de la source)      (la redondance dilue)
  risque propagé           = transmission x perte de l'intrant le plus touché    (il faut tous les intrants)
  transmission             = DECAY x (1 - min(stock, 60 j) / 120)                (le stock amortit)
  risque total             = 1 - (1 - direct) x (1 - propagé)
Ce sont des règles d'experts, pas un modèle appris : les constantes sont à calibrer par backtesting.
"""
from __future__ import annotations

import difflib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import networkx as nx
import yaml

from src.schemas.events import (Alert, CorrelatedSignal, EntityRef, EventInfo, EventMeta, GraphEdge, GraphNode,
                                GraphState, MitigationAction, MitigationPlan, NodeImpact, NodeState, NormalizedEvent,
                                SimulationResult)
from src.utils.text import contains_term, norm_key

DECAY = 0.95
CORRELATION_WINDOW_DAYS = 3
SOFT_LINK_CONFIDENCE = 0.40          # poids d'un rattachement élargi (rôle « exposé ») par rapport à un rattachement exact
SEMANTIC_DEDUP_THRESHOLD = 0.50      # similarité cosinus minimale entre deux événements médias pour les fusionner
LEVEL_THRESHOLDS = (("critical", 0.60), ("warning", 0.35), ("info", 0.15))
ALERT_THRESHOLD = 0.35

BASE_SEVERITY = {"catastrophe": 0.80, "meteo_extreme": 0.80, "greve": 0.65, "logistique": 0.60, "sanction": 0.70,
                 "faillite": 0.90, "cyberattaque": 0.65, "penurie": 0.60, "tension_marche": 0.45}
# Deux événements de la même famille sur le même nœud décrivent le même aléa : ils se corroborent.
FAMILY = {"catastrophe": "climat", "meteo_extreme": "climat", "greve": "operations", "logistique": "operations",
          "sanction": "reglementaire", "faillite": "financier", "cyberattaque": "cyber",
          "penurie": "approvisionnement", "tension_marche": "marche"}
TYPE_WEIGHT = {"produit_fini": 3.0, "usine": 2.0}
FAMILY_LABELS = {"climat": "climat", "operations": "opérations", "reglementaire": "réglementaire", "financier": "financier",
                 "cyber": "cyber", "approvisionnement": "approvisionnement", "marche": "marché"}
AGENT_LABELS = {"media": "médias", "weather": "météo", "finance": "finance"}


def level_of(risk: float) -> str:
    for name, threshold in LEVEL_THRESHOLDS:
        if risk >= threshold:
            return name
    return "ok"


def pct(x: float) -> str:
    return f"{100 * x:.0f} %"


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _parse_date(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def event_intensity(ev: NormalizedEvent) -> float:
    """Intensité entre 0,3 et 1 tirée des mesures brutes des agents météo et finance. 1 pour un article."""
    if ev.weather is not None:
        gust = ev.weather.gust_max_kmh or ev.weather.wind_max_kmh or 0.0
        rain = ev.weather.precip_mm or 0.0
        return _clip(max((gust - 70) / 110, (rain - 40) / 210), 0.3, 1.0)
    if ev.finance is not None:
        z = abs(ev.finance.zscore) if ev.finance.zscore is not None else 0.0
        return _clip(max(z / 4, abs(ev.finance.change_5d_pct) / 30), 0.3, 1.0)
    return 1.0


@dataclass
class Evaluation:
    """Résultat d'un calcul complet. Immuable du point de vue du moteur : on en fabrique un nouveau à chaque fois."""
    as_of: Optional[str] = None
    events: list[NormalizedEvent] = field(default_factory=list)       # événements après déduplication sémantique
    merged: dict[str, list[str]] = field(default_factory=dict)        # événement gardé -> événements absorbés
    signals: list[CorrelatedSignal] = field(default_factory=list)
    links: dict[str, list[str]] = field(default_factory=dict)        # event_id -> nœuds rattachés
    direct: dict[str, float] = field(default_factory=dict)
    risks: dict[str, dict] = field(default_factory=dict)              # nœud -> direct, propagated, risk, path
    index: float = 0.0


class OntologyEngine:
    def __init__(self, topology: dict):
        self.meta = topology.get("meta", {})
        self.nodes: dict[str, GraphNode] = {}
        self.graph = nx.DiGraph()
        for raw in topology.get("nodes", []):
            node = GraphNode(**raw)
            if node.id in self.nodes:
                raise ValueError(f"nœud en double : {node.id}")
            self.nodes[node.id] = node
            self.graph.add_node(node.id)
        self.edges: list[GraphEdge] = []
        for raw in topology.get("edges", []):
            edge = GraphEdge(**raw)
            for end in (edge.source, edge.target):
                if end not in self.nodes:
                    raise ValueError(f"lien {edge.source} -> {edge.target} : nœud inconnu {end}")
            self.edges.append(edge)
            self.graph.add_edge(edge.source, edge.target, edge=edge)
        self.active = nx.DiGraph((e.source, e.target, {"edge": e}) for e in self.edges if not e.backup)
        self.active.add_nodes_from(self.nodes)
        if not nx.is_directed_acyclic_graph(self.graph):
            raise ValueError("la topologie contient un cycle : la propagation demande un graphe sans cycle")
        self._order = list(nx.topological_sort(self.active))
        self._check_shares()

        self.market_watch: list[dict] = topology.get("market_watch", [])
        self.extra_places: list[dict] = topology.get("gazetteer", [])
        self._alias_index: dict[str, str] = {}       # alias normalisé -> nœud (noms, alias, identifiants)
        self._place_index: dict[str, list[str]] = defaultdict(list)   # lieu normalisé -> nœuds
        for n in self.nodes.values():
            for alias in [n.id, n.name, *n.aliases]:
                self._alias_index.setdefault(norm_key(alias), n.id)
            names = [n.place] if n.place else []
            if n.type in ("port", "hub"):
                names += [n.name, *n.aliases]
            for name in names:
                if n.id not in self._place_index[norm_key(name)]:
                    self._place_index[norm_key(name)].append(n.id)
        for n in self.nodes.values():                # un lieu seul (« Rotterdam ») désigne le nœud qui s'y trouve
            if n.place and len(self._place_index[norm_key(n.place)]) == 1:
                self._alias_index.setdefault(norm_key(n.place), n.id)

        self.events: list[NormalizedEvent] = []
        self.mode: Optional[str] = None
        self.current = self.evaluate([], None)

    # ------------------------------------------------------------------ chargement
    @classmethod
    def from_yaml(cls, path: str | Path) -> "OntologyEngine":
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    def _check_shares(self) -> None:
        shares: dict[tuple[str, str], float] = defaultdict(float)
        for e in self.edges:
            if not e.backup:
                shares[(e.target, e.input)] += e.dependency
        bad = {k: round(v, 3) for k, v in shares.items() if abs(v - 1.0) > 1e-6}
        if bad:
            raise ValueError(f"parts d'intrant différentes de 1 : {bad}")

    # ------------------------------------------------------------------ référentiels pour l'agent médias
    def soft_referential(self) -> list[dict]:
        """Indices larges pour rattacher un article qui ne cite aucun site par son nom.

        Du plus précis au plus vague : nom d'une matière première, mot-clé sectoriel d'un nœud (`keywords`), pays.
        Chaque entrée : {"term", "kind", "node_ids"}.
        """
        merged: dict[tuple[str, str], list[str]] = {}

        def add(term: str, kind: str, nid: str) -> None:
            ids = merged.setdefault((norm_key(term), kind), [])
            if term and nid not in ids:
                ids.append(nid)

        country_names: dict[str, list[str]] = defaultdict(list)
        for p in self.extra_places:
            country_names[norm_key(p["name"])] = [p["name"], *p.get("aliases", [])]
        for n in self.nodes.values():
            if n.type == "matiere_premiere":
                for term in [n.name, *n.aliases]:
                    add(term, "matière première", n.id)
            for term in n.keywords:
                add(term, "mot-clé sectoriel", n.id)
            if n.country:
                for term in country_names.get(norm_key(n.country), [n.country]):
                    add(term, "pays", n.id)
        return [{"term": term, "kind": kind, "node_ids": ids} for (term, kind), ids in merged.items() if term]

    def company_referential(self) -> list[dict]:
        return [{"id": n.id, "name": n.name.split(" (")[0], "aliases": list(n.aliases), "country": n.country}
                for n in self.nodes.values() if n.company]

    def place_referential(self) -> list[dict]:
        """Lieux connus. precision : 3 = port ou hub, 2 = ville d'un site, 1 = pays."""
        places, seen = [], set()
        for n in self.nodes.values():
            if n.type in ("port", "hub") and n.lat is not None:
                places.append({"name": n.name, "aliases": list(n.aliases), "lat": n.lat, "lon": n.lon,
                               "kind": "port", "precision": 3})
                seen.update(norm_key(a) for a in [n.name, *n.aliases])
        for n in self.nodes.values():
            if n.place and n.lat is not None and norm_key(n.place) not in seen:
                places.append({"name": n.place, "aliases": [], "lat": n.lat, "lon": n.lon, "kind": "ville", "precision": 2})
                seen.add(norm_key(n.place))
        for p in self.extra_places:
            if norm_key(p["name"]) not in seen:
                places.append({"name": p["name"], "aliases": list(p.get("aliases", [])), "lat": p.get("lat"),
                               "lon": p.get("lon"), "kind": p.get("kind", "pays"), "precision": 1})
        return places

    def weather_hubs(self) -> list[GraphNode]:
        return [n for n in self.nodes.values() if n.weather_watch and n.lat is not None]

    # ------------------------------------------------------------------ rattachement et corrélation
    def link_weights(self, ev: NormalizedEvent) -> dict[str, float]:
        """Nœuds rattachés à un événement, avec le poids du lien.

        1,0 : entité « touché » (identifiant ou alias) ou lieu de l'événement.
        SOFT_LINK_CONFIDENCE : entité « exposé » (rattachement élargi de l'agent médias).
        """
        found: dict[str, float] = {}
        for ent in ev.entities:
            if ent.role != "touché":
                continue
            nid = ent.id.split(":", 1)[-1] if ent.id else None
            if nid not in self.nodes:
                nid = self._alias_index.get(norm_key(ent.name))
            if nid in self.nodes:
                found.setdefault(nid, 1.0)
        if ev.location.name:
            for nid in self._place_index.get(norm_key(ev.location.name), []):
                found.setdefault(nid, 1.0)
        for ent in ev.entities:
            nid = ent.id.split(":", 1)[-1] if ent.id else None
            if ent.role == "exposé" and nid in self.nodes:
                found.setdefault(nid, SOFT_LINK_CONFIDENCE)
        return found

    def link_event(self, ev: NormalizedEvent) -> list[str]:
        """Nœuds rattachés à un événement (liens exacts d'abord, puis liens élargis)."""
        return list(self.link_weights(ev))

    # ------------------------------------------------------------------ déduplication sémantique
    def semantic_dedupe(self, events: Iterable[NormalizedEvent],
                        threshold: float = SEMANTIC_DEDUP_THRESHOLD) -> tuple[list[NormalizedEvent], dict[str, list[str]]]:
        """Fusionne les événements médias qui racontent le même incident, avant le calcul de gravité.

        Deux événements sont reliés si leurs textes (libellé + titres des articles) se ressemblent (TF-IDF sur
        n-grammes de caractères, cosinus >= seuil), s'ils sont à moins de 3 jours d'écart et s'ils touchent au moins
        un nœud commun (ou aucun nœud tous les deux). Les groupes sont les composantes connexes.
        Sans cette étape, un même incident classé « logistique » par un article et « catastrophe » par un autre
        produirait deux signaux et compterait deux fois dans le risque direct.
        Limite : le TF-IDF ne rapproche pas deux langues ; un article français et un article anglais restent séparés
        (ils se retrouvent quand même dans le même signal s'ils ont la même famille d'aléa).
        """
        events = list(events)
        media = [i for i, e in enumerate(events) if e.meta.agent == "media" and e.event.type != "aucun"]
        if len(media) < 2:
            return events, {}
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except Exception:                                # scikit-learn absent : pas de fusion, le reste fonctionne
            return events, {}
        texts = [norm_key(events[i].event.label + " " + " ".join(m.titre for m in events[i].media)) for i in media]
        sim = cosine_similarity(TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(texts))
        links = [set(self.link_event(events[i])) for i in media]
        dates = [_parse_date(events[i].date) for i in media]
        parent = list(range(len(media)))

        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a in range(len(media)):
            for b in range(a + 1, len(media)):
                close = dates[a] is None or dates[b] is None or abs((dates[a] - dates[b]).days) <= CORRELATION_WINDOW_DAYS
                same_place = bool(links[a] & links[b]) or (not links[a] and not links[b])
                if sim[a][b] >= threshold and close and same_place:
                    parent[find(b)] = find(a)
        groups: dict[int, list[int]] = defaultdict(list)
        for k in range(len(media)):
            groups[find(k)].append(media[k])

        merged: dict[str, list[str]] = {}
        replace: dict[int, Optional[NormalizedEvent]] = {}
        for members in groups.values():
            if len(members) < 2:
                continue
            group = sorted((events[i] for i in members), key=lambda e: (e.date or "9999", e.event.id))
            fused = self._merge_events(group)
            merged[fused.event.id] = [e.event.id for e in group if e.event.id != fused.event.id]
            replace[members[0]] = fused
            replace.update({i: None for i in members[1:]})
        out = [replace.get(i, e) for i, e in enumerate(events)]
        return [e for e in out if e is not None], merged

    @staticmethod
    def _merge_events(group: list[NormalizedEvent]) -> NormalizedEvent:
        """Un seul événement pour le groupe : type majoritaire (pondéré par le nombre d'articles), toutes les sources."""
        votes: Counter = Counter()
        for e in group:
            votes[e.event.type] += len(e.media)
        best_type = max(votes, key=lambda t: (votes[t], max(e.meta.confidence for e in group if e.event.type == t)))
        rep = next(e for e in group if e.event.type == best_type)
        entities: dict[str, EntityRef] = {}
        for e in group:
            for ent in e.entities:
                key = ent.id or norm_key(ent.name)
                rank = {"touché": 2, "exposé": 1, "mentionné": 0}
                if key not in entities or rank[ent.role] > rank[entities[key].role]:
                    entities[key] = ent
        media = {m.source_id: m for e in group for m in e.media}
        dates = [e.date for e in group if e.date]
        others = [e.event.id for e in group[1:]]
        return NormalizedEvent(
            event=EventInfo(id=group[0].event.id, type=best_type, label=rep.event.label),
            date=min(dates) if dates else None,
            location=rep.location if rep.location.name else next((e.location for e in group if e.location.name), rep.location),
            entities=list(entities.values()),
            weather=next((e.weather for e in group if e.weather), None),
            finance=next((e.finance for e in group if e.finance), None),
            media=sorted(media.values(), key=lambda m: (m.date or "9999", m.source_id)),
            donnees_manquantes=[m for m in group[0].donnees_manquantes if all(m in e.donnees_manquantes for e in group)],
            meta=EventMeta(agent="media", confidence=max(e.meta.confidence for e in group), extractor=rep.meta.extractor,
                           detail=(rep.meta.detail + " ; " if rep.meta.detail else "") + "fusion sémantique avec " + ", ".join(others)))

    def _freshness(self, last: Optional[date], as_of: Optional[date]) -> float:
        if last is None or as_of is None or last >= as_of:
            return 1.0
        return 1.0 - 0.5 * min((as_of - last).days, 14) / 14

    def _correlate(self, events: Iterable[NormalizedEvent], as_of: Optional[date]) -> tuple[list[CorrelatedSignal], dict]:
        buckets: dict[tuple[str, str], list[NormalizedEvent]] = defaultdict(list)
        links: dict[str, list[str]] = {}
        weights: dict[tuple[str, str], float] = {}
        for ev in events:
            if ev.event.type == "aucun":
                continue
            for nid, w in self.link_weights(ev).items():
                weights[(ev.event.id, nid)] = w
            links[ev.event.id] = [nid for (eid, nid) in weights if eid == ev.event.id]
            for nid in links[ev.event.id]:
                buckets[(nid, FAMILY[ev.event.type])].append(ev)

        signals: list[CorrelatedSignal] = []
        for (nid, family), evs in sorted(buckets.items()):
            evs.sort(key=lambda e: (e.date or "9999", e.event.id))
            clusters: list[list[NormalizedEvent]] = []
            for ev in evs:
                d, last = _parse_date(ev.date), _parse_date(clusters[-1][-1].date) if clusters else None
                if clusters and (d is None or last is None or (d - last).days <= CORRELATION_WINDOW_DAYS):
                    clusters[-1].append(ev)
                else:
                    clusters.append([ev])
            for k, cluster in enumerate(clusters, start=1):
                # Un lien élargi pèse SOFT_LINK_CONFIDENCE fois moins et ne corrobore pas un lien exact : s'il existe
                # des événements qui citent le nœud, eux seuls comptent pour le nombre de sources et d'agents.
                weighted = lambda e: BASE_SEVERITY[e.event.type] * event_intensity(e) * weights[(e.event.id, nid)]  # noqa: E731
                exact = [e for e in cluster if weights[(e.event.id, nid)] >= 1.0]
                counted = exact or cluster
                agents = sorted({e.meta.agent for e in counted})
                source_ids = list(dict.fromkeys(s for e in counted for s in e.source_ids))
                severity = max(weighted(e) for e in cluster)
                confidence = _clip(0.55 + 0.10 * min(len(source_ids) - 1, 2) + 0.25 * (len(agents) - 1))
                dates = [e.date for e in cluster if e.date]
                fresh = self._freshness(_parse_date(max(dates)) if dates else None, as_of)
                top = max(cluster, key=weighted)
                signals.append(CorrelatedSignal(
                    id=f"sig:{nid}:{family}:{k}", node_id=nid, family=family,
                    types=sorted({e.event.type for e in cluster}), agents=agents,
                    event_ids=[e.event.id for e in cluster], source_ids=source_ids,
                    first_date=min(dates) if dates else None, last_date=max(dates) if dates else None,
                    severity=round(severity, 3), confidence=round(confidence, 3),
                    contribution=round(_clip(severity * confidence * fresh), 3),
                    corroborated=len(agents) >= 2, link="exact" if exact else "elargi", label=top.event.label))
        return signals, links

    # ------------------------------------------------------------------ propagation
    def _transmission(self, node: GraphNode) -> float:
        return DECAY * (1.0 - min(node.stock_days, 60.0) / 120.0)

    def propagate(self, direct: dict[str, float]) -> dict[str, dict]:
        """Calcul pur : risque direct par nœud -> risque total, part propagée et chemin dominant."""
        out: dict[str, dict] = {}
        for nid in self._order:
            d = _clip(direct.get(nid, 0.0))
            losses: dict[str, float] = defaultdict(float)
            best: dict[str, tuple[float, str]] = {}
            for pred in self.active.predecessors(nid):
                e: GraphEdge = self.active[pred][nid]["edge"]
                part = e.dependency * out[pred]["risk"]
                losses[e.input] += part
                if part > best.get(e.input, (0.0, ""))[0]:
                    best[e.input] = (part, pred)
            propagated, path = 0.0, [nid]
            if losses:
                worst = max(losses, key=losses.get)
                propagated = _clip(self._transmission(self.nodes[nid]) * losses[worst])
                if propagated > d and worst in best:
                    path = out[best[worst][1]]["path"] + [nid]
            risk = 1.0 - (1.0 - d) * (1.0 - propagated)
            out[nid] = {"direct": round(d, 4), "propagated": round(propagated, 4), "risk": round(risk, 4), "path": path}
        return out

    def global_index(self, risks: dict[str, dict]) -> float:
        """Indice global sur 100 : moyenne des risques pondérée par la criticité (produits x3, usines x2)."""
        weights = {nid: n.criticality * TYPE_WEIGHT.get(n.type, 1.0) for nid, n in self.nodes.items()}
        total = sum(weights.values()) or 1.0
        return round(100 * sum(weights[n] * risks[n]["risk"] for n in self.nodes) / total, 1)

    def evaluate(self, events: Iterable[NormalizedEvent], as_of: Optional[str], dedupe: bool = True) -> Evaluation:
        """Calcul complet, sans modifier l'état du moteur. `dedupe=False` saute la déduplication sémantique."""
        events, merged = self.semantic_dedupe(events) if dedupe else (list(events), {})
        signals, links = self._correlate(events, _parse_date(as_of))
        survival: dict[str, float] = defaultdict(lambda: 1.0)
        for s in signals:
            survival[s.node_id] *= 1.0 - s.contribution
        direct = {nid: round(1.0 - v, 4) for nid, v in survival.items()}
        risks = self.propagate(direct)
        return Evaluation(as_of=as_of, events=events, merged=merged, signals=signals, links=links, direct=direct, risks=risks,
                          index=self.global_index(risks))

    def ingest(self, events: Iterable[NormalizedEvent], as_of: Optional[str] = None, mode: Optional[str] = None) -> Evaluation:
        """Remplace l'état réel par celui calculé à partir de ces événements."""
        self.mode = mode
        self.current = self.evaluate(events, as_of)
        self.events = self.current.events                 # après déduplication sémantique
        return self.current

    def reset(self) -> None:
        self.ingest([], None, None)

    # ------------------------------------------------------------------ lecture de l'état
    def _node_states(self, risks: dict[str, dict], signals: list[CorrelatedSignal]) -> list[NodeState]:
        by_node: dict[str, list[str]] = defaultdict(list)
        for s in signals:
            by_node[s.node_id].append(s.id)
        return [NodeState(**n.model_dump(), direct=risks[nid]["direct"], propagated=risks[nid]["propagated"],
                          risk=risks[nid]["risk"], level=level_of(risks[nid]["risk"]), path=risks[nid]["path"],
                          signal_ids=by_node.get(nid, [])) for nid, n in self.nodes.items()]

    def state(self) -> GraphState:
        cur = self.current
        return GraphState(as_of=cur.as_of, mode=self.mode, global_risk_index=cur.index,
                          critical_nodes=[n for n in self.nodes if cur.risks[n]["risk"] >= 0.60],
                          nodes=self._node_states(cur.risks, cur.signals), edges=self.edges)

    def names(self, ids: Iterable[str]) -> list[str]:
        return [self.nodes[i].name for i in ids]

    def alerts(self) -> list[Alert]:
        cur, out = self.current, []
        by_node: dict[str, list[CorrelatedSignal]] = defaultdict(list)
        for s in cur.signals:
            by_node[s.node_id].append(s)
        for nid, r in cur.risks.items():
            if r["risk"] < ALERT_THRESHOLD:
                continue
            node = self.nodes[nid]
            sigs = [s for step in r["path"] for s in by_node.get(step, [])]
            own = by_node.get(nid, [])
            if len(r["path"]) > 1:
                origin = self.nodes[r["path"][0]]
                rule = (f"Risque propagé {pct(r['propagated'])} depuis « {origin.name} » "
                        f"le long de {len(r['path']) - 1} lien(s) ; risque direct {pct(r['direct'])}.")
            else:
                parts = [f"{FAMILY_LABELS[s.family]} ({' + '.join(AGENT_LABELS[a] for a in s.agents)}{', corroboré' if s.corroborated else ''})"
                         for s in own]
                rule = f"Risque direct {pct(r['direct'])} : " + (", ".join(parts) or "aucun signal direct") + \
                       (f" ; risque propagé {pct(r['propagated'])}." if r["propagated"] else ".")
            labels = list(dict.fromkeys(s.label for s in sorted(sigs, key=lambda s: -s.contribution)))[:2]
            dates = [s.first_date for s in sigs if s.first_date]
            out.append(Alert(
                id=f"ALR:{nid}", node_id=nid, node_name=node.name, node_type=node.type, level=level_of(r["risk"]),
                risk=r["risk"], direct=r["direct"], propagated=r["propagated"],
                priority=round(r["risk"] * (0.5 + 0.5 * node.criticality), 4), rule=rule,
                path=r["path"], path_names=self.names(r["path"]),
                agents=sorted({a for s in sigs for a in s.agents}), signal_ids=[s.id for s in sigs],
                source_ids=list(dict.fromkeys(i for s in sigs for i in s.source_ids)),
                summary=f"{node.name} : risque {pct(r['risk'])}. " + (" | ".join(labels) if labels else "Aucun signal direct."),
                date=min(dates) if dates else None))
        return sorted(out, key=lambda a: -a.priority)

    def top_exposed(self, n: int = 5, node_type: Optional[str] = None) -> list[NodeState]:
        states = [s for s in self._node_states(self.current.risks, self.current.signals)
                  if node_type is None or s.type == node_type]
        return sorted(states, key=lambda s: -s.risk)[:n]

    def threatened_products(self, threshold: float = 0.15) -> list[NodeState]:
        return [s for s in self.top_exposed(len(self.nodes), "produit_fini") if s.risk >= threshold]

    def downstream_products(self, node_id: str) -> list[str]:
        self._require(node_id)
        return [n for n in nx.descendants(self.active, node_id) if self.nodes[n].type == "produit_fini"]

    def dependency_ranking(self, node_id: str, n: int = 5) -> list[dict]:
        """Nœuds amont dont la panne totale toucherait le plus `node_id` (points de défaillance)."""
        self._require(node_id)
        base = self.current.risks[node_id]["risk"]
        rows = []
        for anc in nx.ancestors(self.active, node_id):
            sim = self.propagate({**self.current.direct, anc: 1.0})
            rows.append({"node_id": anc, "name": self.nodes[anc].name, "type": self.nodes[anc].type,
                         "risk_if_down": sim[node_id]["risk"], "delta": round(sim[node_id]["risk"] - base, 4),
                         "path": self.names(sim[node_id]["path"])})
        return sorted(rows, key=lambda r: -r["risk_if_down"])[:n]

    # ------------------------------------------------------------------ what-if et mitigation
    def _require(self, node_id: str) -> GraphNode:
        if node_id not in self.nodes:
            raise KeyError(f"nœud inconnu : {node_id}")
        return self.nodes[node_id]

    def simulate_disruption(self, node_id: str, severity: float) -> SimulationResult:
        """Teste une panne hypothétique. L'état réel (`self.current`, `self.events`) n'est jamais modifié."""
        node = self._require(node_id)
        if not 0.0 <= severity <= 1.0:
            raise ValueError("severity doit être comprise entre 0 et 1")
        base = self.current.risks
        direct = dict(self.current.direct)                       # copie : on ne touche pas à l'état réel
        direct[node_id] = max(direct.get(node_id, 0.0), severity)
        sim = self.propagate(direct)
        impacts = [NodeImpact(node_id=n, name=self.nodes[n].name, type=self.nodes[n].type, baseline=base[n]["risk"],
                              simulated=sim[n]["risk"], delta=round(sim[n]["risk"] - base[n]["risk"], 4),
                              level=level_of(sim[n]["risk"]), path=sim[n]["path"])
                   for n in self.nodes if sim[n]["risk"] - base[n]["risk"] > 0.005]
        impacts.sort(key=lambda i: -i.delta)
        products = [i for i in impacts if i.type == "produit_fini" and i.simulated >= 0.15]
        return SimulationResult(node_id=node_id, node_name=node.name, severity=severity,
                                baseline_index=self.current.index, simulated_index=self.global_index(sim),
                                impacts=impacts, threatened_products=products,
                                nodes=self._node_states(sim, self.current.signals),
                                mitigation=self.mitigation_plan(node_id))

    def alternative_suppliers(self, node_id: str, depth: int = 3) -> list[dict]:
        """Pour chaque client aval (jusqu'à `depth` liens), les autres sources du même intrant.

        Une source n'est proposée que si elle ne dépend pas elle-même du nœud en panne.
        """
        self._require(node_id)
        tainted = {node_id} | nx.descendants(self.graph, node_id)       # tout ce qui dépend du nœud, secours compris
        frontier, seen, out = [(node_id, 0)], {node_id}, []
        while frontier:
            current, d = frontier.pop(0)
            for customer in self.active.successors(current):
                edge: GraphEdge = self.active[current][customer]["edge"]
                alts = []
                for pred in self.graph.predecessors(customer):
                    e: GraphEdge = self.graph[pred][customer]["edge"]
                    if pred == current or e.input != edge.input or pred in tainted:
                        continue
                    spare = e.capacity if e.backup else max(0.0, e.capacity - e.dependency)
                    alts.append({"node_id": pred, "name": self.nodes[pred].name, "kind": "secours" if e.backup else "actif",
                                 "current_share": e.dependency, "spare_capacity": round(spare, 3),
                                 "lead_time_days": e.lead_time_days, "risk": self.current.risks[pred]["risk"]})
                alts.sort(key=lambda a: (a["risk"], -a["spare_capacity"]))
                recover = min(edge.dependency, sum(a["spare_capacity"] for a in alts))
                out.append({"customer_id": customer, "customer": self.nodes[customer].name, "via": self.nodes[current].name,
                            "input": edge.input, "depth": d, "share_at_risk": edge.dependency,
                            "coverage": round(recover / edge.dependency, 3) if edge.dependency else 0.0,
                            "alternatives": alts})
                if customer not in seen and d + 1 < depth:
                    seen.add(customer)
                    frontier.append((customer, d + 1))
        return out

    def mitigation_plan(self, node_id: str) -> MitigationPlan:
        node = self._require(node_id)
        actions: list[MitigationAction] = []
        coverage: dict[str, float] = {}
        for row in self.alternative_suppliers(node_id):
            if row["depth"] == 0 or row["alternatives"]:         # clients directs, et clients plus loin s'ils ont une alternative
                coverage[f"{row['customer']} / {row['input']}"] = row["coverage"]
            for alt in row["alternatives"]:
                if alt["spare_capacity"] <= 0:
                    continue
                if alt["kind"] == "secours":
                    actions.append(MitigationAction(
                        kind="route_secours", target=alt["name"],
                        description=(f"Activer le secours « {alt['name']} » pour {row['customer']} ({row['input']}) : "
                                     f"jusqu'à {pct(alt['spare_capacity'])} du besoin, délai {alt['lead_time_days']:.0f} j."),
                        capacity=alt["spare_capacity"], lead_time_days=alt["lead_time_days"]))
                else:
                    actions.append(MitigationAction(
                        kind="reallocation", target=alt["name"],
                        description=(f"Augmenter la part de « {alt['name']} » pour {row['customer']} ({row['input']}) : "
                                     f"+{pct(alt['spare_capacity'])} disponibles (part actuelle {pct(alt['current_share'])}), "
                                     f"délai {alt['lead_time_days']:.0f} j."),
                        capacity=alt["spare_capacity"], lead_time_days=alt["lead_time_days"]))
        downstream = nx.descendants(self.active, node_id)
        for nid in downstream:
            n = self.nodes[nid]
            if n.type == "usine" and n.stock_days > 0:
                actions.append(MitigationAction(
                    kind="stock", target=n.name,
                    description=f"{n.name} : {n.stock_days:.0f} j de stock. Geler les sorties non prioritaires et réserver le stock aux produits les plus critiques."))
        actions.append(MitigationAction(
            kind="surveillance", target=node.name,
            description=f"Suivre « {node.name} » chaque jour (médias, météo, marché) et relancer la simulation à chaque nouveau signal."))
        order = {"reallocation": 0, "route_secours": 1, "stock": 2, "surveillance": 3}
        actions.sort(key=lambda a: (order[a.kind], a.lead_time_days or 0))
        products = [self.nodes[p].name for p in downstream if self.nodes[p].type == "produit_fini"]
        return MitigationPlan(node_id=node_id, node_name=node.name, actions=actions, coverage=coverage,
                              threatened_products=sorted(products))

    # ------------------------------------------------------------------ résolution d'un nom en langage naturel
    def resolve_node(self, text: str) -> Optional[str]:
        """Trouve le nœud cité dans une phrase : alias le plus long d'abord, puis tolérance aux fautes de frappe."""
        t = norm_key(text)
        for alias in sorted(self._alias_index, key=len, reverse=True):
            if len(alias) >= 4 and contains_term(t, alias):
                return self._alias_index[alias]
        singles = [a for a in self._alias_index if " " not in a and len(a) >= 5]
        for word in t.replace("'", " ").split():
            if len(word) >= 5:
                hit = difflib.get_close_matches(word, singles, n=1, cutoff=0.85)
                if hit:
                    return self._alias_index[hit[0]]
        return None
