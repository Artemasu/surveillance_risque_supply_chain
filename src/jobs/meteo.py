"""Tâches du volet Météo : calibration des sites, prévisions à 16 jours, import des sorties du notebook."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.analytics.thresholds import episodes
from src.analytics.weather_indicators import (INDICATEURS, SiteCalibration, add_indicators, calibrate_site,
                                              evaluate_site)
from src.connectors import openmeteo as om
from src.connectors.http_cache import SourceError
from src.connectors.koppen import classe_climatique
from src.storage import db

log = logging.getLogger("supplychain.jobs")
DEBUT = "2010-01-01"


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def indicator_rows(site: str, ev: pd.DataFrame, cal: SiteCalibration) -> pd.DataFrame:
    """Format long de la table `indicators` : un indicateur par ligne et par jour, plus le score du site."""
    parts = []
    for ind, c in cal.indicators.items():
        col = INDICATEURS.loc[ind].colonne
        parts.append(pd.DataFrame({"agent": "weather", "series": site, "indicator": ind, "date": ev["date"].dt.date,
                                   "value": ev[col].to_numpy(dtype=float), "threshold": c.seuil,
                                   "rank": ev[f"rang_{ind}"].to_numpy(dtype=float),
                                   "alert": ev[f"alerte_{ind}"].astype(bool).to_numpy()}))
    parts.append(pd.DataFrame({"agent": "weather", "series": site, "indicator": "_score", "date": ev["date"].dt.date,
                               "value": ev["score_meteo"].to_numpy(dtype=float), "threshold": np.nan, "rank": np.nan,
                               "alert": ev["alerte_meteo"].astype(bool).to_numpy()}))
    out = pd.concat(parts, ignore_index=True)
    return out[out["value"].notna() | out["alert"]]


def noise_rows(site: str, ev: pd.DataFrame, cal: SiteCalibration) -> pd.DataFrame:
    years = max((ev["date"].max() - ev["date"].min()).days / 365.25, 1)
    flags = ev.set_index("date")
    return pd.DataFrame([{"agent": "weather", "series": site, "indicator": ind,
                          "episodes_per_year": round(len(episodes(flags[f"alerte_{ind}"], ecart_max=1)) / years, 3)}
                         for ind in cal.indicators])


def store_site(site: dict, hist: pd.DataFrame, origin: str, topology: Optional[str] = None,
               river: Optional[dict] = None) -> SiteCalibration:
    """Calibre un site, enregistre seuils, indicateurs jour par jour et bruit (épisodes par an)."""
    df = add_indicators(hist)
    cal = calibrate_site(site["site"], df, site["indicators"])
    cal.river = river or {}
    ev = evaluate_site(df, cal)
    db.save_weather_site(site, cal, origin, topology)
    with db.connect() as con:
        con.execute("DELETE FROM indicators WHERE agent='weather' AND series=?", [site["site"]])
        db.upsert("indicators", indicator_rows(site["site"], ev, cal), con)
        db.upsert("noise", noise_rows(site["site"], ev, cal), con)
    return cal


# --------------------------------------------------------------------------- import du notebook
def import_notebook(folder: Path) -> dict:
    """Sorties de `meteo_supply_chain_v2.ipynb` -> base : sites, seuils recalculés, indicateurs, alertes, validation."""
    sorties = folder / "meteo" / "sorties"
    sites = pd.read_csv(sorties / "meteo_sites.csv")
    brut = pd.read_csv(sorties / "meteo_brut.csv", parse_dates=["date"])
    n = 0
    for s in sites.itertuples():
        site = {"site": slug(s.site), "name": s.site, "country": s.pays, "lat": s.lat, "lon": s.lon, "role": s.role,
                "fluvial": bool(s.fluvial), "indicators": [i.strip() for i in str(s.indicateurs).split(",")],
                "climat": getattr(s, "climat", None) if hasattr(s, "climat") else None}
        river = ({"lat_debit": s.lat_debit, "lon_debit": s.lon_debit, "debit_median": s.debit_median}
                 if pd.notna(getattr(s, "lat_debit", np.nan)) else {})
        store_site(site, brut[brut["site"] == s.site], origin="notebook", river=river)
        n += 1
    out = {"sites": n}
    names = {s.site: slug(s.site) for s in sites.itertuples()}
    f = sorties / "meteo_alertes_16_jours.csv"
    if f.exists():
        al = pd.read_csv(f)
        if len(al):
            run_date = pd.to_datetime(al["date"]).min().date() - timedelta(days=1)
            al = pd.DataFrame({"site": al["site"].map(names), "run_date": run_date, "date": pd.to_datetime(al["date"]).dt.date,
                               "indicator": al["indicateur"], "value": al["valeur"], "threshold": al["seuil"], "rank": np.nan,
                               "alert": True, "unit": al["unite"], "risk": al["risque"], "score": np.nan})
            db.upsert("wx_forecast", al)
        out["alertes_prevues"] = len(al)
    f = sorties / "meteo_validation_cas.csv"
    if f.exists():
        v = pd.read_csv(f)
        rows = pd.DataFrame({"agent": "weather", "cas": v["cas"], "cible": v["site"].map(names).fillna(v["site"]),
                             "indicator": v["indicateur"] + " · " + v["source"].astype(str),
                             "detected": v["alerte_avant_perturbation"].astype(bool), "lead_days": v["jours_avance"],
                             "payload": [db.dumps(r) for r in v.astype(object).where(pd.notna(v), None).to_dict("records")]})
        db.upsert("validation", rows.drop_duplicates(["agent", "cas", "cible", "indicator"]))
        out["cas_valides"] = len(v)
    f = sorties / "meteo_helene_previsions.csv"
    if f.exists():
        h = pd.read_csv(f)
        db.upsert("validation", pd.DataFrame([{"agent": "weather", "cas": "Ouragan Helene (prévisions archivées)",
                                               "cible": "spruce_pine", "indicator": "pluie_3j · prévisions",
                                               "detected": bool(h["depasse_seuil"].any()),
                                               "lead_days": float(h[h["depasse_seuil"]]["avance"].str.extract(r"J-(\d+)")[0].astype(float).max() or 0),
                                               "payload": db.dumps(h.astype(object).where(pd.notna(h), None).to_dict("records"))}]))
    return out


# --------------------------------------------------------------------------- calibration d'une topologie
def calibrate_topology(engine, topology: str, debut: str = DEBUT, force: bool = False, only: Optional[list[str]] = None) -> list[dict]:
    """Historique ERA5 (+ débit pour les sites fluviaux) puis seuils de chaque hub surveillé de la topologie.

    Coût Open-Meteo : environ 250 « appels » pondérés par site pour 15 ans de données (limite gratuite : 10 000 par
    jour). Le cache rend la tâche reprenable : relancer après une limite de débit ne refait pas les sites déjà lus."""
    done = set() if force else set(db.load_weather_calibrations())
    fin = date.today() - timedelta(days=om.RETARD_ERA5 + 1)
    bilan = []
    for nid, w in engine.weather_site_config().items():
        if only and nid not in only:
            continue
        site_id = w["site"]
        if site_id in done:
            bilan.append({"site": site_id, "statut": "déjà calibré"})
            continue
        info = {"site": site_id, "statut": "✗"}
        try:
            hist = om.historique(w["lat"], w["lon"], debut, fin)
            river = {}
            if w["fluvial"]:
                river = om.trouver_fleuve(w["lat"], w["lon"])
                if river.get("plausible"):
                    hist = hist.merge(om.debit(river["lat_debit"], river["lon_debit"], debut, fin), on="date", how="left")
            climat = classe_climatique(w["lat"], w["lon"])
            site = {"site": site_id, "name": w["name"], "country": w["country"], "lat": w["lat"], "lon": w["lon"],
                    "role": w["role"], "fluvial": w["fluvial"], "indicators": w["indicators"], "node_id": nid,
                    "climat": (climat or {}).get("classe")}
            cal = store_site(site, hist, origin="calibration", topology=topology, river=river)
            info.update(statut="✓", indicateurs=", ".join(f"{k} {c.seuil:g}" for k, c in cal.indicators.items()))
        except SourceError as e:
            info["erreur"] = str(e)[:160]
        bilan.append(info)
        log.info("calibration %s : %s", site_id, info["statut"])
    return bilan


def forecast_sites(sites: Optional[list[str]] = None) -> dict:
    """Prévisions à 16 jours de tous les sites calibrés : indicateurs du jour et alertes prévues (table wx_forecast)."""
    cals = db.load_weather_calibrations(sites)
    meta = db.query("SELECT site, lat, lon FROM wx_sites")
    pos = {r.site: (r.lat, r.lon) for r in meta.itertuples()}
    today = date.today()
    rows, ok, errors = [], 0, {}
    for site, cal in cals.items():
        if site not in pos:
            continue
        lat, lon = pos[site]
        try:
            past = 92 if "pluie_90j" in cal.indicators else 3
            df = om.prevision(lat, lon, past_days=past)
            if {"crue", "basses_eaux"} & set(cal.indicators) and cal.river.get("lat_debit"):
                df = df.merge(om.debit(cal.river["lat_debit"], cal.river["lon_debit"], past_days=10, forecast_days=16),
                              on="date", how="left")
        except SourceError as e:
            errors[site] = str(e)[:120]
            continue
        ok += 1
        ev = evaluate_site(add_indicators(df), cal)
        ev = ev[ev["date"].dt.date >= today]
        for _, day in ev.iterrows():
            for ind, c in cal.indicators.items():
                v = day.get(INDICATEURS.loc[ind].colonne)
                if v is None or pd.isna(v):
                    continue
                rows.append({"site": site, "run_date": today, "date": day["date"].date(), "indicator": ind,
                             "value": float(v), "threshold": c.seuil, "rank": float(day[f"rang_{ind}"]),
                             "alert": bool(day[f"alerte_{ind}"]), "unit": INDICATEURS.loc[ind].unite,
                             "risk": INDICATEURS.loc[ind].risque, "score": float(day["score_meteo"])})
    if rows:
        with db.connect() as con:
            con.execute("DELETE FROM wx_forecast WHERE run_date=?", [today])
            db.upsert("wx_forecast", pd.DataFrame(rows), con)
    db.upsert("sources", pd.DataFrame([{"source_id": "open-meteo:forecast", "agent": "weather", "provider": "Open-Meteo",
                                        "status": "ok" if not errors else "partial" if ok else "failed",
                                        "detail": db.dumps(errors) if errors else f"{ok} sites", "checked_at": datetime.now()}]))
    return {"sites": len(cals), "lus": ok, "lignes": len(rows), "alertes": sum(r["alert"] for r in rows), "echecs": errors}
