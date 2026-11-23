"""Endpoints des volets Météo et Finance, de l'historique et des stress tests (lecture de la base unifiée).

Aucun appel réseau pendant une requête GET : tout vient de la base, remplie par `python -m src.jobs ...`
ou par les deux POST /jobs/... (prévisions météo, collecte finance) déclenchés depuis l'interface.
Base vide : réponses vides avec `ready=false`, jamais d'erreur 500.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from src.analytics.thresholds import intensity_from_rank
from src.analytics.weather_indicators import INDICATEURS, LABELS
from src.config import settings
from src.graph.ontology_engine import BASE_SEVERITY, SOFT_LINK_CONFIDENCE
from src.storage import db

router = APIRouter()


def _svc(request: Request):
    return request.app.state.service


def _clean(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        return [_clean(v) for v in x.tolist()]
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, float) and (np.isnan(x) or np.isinf(x)):
        return None
    if isinstance(x, (np.floating,)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.date().isoformat()
    if isinstance(x, date):
        return x.isoformat()
    return x


def _rows(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{k: _clean(v) for k, v in r.items()} for r in df.astype(object).to_dict("records")]


def _site_nodes(request: Request) -> dict[str, list[dict]]:
    """Site calibré -> nœuds de la topologie active qui l'utilisent (et produits finis menacés en aval)."""
    eng = _svc(request).engine
    out: dict[str, list[dict]] = {}
    for nid, cfg in eng.weather_site_config().items():
        out.setdefault(cfg["site"], []).append({"node_id": nid, "name": eng.nodes[nid].name, "type": eng.nodes[nid].type,
                                                "products": eng.names(eng.downstream_products(nid))})
    return out


# =========================================================================== météo
@router.get("/weather/overview", tags=["météo"])
def weather_overview(request: Request) -> dict:
    """Sites suivis, score et alertes du dernier jour connu, alertes prévues à 16 jours, fiabilité."""
    sites = db.query("SELECT * FROM wx_sites ORDER BY site")
    if sites.empty:
        return {"ready": False, "sites": [], "forecast": [], "kpis": {}, "validation": [], "message":
                "Base météo vide : lancer python -m src.jobs import-notebooks (ou calibrate-meteo)."}
    last = db.query("""SELECT series AS site, max(date) AS last FROM indicators WHERE agent='weather' GROUP BY series""")
    day = db.query("""SELECT i.series AS site, i.indicator, i.value, i.threshold, i.rank, i.alert, i.date
                      FROM indicators i JOIN (SELECT series, max(date) d FROM indicators WHERE agent='weather' GROUP BY series) m
                      ON i.series=m.series AND i.date=m.d WHERE i.agent='weather'""")
    run = db.query("SELECT max(run_date) AS r FROM wx_forecast")
    run_date = None if run.empty or pd.isna(run["r"].iloc[0]) else run["r"].iloc[0]
    fc = db.query("SELECT * FROM wx_forecast WHERE run_date=? ORDER BY date", [run_date]) if run_date is not None else pd.DataFrame()
    noise = db.query("SELECT series AS site, indicator, episodes_per_year FROM noise WHERE agent='weather'")
    val = db.query("SELECT * FROM validation WHERE agent='weather'")
    links = _site_nodes(request)
    rows = []
    for s in _rows(sites):
        d = day[day["site"] == s["site"]]
        score = d[d["indicator"] == "_score"]
        inds = d[d["indicator"] != "_score"]
        site_fc = fc[(fc["site"] == s["site"]) & fc["alert"].astype(bool)] if len(fc) else pd.DataFrame()
        rows.append({**s, "last_date": _clean(last.set_index("site")["last"].get(s["site"])) if len(last) else None,
                     "score": _clean(score["value"].iloc[0]) if len(score) else None,
                     "alert_today": bool(inds["alert"].any()) if len(inds) else False,
                     "indicators_today": _rows(inds.drop(columns=["site", "date"])),
                     "forecast_alerts": len(site_fc),
                     "forecast_max_rank": _clean(fc[fc["site"] == s["site"]]["rank"].max()) if len(fc) else None,
                     "episodes_per_year": _clean(noise[noise["site"] == s["site"]]["episodes_per_year"].sum()) if len(noise) else None,
                     "nodes": links.get(s["site"], [])})
    fc_alerts = fc[fc["alert"].astype(bool)] if len(fc) else pd.DataFrame()
    best = val[val["detected"].astype(bool)]["lead_days"].max() if len(val) else None
    kpis = {"sites": len(rows), "sites_in_topology": sum(1 for r in rows if r["nodes"]),
            "alerts_today": sum(r["alert_today"] for r in rows), "forecast_alerts": int(len(fc_alerts)),
            "forecast_sites": int(fc_alerts["site"].nunique()) if len(fc_alerts) else 0,
            "best_lead_days": _clean(best), "episodes_per_year": _clean(noise["episodes_per_year"].sum()) if len(noise) else None,
            "forecast_run": _clean(run_date), "cases": int(len(val)),
            "cases_detected": int(val["detected"].astype(bool).sum()) if len(val) else 0,
            "hubs_calibrated": sum(1 for nid, c in _svc(request).engine.weather_site_config().items()
                                   if c["site"] in set(sites["site"])),
            "hubs_watched": len(_svc(request).engine.weather_site_config())}
    labels = {k: {"label": LABELS[k], "unit": INDICATEURS.loc[k].unite, "risk": INDICATEURS.loc[k].risque,
                  "sens": INDICATEURS.loc[k].sens} for k in INDICATEURS.index}
    return {"ready": True, "kpis": kpis, "sites": rows, "forecast": _rows(fc_alerts), "validation": _rows(val),
            "indicators": labels}


@router.get("/weather/sites/{site}/series", tags=["météo"])
def weather_series(site: str, indicator: str = Query(...), days: int = Query(365, ge=7, le=6000)) -> dict:
    """Série d'un indicateur avec son seuil, ses alertes et la bande saisonnière 2010-2020 (p10, médiane, p90)."""
    df = db.query("""SELECT date, value, threshold, rank, alert FROM indicators
                     WHERE agent='weather' AND series=? AND indicator=? ORDER BY date""", [site, indicator])
    if df.empty:
        raise HTTPException(404, f"aucune série pour {site} / {indicator}")
    df["date"] = pd.to_datetime(df["date"])
    calib = df[df["date"] <= "2020-12-31"].copy()
    calib["doy"] = calib["date"].dt.dayofyear.clip(upper=365)
    band = calib.groupby("doy")["value"].quantile([0.1, 0.5, 0.9]).unstack()
    band = band.rolling(15, center=True, min_periods=1).mean()          # lissage sur ± 7 jours
    recent = df[df["date"] >= df["date"].max() - pd.Timedelta(days=days)].copy()
    doy = recent["date"].dt.dayofyear.clip(upper=365)
    for q, name in ((0.1, "p10"), (0.5, "p50"), (0.9, "p90")):
        recent[name] = doy.map(band[q]).to_numpy() if q in band else np.nan
    recent["date"] = recent["date"].dt.date
    fc = db.query("""SELECT date, value, threshold, rank, alert FROM wx_forecast WHERE site=? AND indicator=?
                     AND run_date=(SELECT max(run_date) FROM wx_forecast WHERE site=?) ORDER BY date""", [site, indicator, site])
    p = INDICATEURS.loc[indicator] if indicator in INDICATEURS.index else None
    return {"site": site, "indicator": indicator, "label": LABELS.get(indicator, indicator),
            "unit": None if p is None else p.unite, "sens": None if p is None else p.sens,
            "threshold": _clean(df["threshold"].dropna().iloc[-1]) if df["threshold"].notna().any() else None,
            "series": _rows(recent), "forecast": _rows(fc)}


@router.get("/weather/heatmap", tags=["météo"])
def weather_heatmap(day: Optional[str] = None) -> dict:
    """Rang de chaque indicateur suivi, par site, un jour donné (défaut : dernier jour connu de chaque site)."""
    if day:
        df = db.query("""SELECT series AS site, indicator, rank, value, alert FROM indicators
                         WHERE agent='weather' AND indicator<>'_score' AND date=?""", [day])
    else:
        df = db.query("""SELECT i.series AS site, i.indicator, i.rank, i.value, i.alert FROM indicators i
                         JOIN (SELECT series, max(date) d FROM indicators WHERE agent='weather' GROUP BY series) m
                         ON i.series=m.series AND i.date=m.d WHERE i.agent='weather' AND i.indicator<>'_score'""")
    return {"day": day, "cells": _rows(df), "indicators": list(INDICATEURS.index)}


@router.get("/weather/episodes", tags=["météo"])
def weather_episodes(site: str, years: int = Query(15, ge=1, le=40)) -> list[dict]:
    """Jours d'alerte par mois (tous indicateurs) : la saisonnalité du risque d'un site."""
    df = db.query("""SELECT date_trunc('month', date) AS mois, count(DISTINCT date) AS jours FROM indicators
                     WHERE agent='weather' AND series=? AND indicator<>'_score' AND alert
                     AND date >= current_date - INTERVAL (?) YEAR GROUP BY 1 ORDER BY 1""", [site, years])
    return _rows(df)


# =========================================================================== finance
def _finance_situations(day: Optional[str]) -> list[dict]:
    from src.jobs.finance import latest_situations
    return latest_situations(day)


@router.get("/finance/overview", tags=["finance"])
def finance_overview(request: Request, day: Optional[str] = None) -> dict:
    """Situation de chaque signal (valeur, seuil, rang, alerte), score finance, fournisseurs, règles récentes."""
    sits = _finance_situations(day)
    if not sits:
        return {"ready": False, "signals": [], "kpis": {}, "suppliers": [], "message":
                "Base finance vide : lancer python -m src.jobs import-notebooks (ou ingest-finance)."}
    svc = _svc(request)
    bindings = {b["signal"]: b for b in svc.signal_bindings(svc.engine)}
    names = {n.id: n.name for n in svc.engine.nodes.values()}
    for s in sits:
        b = bindings.get(s["signal"]) or bindings.get("gazole_EU" if s["signal"].startswith("gazole_") else "")
        s["nodes"] = [] if not b else [{"node_id": n, "name": names[n], "link": "exact"} for n in b["exact"]] + \
                                      [{"node_id": n, "name": names[n], "link": "exposé"} for n in b["exposed"]]
    score = db.query("""SELECT date, value, alert FROM indicators WHERE agent='finance' AND series='_global'
                        AND indicator='_score' ORDER BY date DESC LIMIT 1""")
    suppliers = []
    supplier_nodes = {b["proxy"]: b["node"] for b in svc.engine.supplier_bindings}
    for r in db.records("SELECT cle, nom, pays, en_alerte, payload, updated_at FROM fin_suppliers ORDER BY nom"):
        p = r["payload"] if isinstance(r["payload"], dict) else {}
        suppliers.append({"cle": r["cle"], "nom": r["nom"], "pays": r["pays"], "en_alerte": r["en_alerte"],
                          "alertes": p.get("alertes", []), "bourse": p.get("bourse"),
                          "proprietaires": p.get("proprietaires", []),
                          "sanctions": len(p.get("sanctions") or []) or p.get("sanctions_count", 0),
                          "procedures": len(p.get("procedures_collectives") or []), "produit": p.get("produit"),
                          "node": supplier_nodes.get(r["cle"]), "node_name": names.get(supplier_nodes.get(r["cle"], ""), None),
                          "updated_at": r["updated_at"], "origine": p.get("origine", "collecte")})
    ref_day = pd.Timestamp(day or date.today())
    rules = db.query("SELECT * FROM fin_rules WHERE publication >= ? ORDER BY publication DESC",
                     [(ref_day - pd.Timedelta(days=90)).date()])
    gscpi = next((s for s in sits if s["signal"] == "gscpi"), None)
    eurusd = next((s for s in sits if s["signal"] == "eur_usd"), None)
    kpis = {"signals": len(sits), "signals_alert": sum(bool(s["en_alerte"]) for s in sits),
            "score": _clean(score["value"].iloc[0]) if len(score) else None,
            "score_date": _clean(score["date"].iloc[0]) if len(score) else None,
            "gscpi": None if not gscpi else gscpi["indicateur"], "gscpi_alert": bool(gscpi and gscpi["en_alerte"]),
            "eur_usd": None if not eurusd else eurusd["valeur_brute"], "eur_usd_var": None if not eurusd else eurusd["indicateur"],
            "suppliers": len(suppliers), "suppliers_alert": sum(bool(s["en_alerte"]) for s in suppliers),
            "rules_90d": int(len(rules)), "last_value": max(s["date_valeur"] for s in sits)}
    return {"ready": True, "kpis": kpis, "signals": sorted(sits, key=lambda s: (not s["en_alerte"], -(s["rang"] or 0))),
            "suppliers": suppliers, "rules_recent": _rows(rules.head(20))}


@router.get("/finance/signals/{signal}/series", tags=["finance"])
def finance_series(signal: str, start: str = "2019-01-01") -> dict:
    """Valeur brute, indicateur (variation ou niveau), seuil et alertes d'un signal."""
    from src.analytics.finance_indicators import catalog
    try:
        cat = catalog(signal)
    except KeyError:
        raise HTTPException(404, f"signal inconnu : {signal}")
    raw = db.query("SELECT date, valeur FROM fin_raw WHERE signal=? AND date>=? ORDER BY date", [signal, start])
    ind = db.query("""SELECT date, value AS indicateur, threshold AS seuil, rank AS rang, alert AS alerte FROM indicators
                      WHERE agent='finance' AND series=? AND date>=? ORDER BY date""", [signal, start])
    if raw.empty and ind.empty:
        raise HTTPException(404, f"aucune donnée pour {signal}")
    # indicateur sur les seules dates de publication (pas les jours remplis par report de la dernière valeur)
    m = raw.merge(ind, on="date", how="left") if len(raw) else ind
    return {"signal": signal, "nom": cat["nom"], "famille": cat["famille"], "unite": cat["unite"], "sens": cat["sens"],
            "mesure": cat["mesure"], "horizon": int(cat["horizon"]), "impact": cat["impact"], "source": cat["source"],
            "seuil": _clean(ind["seuil"].dropna().iloc[-1]) if len(ind) and ind["seuil"].notna().any() else None,
            "series": _rows(m)}


@router.get("/finance/base100", tags=["finance"])
def finance_base100(start: str = "2019-01-01", signals: Optional[str] = None) -> dict:
    """Tous les signaux en base 100 à `start` (une valeur par semaine), pour les comparer d'un coup d'œil."""
    raw = db.query("SELECT signal, date, valeur FROM fin_raw WHERE date>=? ORDER BY date", [start])
    if raw.empty:
        return {"start": start, "series": [], "signals": []}
    if signals:
        raw = raw[raw["signal"].isin(signals.split(","))]
    raw["date"] = pd.to_datetime(raw["date"])
    wide = raw.pivot_table(index="date", columns="signal", values="valeur").resample("W-MON").last().ffill(limit=6)
    base = wide.apply(lambda s: 100 * s / s.dropna().iloc[0] if s.notna().any() else s)
    base = base.round(1).reset_index()
    base["date"] = base["date"].dt.date
    return {"start": start, "signals": [c for c in base.columns if c != "date"], "series": _rows(base)}


@router.get("/finance/score", tags=["finance"])
def finance_score(start: str = "2019-01-01") -> list[dict]:
    df = db.query("""SELECT date, value AS score, alert FROM indicators WHERE agent='finance' AND series='_global'
                     AND indicator='_score' AND date>=? ORDER BY date""", [start])
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    w = df.set_index("date").resample("W-MON").agg({"score": "max", "alert": "max"}).reset_index()
    w["date"] = w["date"].dt.date
    return _rows(w)


@router.get("/finance/suppliers/{cle}", tags=["finance"])
def finance_supplier(cle: str, request: Request) -> dict:
    rows = db.records("SELECT payload FROM fin_suppliers WHERE cle=?", [cle])
    if not rows:
        raise HTTPException(404, f"fournisseur inconnu : {cle}")
    p = rows[0]["payload"]
    svc = _svc(request)
    node = next((b["node"] for b in svc.engine.supplier_bindings if b["proxy"] == cle), None)
    p["node"] = node
    p["node_name"] = svc.engine.nodes[node].name if node else None
    p["products"] = svc.engine.names(svc.engine.downstream_products(node)) if node else []
    raw = db.query("SELECT date, valeur FROM fin_raw WHERE signal=? AND date >= current_date - INTERVAL 2 YEAR ORDER BY date",
                   [f"bourse_{cle}"])
    p["stock"] = _rows(raw)
    return p


@router.get("/finance/rules", tags=["finance"])
def finance_rules(zone: Optional[str] = None, since: str = "2022-01-01") -> list[dict]:
    sql, params = "SELECT * FROM fin_rules WHERE publication >= ?", [since]
    if zone:
        sql += " AND zone = ?"
        params.append(zone)
    return _rows(db.query(sql + " ORDER BY publication DESC", params))


@router.get("/finance/diesel", tags=["finance"])
def finance_diesel() -> dict:
    """Dernier prix du gazole par pays, variation sur 4 semaines et délai de transmission Brent -> pompe."""
    df = db.query("SELECT pays, date, valeur FROM fin_diesel ORDER BY pays, date")
    tr = db.query("SELECT * FROM fin_transmission")
    out = []
    for pays, g in df.groupby("pays"):
        g = g.dropna()
        if len(g) < 5:
            continue
        out.append({"pays": pays, "date": _clean(g["date"].iloc[-1]), "prix": round(float(g["valeur"].iloc[-1]), 3),
                    "var_4s": round(100 * (g["valeur"].iloc[-1] / g["valeur"].iloc[-5] - 1), 2)})
    trans = {r["pays"]: r for r in _rows(tr)}
    for r in out:
        t = trans.get(r["pays"], {})
        r["decalage_semaines"], r["correlation"] = t.get("decalage_semaines"), t.get("correlation")
    return {"countries": out}


@router.get("/finance/validation", tags=["finance"])
def finance_validation() -> dict:
    return {"cases": db.records("SELECT * FROM validation WHERE agent='finance'"),
            "noise": _rows(db.query("SELECT series AS signal, episodes_per_year FROM noise WHERE agent='finance' ORDER BY 2 DESC"))}


# =========================================================================== historique
@router.get("/history/runs", tags=["historique"])
def history_runs(limit: int = Query(50, ge=1, le=500), topology: Optional[str] = None) -> list[dict]:
    sql, params = "SELECT run_id, started_at, mode, scenario, topology, topology_name, as_of, status, global_risk_index, n_events, n_signals, n_alerts, message FROM runs", []
    if topology:
        sql += " WHERE topology=?"
        params.append(topology)
    return db.records(sql + " ORDER BY started_at DESC LIMIT ?", params + [limit])


@router.get("/history/risk", tags=["historique"])
def history_risk(topology: Optional[str] = None, node_id: Optional[str] = None, mode: Optional[str] = None) -> dict:
    """Indice global et risque d'un nœud au fil des exécutions (une valeur par date de situation : la plus récente)."""
    where, params = ["1=1"], []
    if topology:
        where.append("r.topology=?")
        params.append(topology)
    if mode:
        where.append("r.mode=?")
        params.append(mode)
    runs = db.query(f"""SELECT r.run_id, r.as_of, r.mode, r.scenario, r.global_risk_index, r.n_alerts, r.started_at
                        FROM runs r WHERE {' AND '.join(where)} ORDER BY r.started_at""", params)
    if runs.empty:
        return {"global": [], "node": [], "top": []}
    latest = runs.sort_values("started_at").groupby(["as_of", "mode", "scenario"], dropna=False).tail(1).sort_values("as_of")
    node = []
    if node_id:
        nr = db.query("SELECT run_id, direct, propagated, risk, level FROM node_risk_history WHERE node_id=?", [node_id])
        node = _rows(latest[["run_id", "as_of", "mode", "scenario"]].merge(nr, on="run_id"))
    last_run = runs.iloc[-1]["run_id"]
    top = db.query("""SELECT node_id, name, type, risk, level, families FROM node_risk_history WHERE run_id=?
                      ORDER BY risk DESC LIMIT 12""", [last_run])
    return {"global": _rows(latest.drop(columns=["started_at"])), "node": node, "top": _rows(top)}


@router.get("/history/events", tags=["historique"])
def history_events(topology: Optional[str] = None, agent: Optional[str] = None, family: Optional[str] = None,
                   since: Optional[str] = None, mode: Optional[str] = None, limit: int = Query(200, ge=1, le=2000)) -> list[dict]:
    where, params = ["1=1"], []
    for col, val in (("topology", topology), ("agent", agent), ("family", family), ("mode", mode)):
        if val:
            where.append(f"e.{col}=?")
            params.append(val)
    if since:
        where.append("e.date_first>=?")
        params.append(since)
    rows = db.records(f"""SELECT e.event_id, e.topology, e.agent, e.type, e.family, e.date_first, e.label, e.confidence,
                                 e.first_seen, e.last_seen, e.mode, e.source_ids,
                                 (SELECT list(l.node_id) FROM event_links l WHERE l.event_id=e.event_id AND l.topology=e.topology) AS nodes
                          FROM events e WHERE {' AND '.join(where)} ORDER BY e.date_first DESC NULLS LAST, e.last_seen DESC LIMIT ?""",
                      params + [limit])
    return rows


@router.get("/history/compare", tags=["historique"])
def history_compare(a: str, b: str) -> dict:
    """Risque de chaque nœud entre deux exécutions (a = avant, b = après)."""
    df = db.query("""SELECT coalesce(x.node_id, y.node_id) AS node_id, coalesce(x.name, y.name) AS name,
                            coalesce(x.type, y.type) AS type, x.risk AS before, y.risk AS after, y.level
                     FROM (SELECT * FROM node_risk_history WHERE run_id=?) x
                     FULL JOIN (SELECT * FROM node_risk_history WHERE run_id=?) y ON x.node_id=y.node_id""", [a, b])
    if df.empty:
        raise HTTPException(404, "exécutions introuvables")
    df["delta"] = df["after"].fillna(0) - df["before"].fillna(0)
    return {"a": a, "b": b, "nodes": _rows(df.sort_values("delta", ascending=False))}


# =========================================================================== état, tâches, stress tests
@router.get("/sources/status", tags=["système"])
def sources_status(request: Request) -> dict:
    counts = {}
    tables = ("wx_sites", "thresholds", "indicators", "wx_forecast", "fin_raw", "fin_suppliers", "fin_rules", "events", "runs")
    if settings.db_path.exists():
        df = db.query(" UNION ALL ".join(f"SELECT '{t}' AS t, COUNT(*) AS n FROM {t}" for t in tables))
        counts = {r.t: int(r.n) for r in df.itertuples()}
    return {"db": str(settings.db_path), "ready": bool(counts.get("wx_sites") or counts.get("fin_raw")), "counts": counts,
            "sources": db.records("SELECT * FROM sources ORDER BY agent, source_id"),
            "calibrated_hubs": [nid for nid, c in _svc(request).engine.weather_site_config().items()
                                if c["site"] in set(db.query("SELECT site FROM wx_sites")["site"] if counts.get("wx_sites") else [])]}


_JOB_LOCK = asyncio.Lock()


@router.post("/jobs/{name}", tags=["système"])
async def run_job(name: str) -> dict:
    """Tâches courtes déclenchables depuis l'interface (réseau). La calibration reste en ligne de commande."""
    if name not in ("forecast-meteo", "ingest-finance"):
        raise HTTPException(400, "tâches disponibles : forecast-meteo, ingest-finance")
    if _JOB_LOCK.locked():
        raise HTTPException(409, "une tâche est déjà en cours")
    async with _JOB_LOCK:
        if name == "forecast-meteo":
            from src.jobs.meteo import forecast_sites
            return {"job": name, "result": await asyncio.to_thread(forecast_sites)}
        from src.jobs.finance import ingest
        return {"job": name, "result": await asyncio.to_thread(ingest, suppliers=True, rules=True)}


def _severity(event_type: str, rank: float, weight: float = 1.0, confidence: float = 0.9) -> float:
    """Gravité d'un choc, calculée comme le moteur le ferait pour un événement de ce rang."""
    return round(min(1.0, BASE_SEVERITY[event_type] * (intensity_from_rank(rank) or 0.3) * weight * confidence), 3)


@router.get("/graph/stress-tests", tags=["graphe"])
def stress_tests(request: Request) -> list[dict]:
    """Stress tests prédéfinis tirés des volets Météo et Finance de la topologie active (centile 99,5 des sites)."""
    svc = _svc(request)
    eng = svc.engine
    out = []
    priority = ["basses_eaux", "pluie_90j", "rafales", "crue", "pluie_3j", "gel"]   # un aléa par site : le plus typique
    for nid, cfg in eng.weather_site_config().items():
        for ind in sorted((i for i in cfg["indicators"] if i in priority), key=priority.index)[:1]:
            label = {"rafales": "Tempête : rafales au centile 99,5", "basses_eaux": "Sécheresse : basses eaux du fleuve",
                     "pluie_90j": "Mousson : inondation lente", "crue": "Crue du fleuve", "pluie_3j": "Pluie diluvienne sur 3 jours",
                     "gel": "Vague de froid"}[ind]
            shocks = {n: _severity("meteo_extreme", 0.995) for n, c in eng.weather_site_config().items()
                      if c["site"] == cfg["site"] and ind in c["indicators"]}
            key = f"wx:{cfg['site']}:{ind}"
            if any(o["id"] == key for o in out):
                continue
            out.append({"id": key, "family": "climat", "agent": "weather", "label": f"{label} à {cfg['name']}",
                        "detail": INDICATEURS.loc[ind].risque, "shocks": shocks})
    for b in svc.signal_bindings(eng):
        from src.analytics.finance_indicators import catalog
        try:
            cat = catalog(b["signal"])
        except KeyError:
            continue
        shocks = {n: _severity("tension_marche", 0.995) for n in b["exact"]}
        shocks.update({n: _severity("tension_marche", 0.995, SOFT_LINK_CONFIDENCE) for n in b["exposed"] if n not in shocks})
        if shocks:
            sens = "flambée" if cat["sens"] == "haut" else "chute"
            out.append({"id": f"fin:{b['signal']}", "family": "marche", "agent": "finance",
                        "label": f"{cat['nom']} : {sens} au centile 99,5", "detail": cat["impact"], "shocks": shocks})
    for s in eng.supplier_bindings:
        out.append({"id": f"sanction:{s['proxy']}", "family": "reglementaire", "agent": "finance",
                    "label": f"Sanction sur {eng.nodes[s['node']].name} ou sa maison mère",
                    "detail": "Ruptures d'approvisionnement, paiements bloqués", "shocks": {s["node"]: _severity("sanction", 0.999)}})
        out.append({"id": f"faillite:{s['proxy']}", "family": "financier", "agent": "finance",
                    "label": f"Procédure collective chez {eng.nodes[s['node']].name}",
                    "detail": "Fournisseur en redressement ou liquidation", "shocks": {s["node"]: 0.85}})
    return out
