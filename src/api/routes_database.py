"""Explorateur de la base unifiée (data/aegis.duckdb) et du graphe unifié, en LECTURE SEULE.

    GET /database/summary               volumétrie de chaque domaine (médias, météo, finance, base unifiée)
    GET /database/tables                tables explorables et leurs filtres
    GET /database/tables/{name}         lignes paginées (LIMIT/OFFSET), recherche, filtres ; ?format=csv pour l'export
    GET /database/unified-graph         nœuds de la chaîne active + événements de la dernière exécution qui les touchent

Les requêtes sont construites à partir d'un catalogue fermé (aucun SQL fourni par le client) et paramétrées.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.api.routes_data import _rows
from src.config import settings
from src.graph.ontology_engine import BASE_SEVERITY, FAMILY, event_intensity
from src.schemas.events import NormalizedEvent
from src.storage import db

router = APIRouter(prefix="/database", tags=["base de données"])
CSV_MAX_ROWS = 200_000

# Dernière exécution de chaque topologie : sert au score de risque des nœuds
LATEST = """(SELECT topology, run_id FROM runs QUALIFY row_number() OVER (PARTITION BY topology ORDER BY started_at DESC) = 1)"""


@dataclass
class TableSpec:
    label: str
    domain: str                         # media, weather, finance, unified
    sql: str                            # SELECT de base, enveloppé en sous-requête
    date_col: Optional[str]
    search: list[str]                   # colonnes de la recherche texte
    filters: dict[str, str] = field(default_factory=dict)   # paramètre -> colonne (égalité)
    alert_col: Optional[str] = None
    rank_col: Optional[str] = None
    order: str = ""
    requires: tuple[str, ...] = ()
    description: str = ""


TABLES: dict[str, TableSpec] = {
    "media": TableSpec(
        "Médias : événements extraits", "media",
        f"""SELECT e.date_first AS date,
                   CASE WHEN e.source_ids[1] LIKE 'gdelt%' THEN 'GDELT' WHEN e.source_ids[1] LIKE 'gnews%' OR e.source_ids[1] LIKE 'google%' THEN 'Google News'
                        WHEN e.source_ids[1] LIKE 'replay%' THEN 'Scénario' ELSE 'RSS' END AS source,
                   e.label AS titre, e.type, e.family AS famille,
                   json_array_length(e.payload->'media') AS articles,
                   array_to_string(json_extract_string(e.payload, '$.entities[*].name'), ', ') AS entites,
                   e.confidence AS confiance,
                   (SELECT string_agg(l.node_id, ', ') FROM event_links l WHERE l.event_id=e.event_id AND l.topology=e.topology) AS noeuds,
                   e.topology, e.mode, e.event_id, e.last_seen AS vu_le
            FROM events e WHERE e.agent='media'""",
        "date", ["titre", "entites", "noeuds"], {"family": "famille", "type": "type", "topology": "topology"},
        rank_col="confiance", order="date DESC NULLS LAST, vu_le DESC",
        description="Un événement par incident (articles fusionnés), avec ses entités et les nœuds rattachés."),
    "weather_indicators": TableSpec(
        "Météo : indicateurs quotidiens", "weather",
        """SELECT i.date, i.series AS site_id, s.name AS site, s.country AS pays, i.indicator AS indicateur,
                  i.value AS valeur, t.unit AS unite, i.threshold AS seuil, i.rank AS rang, i.alert AS alerte
           FROM indicators i LEFT JOIN wx_sites s ON s.site=i.series
           LEFT JOIN thresholds t ON t.agent='weather' AND t.series=i.series AND t.indicator=i.indicator
           WHERE i.agent='weather' AND i.indicator <> '_score'""",
        "date", ["site", "site_id", "indicateur"], {"site": "site_id", "indicator": "indicateur"},
        alert_col="alerte", rank_col="rang", order="date DESC, site_id, indicateur",
        description="Pluie 3 j / 90 j, rafales, neige, chaleur, gel, crue, basses eaux par site et par jour, avec le seuil calibré."),
    "weather_forecast": TableSpec(
        "Météo : prévisions 16 jours", "weather",
        """SELECT f.date, f.run_date AS emise_le, f.site AS site_id, s.name AS site, f.indicator AS indicateur,
                  f.value AS valeur, f.unit AS unite, f.threshold AS seuil, f.rank AS rang, f.alert AS alerte,
                  f.score AS score_site, f.risk AS risque
           FROM wx_forecast f LEFT JOIN wx_sites s ON s.site=f.site""",
        "date", ["site", "site_id", "indicateur", "risque"], {"site": "site_id", "indicator": "indicateur"},
        alert_col="alerte", rank_col="rang", order="emise_le DESC, date, site_id",
        description="Indicateurs prévus jour par jour, comparés au seuil du site."),
    "weather_sites": TableSpec(
        "Météo : sites calibrés", "weather",
        """SELECT s.site AS site_id, s.name AS site, s.country AS pays, s.lat, s.lon, s.role, s.fluvial,
                  array_to_string(s.indicators, ', ') AS indicateurs, s.debit_median, s.climat, s.origin AS origine,
                  s.topology, s.node_id AS noeud, s.updated_at AS maj
           FROM wx_sites s""",
        None, ["site", "site_id", "pays", "role"], {"site": "site_id"}, order="site_id",
        description="Sites suivis, indicateurs pertinents, point du fleuve, origine (notebook ou calibration)."),
    "finance_series": TableSpec(
        "Finance : séries de marché et bourse", "finance",
        """SELECT r.date, c.famille, r.signal AS symbole, c.nom, r.valeur, c.unite, i.value AS indicateur,
                  c.mesure, i.threshold AS seuil, i.rank AS rang, i.alert AS alerte, c.source
           FROM fin_raw r LEFT JOIN fin_signals c ON c.signal=r.signal
           LEFT JOIN indicators i ON i.agent='finance' AND i.series=r.signal AND i.indicator='indicateur' AND i.date=r.date""",
        "date", ["symbole", "nom", "famille"], {"symbol": "symbole", "family": "famille"},
        alert_col="alerte", rank_col="rang", order="date DESC, symbole",
        description="Valeurs publiées (Brent, gaz, gazole, GSCPI, change, métaux, prix de production, cours des fournisseurs)."),
    "finance_suppliers": TableSpec(
        "Finance : fiches fournisseurs", "finance",
        """SELECT cle, nom, pays, en_alerte AS alerte,
                  json_extract_string(payload, '$.produit') AS produit,
                  TRY_CAST(json_extract(payload, '$.bourse."variation_20j_%"') AS DOUBLE) AS bourse_20j_pct,
                  array_to_string(json_extract_string(payload, '$.proprietaires[*].nom'), ', ') AS maisons_meres,
                  json_array_length(payload->'sanctions') AS sanctions,
                  json_array_length(payload->'procedures_collectives') AS procedures,
                  array_to_string(json_extract_string(payload, '$.alertes[*]'), ' ; ') AS alertes,
                  updated_at AS maj
           FROM fin_suppliers""",
        None, ["nom", "cle", "pays", "maisons_meres", "alertes"], {"symbol": "cle"}, alert_col="alerte", order="alerte DESC, nom",
        description="Bourse, maisons mères (GLEIF), correspondances sur les listes de sanctions, BODACC."),
    "finance_rules": TableSpec(
        "Finance : règles et taxes (US, UE)", "finance",
        """SELECT publication AS date, entree_en_vigueur, zone, famille, titre, delai_jours, url, id FROM fin_rules""",
        "date", ["titre", "famille"], {"zone": "zone", "family": "famille"}, order="date DESC",
        description="Federal Register (Entity List, droits de douane) et règles UE suivies à la main."),
    "finance_sanctions": TableSpec(
        "Finance : listes de sanctions UE et US", "finance",
        """SELECT date_inscription AS date, liste, nom, autres_noms, programme, source_id FROM fin_sanctions""",
        "date", ["nom", "autres_noms", "programme", "liste"], {}, order="date DESC NULLS LAST, nom",
        requires=("fin_sanctions",),
        description="Entités (hors personnes) de la Consolidated Screening List américaine et de la liste consolidée de l'UE."),
    "unified": TableSpec(
        "Base unifiée : événements corrélés au graphe", "unified",
        f"""SELECT e.event_id, e.agent AS domaine, e.family AS famille, e.type, l.node_id AS noeud_cible, l.link AS lien,
                   l.weight AS poids, e.confidence AS confiance, nr.risk AS score_risque, nr.level AS niveau,
                   e.date_first AS date, e.last_seen AS vu_le, e.label, e.topology, e.mode, e.payload
            FROM events e JOIN event_links l ON l.event_id=e.event_id AND l.topology=e.topology
            LEFT JOIN {LATEST} lr ON lr.topology=e.topology
            LEFT JOIN node_risk_history nr ON nr.run_id=lr.run_id AND nr.node_id=l.node_id""",
        "date", ["event_id", "noeud_cible", "label"], {"agent": "domaine", "family": "famille", "topology": "topology", "site": "noeud_cible"},
        rank_col="score_risque", order="date DESC NULLS LAST, vu_le DESC",
        description="Signaux normalisés des trois agents rattachés aux nœuds ; score = risque du nœud à la dernière exécution."),
}


def _where(spec: TableSpec, p: dict) -> tuple[str, list]:
    clauses, params = [], []
    if p.get("q"):
        clauses.append("(" + " OR ".join(f"CAST({c} AS VARCHAR) ILIKE ?" for c in spec.search) + ")")
        params += [f"%{p['q']}%"] * len(spec.search)
    if spec.date_col and p.get("date_from"):
        clauses.append(f"{spec.date_col} >= ?")
        params.append(p["date_from"])
    if spec.date_col and p.get("date_to"):
        clauses.append(f"{spec.date_col} <= ?")
        params.append(p["date_to"])
    for key, col in spec.filters.items():
        if p.get(key):
            clauses.append(f"{col} = ?")
            params.append(p[key])
    if p.get("alert") and spec.alert_col:
        clauses.append(f"{spec.alert_col}")
    if p.get("min_rank") is not None and spec.rank_col:
        clauses.append(f"{spec.rank_col} >= ?")
        params.append(p["min_rank"])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _guard(spec: TableSpec) -> None:
    if not settings.db_path.exists():
        raise HTTPException(503, "base absente : python -m src.jobs import-notebooks")
    missing = [t for t in spec.requires if t not in db.table_names()]
    if missing:
        raise HTTPException(404, f"table absente de la base : {', '.join(missing)} (python -m src.jobs ingest-finance)")


def _unified_extras(df: pd.DataFrame) -> pd.DataFrame:
    """Intensité de chaque événement, calculée par le moteur à partir du bloc météo / finance (1 pour un article)."""
    if "payload" not in df:
        return df
    vals = []
    for raw in df["payload"]:
        try:
            ev = NormalizedEvent.model_validate(json.loads(raw) if isinstance(raw, str) else raw)
            vals.append(round(BASE_SEVERITY.get(ev.event.type, 0.5) * event_intensity(ev), 3))
        except Exception:
            vals.append(None)
    df = df.drop(columns=["payload"])
    df.insert(df.columns.get_loc("confiance"), "intensite", vals)
    return df


@router.get("/summary")
def summary() -> dict:
    """Compteurs réels de la base, par domaine."""
    if not settings.db_path.exists():
        return {"ready": False, "db": str(settings.db_path), "domains": {}}
    names = db.table_names()
    q = lambda sql: int(db.query_ro(sql)["n"].iloc[0])  # noqa: E731
    def safe(sql: str, table: str) -> int:
        return q(sql) if table in names else 0
    domains = {
        "media": {"evenements": safe("SELECT count(*) n FROM events WHERE agent='media'", "events"),
                  "articles": safe("SELECT coalesce(sum(json_array_length(payload->'media')), 0) n FROM events WHERE agent='media'", "events")},
        "weather": {"indicateurs": safe("SELECT count(*) n FROM indicators WHERE agent='weather'", "indicators"),
                    "sites": safe("SELECT count(*) n FROM wx_sites", "wx_sites"),
                    "seuils": safe("SELECT count(*) n FROM thresholds WHERE agent='weather' AND indicator<>'_score'", "thresholds"),
                    "previsions": safe("SELECT count(*) n FROM wx_forecast", "wx_forecast"),
                    "jours_en_alerte": safe("SELECT count(*) n FROM indicators WHERE agent='weather' AND indicator<>'_score' AND alert", "indicators")},
        "finance": {"valeurs": safe("SELECT count(*) n FROM fin_raw", "fin_raw"),
                    "signaux": safe("SELECT count(DISTINCT signal) n FROM fin_raw", "fin_raw"),
                    "fournisseurs": safe("SELECT count(*) n FROM fin_suppliers", "fin_suppliers"),
                    "sanctions": safe("SELECT count(*) n FROM fin_sanctions", "fin_sanctions"),
                    "regles": safe("SELECT count(*) n FROM fin_rules", "fin_rules")},
        "unified": {"evenements": safe("SELECT count(*) n FROM events", "events"),
                    "liens": safe("SELECT count(*) n FROM event_links", "event_links"),
                    "liaisons_referentiel": safe("SELECT count(*) n FROM entity_bindings", "entity_bindings"),
                    "executions": safe("SELECT count(*) n FROM runs", "runs"),
                    "historique_noeuds": safe("SELECT count(*) n FROM node_risk_history", "node_risk_history")},
    }
    by_agent = db.query_ro("SELECT agent, count(*) n FROM events GROUP BY 1") if "events" in names else pd.DataFrame()
    domains["unified"]["par_agent"] = {r.agent: int(r.n) for r in by_agent.itertuples()}
    total = int(db.query_ro(" + ".join(f"(SELECT count(*) FROM {t})" for t in sorted(names)).join(["SELECT ", " AS n"]))["n"].iloc[0]) if names else 0
    return {"ready": True, "db": str(settings.db_path), "size_mb": round(settings.db_path.stat().st_size / 1e6, 1),
            "tables": len(names), "rows_total": total, "domains": domains}


@router.get("/tables")
def tables() -> list[dict]:
    names = db.table_names()
    return [{"name": k, "label": s.label, "domain": s.domain, "description": s.description, "has_date": bool(s.date_col),
             "filters": list(s.filters), "alert": bool(s.alert_col), "rank": s.rank_col,
             "available": all(t in names for t in s.requires)} for k, s in TABLES.items()]


@router.get("/tables/{name}")
def table(name: str, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
          q: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
          site: Optional[str] = None, symbol: Optional[str] = None, indicator: Optional[str] = None,
          family: Optional[str] = None, agent: Optional[str] = None, zone: Optional[str] = None,
          type: Optional[str] = None, topology: Optional[str] = None, alert: bool = False,
          min_rank: Optional[float] = Query(None, ge=0, le=1), format: str = Query("json", pattern="^(json|csv)$")):
    spec = TABLES.get(name)
    if spec is None:
        raise HTTPException(404, f"table inconnue : {name} (voir /database/tables)")
    _guard(spec)
    where, params = _where(spec, {"q": q, "date_from": date_from, "date_to": date_to, "site": site, "symbol": symbol,
                                  "indicator": indicator, "family": family, "agent": agent, "zone": zone, "type": type,
                                  "topology": topology, "alert": alert, "min_rank": min_rank})
    base = f"FROM ({spec.sql}) t{where}"
    order = f" ORDER BY {spec.order}" if spec.order else ""
    if format == "csv":
        df = _unified_extras(db.query_ro(f"SELECT * {base}{order} LIMIT {CSV_MAX_ROWS}", params))
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="aegis_{name}.csv"'})
    total = int(db.query_ro(f"SELECT count(*) AS n {base}", params)["n"].iloc[0])
    df = _unified_extras(db.query_ro(f"SELECT * {base}{order} LIMIT ? OFFSET ?", params + [limit, offset]))
    return {"name": name, "label": spec.label, "total": total, "limit": limit, "offset": offset,
            "columns": list(df.columns), "rows": _rows(df)}


@router.get("/tables/{name}/values")
def distinct_values(name: str, column: str) -> list[str]:
    """Valeurs possibles d'un filtre (sites, symboles, familles...) pour les menus déroulants."""
    spec = TABLES.get(name)
    if spec is None or column not in spec.filters:
        raise HTTPException(404, "filtre inconnu")
    _guard(spec)
    col = spec.filters[column]
    df = db.query_ro(f"SELECT DISTINCT {col} AS v FROM ({spec.sql}) t WHERE {col} IS NOT NULL ORDER BY 1 LIMIT 500")
    return [str(v) for v in df["v"]] if len(df) else []


@router.get("/unified-graph")
def unified_graph(request: Request, limit: int = Query(250, ge=1, le=2000)) -> dict:
    """Graphe unifié : nœuds et liens de la chaîne active, et événements de la dernière exécution qui les touchent."""
    svc = request.app.state.service
    eng = svc.engine
    topo = svc.topology_key()
    state = eng.state()
    nodes = [{"id": n.id, "name": n.name, "type": n.type, "tier": n.tier, "country": n.country, "place": n.place,
              "criticality": n.criticality, "stock_days": n.stock_days, "risk": n.risk, "direct": n.direct,
              "propagated": n.propagated, "level": n.level, "signal_ids": n.signal_ids,
              "families": sorted({s.split(":")[2] for s in n.signal_ids if s.count(":") >= 2})} for n in state.nodes]
    edges = [e.model_dump() for e in state.edges]
    events, run = [], None
    if settings.db_path.exists() and {"events", "runs"} <= db.table_names():
        r = db.query_ro("SELECT run_id, as_of, mode, scenario, started_at FROM runs WHERE topology=? ORDER BY started_at DESC LIMIT 1", [topo])
        if len(r):
            run = _rows(r)[0]
            df = db.query_ro("""SELECT e.event_id, e.agent, e.type, e.family, e.date_first, e.label, e.confidence, e.payload,
                                       e.source_ids, list(struct_pack(node_id := l.node_id, weight := l.weight, link := l.link)) AS links
                                FROM events e JOIN event_links l ON l.event_id=e.event_id AND l.topology=e.topology
                                WHERE e.topology=? AND e.last_run=?
                                GROUP BY ALL ORDER BY e.date_first DESC NULLS LAST LIMIT ?""", [topo, run["run_id"], limit])
            df = _unified_extras(df.rename(columns={"confidence": "confiance"}))
            if eng.current.as_of is None:              # API redémarrée : risques de la dernière exécution enregistrée
                hist = {r["node_id"]: r for r in _rows(db.query_ro(
                    "SELECT node_id, direct, propagated, risk, level, families FROM node_risk_history WHERE run_id=?", [run["run_id"]]))}
                for n in nodes:
                    h = hist.get(n["id"])
                    if h:
                        n.update(risk=h["risk"], direct=h["direct"], propagated=h["propagated"], level=h["level"],
                                 families=h["families"] or [])
                run["from_history"] = True
            for row in _rows(df):
                events.append({"id": row["event_id"], "agent": row["agent"], "type": row["type"],
                               "family": row["family"] or FAMILY.get(row["type"]), "date": row["date_first"],
                               "label": row["label"], "confidence": row["confiance"], "intensity": row["intensite"],
                               "sources": row["source_ids"] or [],
                               "links": [{"node_id": x["node_id"], "weight": x["weight"], "link": x["link"]} for x in (row["links"] or [])]})
    return {"topology": topo, "topology_name": eng.meta.get("company") or eng.meta.get("name", ""), "run": run,
            "nodes": nodes, "edges": edges, "events": events}
