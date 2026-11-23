"""Base unifiée DuckDB : schéma en trois couches et accès.

    brute       observations        (série, variable, date de validité, date de connaissance)
    calculée    thresholds, indicators, wx_forecast, wx_sites, fin_* (seuils calibrés, rangs, alertes jour par jour)
    signaux     events, event_links (événements normalisés des 3 agents, rattachés aux nœuds du graphe)
    historique  runs, node_risk_history, alerts_history (chaque exécution du pipeline)
    référentiel entity_bindings (nœud du graphe <-> site météo, signal de marché, fournisseur réel), sources

Double date (`valid_date` / `known_at`) : la date du phénomène et la date où on l'a su (émission d'une prévision,
publication d'un chiffre mensuel). C'est ce qui permet un replay honnête : « ce qu'on savait le jour J ».

DuckDB n'accepte qu'un écrivain à la fois par fichier : chaque opération ouvre une connexion courte, sous verrou,
et réessaie quelques fois si un autre processus (job en ligne de commande) tient le fichier.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import pandas as pd

from src.config import settings

log = logging.getLogger("supplychain.storage")
_LOCK = threading.RLock()
_INITIALISED: set[str] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR PRIMARY KEY, agent VARCHAR, provider VARCHAR, status VARCHAR, detail VARCHAR,
    checked_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS observations (
    agent VARCHAR, series VARCHAR, variable VARCHAR, valid_date DATE, known_at DATE, value DOUBLE, unit VARCHAR,
    source_ref VARCHAR, fetched_at TIMESTAMP, PRIMARY KEY (series, variable, valid_date, known_at));
CREATE TABLE IF NOT EXISTS thresholds (
    agent VARCHAR, series VARCHAR, indicator VARCHAR, sens VARCHAR, q DOUBLE, seuil DOUBLE, grid DOUBLE[], n INTEGER,
    period VARCHAR, unit VARCHAR, calibrated_at TIMESTAMP, PRIMARY KEY (agent, series, indicator));
CREATE TABLE IF NOT EXISTS indicators (
    agent VARCHAR, series VARCHAR, indicator VARCHAR, date DATE, value DOUBLE, threshold DOUBLE, rank DOUBLE,
    alert BOOLEAN, PRIMARY KEY (agent, series, indicator, date));
CREATE TABLE IF NOT EXISTS wx_sites (
    site VARCHAR PRIMARY KEY, name VARCHAR, country VARCHAR, lat DOUBLE, lon DOUBLE, role VARCHAR, fluvial BOOLEAN,
    indicators VARCHAR[], lat_debit DOUBLE, lon_debit DOUBLE, debit_median DOUBLE, climat VARCHAR,
    origin VARCHAR, topology VARCHAR, node_id VARCHAR, updated_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS wx_forecast (
    site VARCHAR, run_date DATE, date DATE, indicator VARCHAR, value DOUBLE, threshold DOUBLE, rank DOUBLE,
    alert BOOLEAN, unit VARCHAR, risk VARCHAR, score DOUBLE, PRIMARY KEY (site, run_date, date, indicator));
CREATE TABLE IF NOT EXISTS validation (
    agent VARCHAR, cas VARCHAR, cible VARCHAR, indicator VARCHAR, detected BOOLEAN, lead_days DOUBLE, payload JSON,
    PRIMARY KEY (agent, cas, cible, indicator));
CREATE TABLE IF NOT EXISTS noise (
    agent VARCHAR, series VARCHAR, indicator VARCHAR, episodes_per_year DOUBLE, PRIMARY KEY (agent, series, indicator));
CREATE TABLE IF NOT EXISTS fin_signals (
    signal VARCHAR PRIMARY KEY, nom VARCHAR, famille VARCHAR, source VARCHAR, freq VARCHAR, sens VARCHAR,
    horizon INTEGER, mesure VARCHAR, q DOUBLE, unite VARCHAR, impact VARCHAR);
CREATE TABLE IF NOT EXISTS fin_raw (
    signal VARCHAR, date DATE, valeur DOUBLE, PRIMARY KEY (signal, date));
CREATE TABLE IF NOT EXISTS fin_suppliers (
    cle VARCHAR PRIMARY KEY, nom VARCHAR, pays VARCHAR, en_alerte BOOLEAN, payload JSON, updated_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS fin_rules (
    id VARCHAR PRIMARY KEY, zone VARCHAR, famille VARCHAR, publication DATE, entree_en_vigueur DATE, titre VARCHAR,
    effet VARCHAR, url VARCHAR, delai_jours DOUBLE);
CREATE TABLE IF NOT EXISTS fin_sanctions (
    source_id VARCHAR PRIMARY KEY, liste VARCHAR, nom VARCHAR, autres_noms VARCHAR, programme VARCHAR,
    date_inscription DATE, updated_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS fin_diesel (
    pays VARCHAR, date DATE, valeur DOUBLE, PRIMARY KEY (pays, date));
CREATE TABLE IF NOT EXISTS fin_transmission (
    pays VARCHAR PRIMARY KEY, decalage_semaines DOUBLE, correlation DOUBLE);
CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR, topology VARCHAR, agent VARCHAR, type VARCHAR, family VARCHAR, date_first DATE, label VARCHAR,
    confidence DOUBLE, payload JSON, source_ids VARCHAR[], first_seen TIMESTAMP, last_seen TIMESTAMP,
    last_run VARCHAR, mode VARCHAR, PRIMARY KEY (event_id, topology, mode));
CREATE TABLE IF NOT EXISTS event_links (
    event_id VARCHAR, topology VARCHAR, node_id VARCHAR, link VARCHAR, weight DOUBLE,
    PRIMARY KEY (event_id, topology, node_id));
CREATE TABLE IF NOT EXISTS entity_bindings (
    topology VARCHAR, node_id VARCHAR, kind VARCHAR, ext_id VARCHAR, meta JSON,
    PRIMARY KEY (topology, node_id, kind, ext_id));
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY, started_at TIMESTAMP, mode VARCHAR, scenario VARCHAR, topology VARCHAR,
    topology_name VARCHAR, as_of DATE, status VARCHAR, global_risk_index DOUBLE, n_events INTEGER,
    n_signals INTEGER, n_alerts INTEGER, agents JSON, message VARCHAR);
CREATE TABLE IF NOT EXISTS node_risk_history (
    run_id VARCHAR, as_of DATE, topology VARCHAR, node_id VARCHAR, name VARCHAR, type VARCHAR, direct DOUBLE,
    propagated DOUBLE, risk DOUBLE, level VARCHAR, families VARCHAR[], PRIMARY KEY (run_id, node_id));
CREATE TABLE IF NOT EXISTS alerts_history (
    run_id VARCHAR, alert_id VARCHAR, node_id VARCHAR, level VARCHAR, risk DOUBLE, priority DOUBLE,
    agents VARCHAR[], summary VARCHAR, PRIMARY KEY (run_id, alert_id));
"""


class StorageUnavailable(RuntimeError):
    pass


def _jsonable(x: Any) -> Any:
    if isinstance(x, (datetime, date, pd.Timestamp)):
        return x.isoformat()
    return str(x)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=_jsonable)


@contextmanager
def connect(path: Optional[Path] = None, read_only: bool = False) -> Iterator[Any]:
    try:
        import duckdb
    except ImportError as e:
        raise StorageUnavailable("duckdb n'est pas installé (pip install duckdb)") from e
    path = Path(path or settings.db_path)
    if read_only and not path.exists():
        raise StorageUnavailable(f"base absente : {path} (lancer python -m src.jobs import-notebooks)")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        con, last = None, None
        for attempt in range(6):
            try:
                con = duckdb.connect(str(path), read_only=read_only)
                break
            except duckdb.IOException as e:            # fichier tenu par un autre processus
                last = e
                time.sleep(0.5 * (attempt + 1))
        if con is None:
            raise StorageUnavailable(f"base verrouillée par un autre processus : {last}")
        try:
            key = str(path.resolve())
            if not read_only and key not in _INITIALISED:
                con.execute(SCHEMA)
                _INITIALISED.add(key)
            yield con
        finally:
            con.close()


def ensure_schema() -> Path:
    with connect() as con:
        con.execute(SCHEMA)
    return settings.db_path


def upsert(table: str, df: pd.DataFrame, con=None) -> int:
    """INSERT OR REPLACE des lignes de `df` (colonnes = colonnes de la table, dans n'importe quel ordre)."""
    if df is None or df.empty:
        return 0
    def run(c):
        c.register("_upsert_df", df)
        cols = ", ".join(f'"{x}"' for x in df.columns)
        c.execute(f'INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _upsert_df')
        c.unregister("_upsert_df")
        return len(df)
    if con is not None:
        return run(con)
    with connect() as c:
        return run(c)


def query(sql: str, params: Optional[list] = None) -> pd.DataFrame:
    """Lecture ; base absente -> DataFrame vide (l'API répond « pas encore de données », sans erreur 500)."""
    if not settings.db_path.exists():
        return pd.DataFrame()
    with connect() as con:
        return con.execute(sql, params or []).df()


def query_ro(sql: str, params: Optional[list] = None) -> pd.DataFrame:
    """Lecture seule (explorateur de la base) : aucune écriture possible, même par erreur de requête."""
    if not settings.db_path.exists():
        return pd.DataFrame()
    with connect(read_only=True) as con:
        return con.execute(sql, params or []).df()


def table_names() -> set[str]:
    if not settings.db_path.exists():
        return set()
    return set(query_ro("SELECT table_name FROM information_schema.tables")["table_name"])


def records(sql: str, params: Optional[list] = None) -> list[dict]:
    df = query(sql, params)
    if df.empty:
        return []
    df = df.astype(object).where(pd.notna(df), None)
    out = []
    for row in df.to_dict("records"):
        for k, v in row.items():
            if isinstance(v, (pd.Timestamp, datetime)):
                midnight = (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0)
                row[k] = v.date().isoformat() if midnight else v.isoformat(timespec="seconds")
            elif isinstance(v, date):
                row[k] = v.isoformat()
            elif hasattr(v, "tolist"):
                row[k] = v.tolist()
            elif isinstance(v, str) and k in ("payload", "agents", "meta") and v[:1] in "[{":
                try:
                    row[k] = json.loads(v)
                except ValueError:
                    pass
        out.append(row)
    return out


# --------------------------------------------------------------------------- calibrations météo
def save_weather_site(site: dict, cal, origin: str, topology: Optional[str] = None) -> None:
    from src.analytics.weather_indicators import calibration_to_rows
    now = datetime.now()
    rows = pd.DataFrame(calibration_to_rows(cal))
    with connect() as con:
        con.execute("DELETE FROM thresholds WHERE agent='weather' AND series=?", [site["site"]])
        if len(rows):
            rows = rows.rename(columns={"site": "series"}).assign(agent="weather", calibrated_at=now)
            upsert("thresholds", rows[["agent", "series", "indicator", "sens", "q", "seuil", "grid", "n", "period", "unit",
                                        "calibrated_at"]], con)
        upsert("wx_sites", pd.DataFrame([{
            "site": site["site"], "name": site.get("name") or site["site"], "country": site.get("country"),
            "lat": site.get("lat"), "lon": site.get("lon"), "role": site.get("role"), "fluvial": bool(site.get("fluvial")),
            "indicators": list(cal.indicators) or list(site.get("indicators") or []),
            "lat_debit": (cal.river or {}).get("lat_debit"), "lon_debit": (cal.river or {}).get("lon_debit"),
            "debit_median": (cal.river or {}).get("debit_median"), "climat": site.get("climat"), "origin": origin,
            "topology": topology, "node_id": site.get("node_id"), "updated_at": now}]), con)


def load_weather_calibrations(sites: Optional[Iterable[str]] = None) -> dict:
    """{site: SiteCalibration} depuis la base ; base absente -> {}."""
    from src.analytics.weather_indicators import calibration_from_rows
    if not settings.db_path.exists():
        return {}
    wanted = list(sites) if sites is not None else None
    th = query("SELECT * FROM thresholds WHERE agent='weather'")
    if th.empty:
        return {}
    meta = query("SELECT site, lat_debit, lon_debit, debit_median FROM wx_sites")
    rivers = {r.site: {"lat_debit": r.lat_debit, "lon_debit": r.lon_debit, "debit_median": r.debit_median}
              for r in meta.itertuples() if pd.notna(r.lat_debit)}
    out = {}
    for site, g in th.groupby("series"):
        if wanted is not None and site not in wanted:
            continue
        rows = [{"indicator": r.indicator, "sens": r.sens, "q": r.q, "seuil": r.seuil,
                 "grid": list(r.grid) if r.grid is not None else [], "n": r.n, "period": r.period} for r in g.itertuples()]
        cal = calibration_from_rows(site, rows)
        if cal:
            cal.river = rivers.get(site, {})
            out[site] = cal
    return out


# --------------------------------------------------------------------------- historique des exécutions
def record_run(run, engine, events_payload: list[dict], topology: str) -> Optional[str]:
    """Enregistre une exécution : résumé, risque de chaque nœud, alertes, événements et leurs rattachements."""
    now = datetime.now()
    run_id = f"{now:%Y%m%dT%H%M%S%f}"
    mode = run.mode if run.mode == "live" else f"replay:{run.scenario}"
    state = engine.state()
    families: dict[str, set] = {}
    for s in engine.current.signals:
        families.setdefault(s.node_id, set()).add(s.family)
    with connect() as con:
        upsert("runs", pd.DataFrame([{
            "run_id": run_id, "started_at": now, "mode": run.mode, "scenario": run.scenario, "topology": topology,
            "topology_name": run.topology_name, "as_of": run.as_of, "status": run.status,
            "global_risk_index": run.global_risk_index, "n_events": run.n_events, "n_signals": run.n_signals,
            "n_alerts": run.n_alerts, "agents": dumps({k: v.model_dump() for k, v in run.agents.items()}),
            "message": run.message}]), con)
        upsert("node_risk_history", pd.DataFrame([{
            "run_id": run_id, "as_of": run.as_of, "topology": topology, "node_id": n.id, "name": n.name, "type": n.type,
            "direct": n.direct, "propagated": n.propagated, "risk": n.risk, "level": n.level,
            "families": sorted(families.get(n.id, []))} for n in state.nodes]), con)
        alerts = engine.alerts()
        if alerts:
            upsert("alerts_history", pd.DataFrame([{
                "run_id": run_id, "alert_id": a.id, "node_id": a.node_id, "level": a.level, "risk": a.risk,
                "priority": a.priority, "agents": list(a.agents), "summary": a.summary} for a in alerts]), con)
        if events_payload:
            from src.graph.ontology_engine import FAMILY
            existing = {r[0]: r[1] for r in con.execute(
                "SELECT event_id, first_seen FROM events WHERE topology=? AND mode=?", [topology, mode]).fetchall()}
            ev_rows, link_rows = [], []
            for item in events_payload:
                ev = item["event"]
                eid = ev["event"]["id"]
                ev_rows.append({"event_id": eid, "topology": topology, "agent": item["agent"], "type": ev["event"]["type"],
                                "family": FAMILY.get(ev["event"]["type"]), "date_first": ev.get("date"),
                                "label": ev["event"]["label"], "confidence": ev["meta"]["confidence"], "payload": dumps(ev),
                                "source_ids": [m["source_id"] for m in ev.get("media", [])] +
                                              [b["source_id"] for b in (ev.get("weather"), ev.get("finance")) if b],
                                "first_seen": existing.get(eid, now), "last_seen": now, "last_run": run_id, "mode": mode})
                weights = item.get("weights") or {}
                for nid in item.get("nodes", []):
                    w = weights.get(nid, 1.0)
                    link_rows.append({"event_id": eid, "topology": topology, "node_id": nid,
                                      "link": "exact" if w >= 1.0 else "elargi", "weight": w})
            upsert("events", pd.DataFrame(ev_rows), con)
            upsert("event_links", pd.DataFrame(link_rows), con)
    return run_id


def save_bindings(topology: str, engine) -> None:
    """Référentiel nœud <-> identifiants externes, recalculé à chaque chargement de topologie."""
    rows = []
    for nid, w in engine.weather_site_config().items():
        rows.append({"topology": topology, "node_id": nid, "kind": "weather_site", "ext_id": nid,
                     "meta": dumps({"indicators": w["indicators"], "fluvial": w["fluvial"]})})
    for m in engine.market_signals:
        for nid in m.get("nodes", []):
            rows.append({"topology": topology, "node_id": nid, "kind": "market_signal", "ext_id": m["signal"],
                         "meta": dumps({"link": "exact"})})
        for nid in engine.nodes_for_inputs(m.get("inputs", [])):
            rows.append({"topology": topology, "node_id": nid, "kind": "market_signal", "ext_id": m["signal"],
                         "meta": dumps({"link": "exposé", "inputs": m.get("inputs")})})
    for s in engine.supplier_bindings:
        rows.append({"topology": topology, "node_id": s["node"], "kind": "supplier", "ext_id": s["proxy"],
                     "meta": dumps({"note": s.get("note", "")})})
    for w in engine.market_watch:
        for nid in w.get("nodes", []):
            rows.append({"topology": topology, "node_id": nid, "kind": "instrument", "ext_id": w["id"],
                         "meta": dumps({"yf": w.get("yf")})})
    with connect() as con:
        con.execute("DELETE FROM entity_bindings WHERE topology=?", [topology])
        if rows:
            upsert("entity_bindings", pd.DataFrame(rows).drop_duplicates(["topology", "node_id", "kind", "ext_id"]), con)
