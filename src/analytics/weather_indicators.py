"""Indicateurs météo et seuils propres à chaque site — méthode du notebook `meteo_supply_chain_v2.ipynb`.

Une perturbation vient d'un pic (rafale) ou d'une accumulation (trois mois de pluie, semaines de sécheresse sur
le Rhin) : les indicateurs portent sur plusieurs durées. Un indicateur alerte quand il dépasse son quantile 99 %
(ou passe sous son quantile 1 % pour le gel et les basses eaux), calculé sur 2010-2020 uniquement : les crises
récentes ne servent jamais à fixer les seuils. Seuls les indicateurs pertinents d'un site peuvent alerter.

La calibration d'un site est résumée par une grille de quantiles (`grid_p`, `grid_v`) : elle suffit à calculer
seuils et rangs plus tard, sans recharger quinze ans d'historique.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from src.analytics.thresholds import FIN_CALIBRATION, level_of_rank

INDICATEURS = pd.DataFrame([
    # id,            colonne,              sens,   q,    unité,  risque pour la supply chain
    ("pluie_3j", "pluie_3j", "haut", 0.99, "mm", "Crue éclair, routes et voies ferrées coupées"),
    ("pluie_90j", "pluie_90j", "haut", 0.99, "mm", "Inondation lente, zones industrielles noyées"),
    ("rafales", "wind_gusts_10m_max", "haut", 0.99, "km/h", "Arrêt des ports et des grues, dégâts"),
    ("neige", "snowfall_sum", "haut", 0.99, "cm", "Routes et rail bloqués"),
    ("chaleur", "temperature_2m_max", "haut", 0.99, "°C", "Canicule : coupures électriques, rendement"),
    ("gel", "temp_min_3j", "bas", 0.01, "°C", "Gel : coupures électriques, installations gelées"),
    ("crue", "debit_7j", "haut", 0.99, "m³/s", "Crue de rivière"),
    ("basses_eaux", "debit_7j", "bas", 0.01, "m³/s", "Navigation fluviale limitée"),
], columns=["indicateur", "colonne", "sens", "q", "unite", "risque"]).set_index("indicateur")
PLANCHER = {"neige": 1.0}          # en dessous d'1 cm, la neige ne bloque rien
LABELS = {"pluie_3j": "pluie sur 3 jours", "pluie_90j": "pluie sur 90 jours", "rafales": "rafales", "neige": "neige",
          "chaleur": "chaleur", "gel": "gel", "crue": "crue", "basses_eaux": "basses eaux"}

# Indicateurs par défaut quand la topologie ne les précise pas (choix métier, à adapter par site)
DEFAULTS_BY_TYPE = {"port": ["rafales", "pluie_3j", "neige"], "hub": ["rafales", "neige", "pluie_3j"],
                    "usine": ["pluie_3j", "rafales", "chaleur", "gel"], "fournisseur": ["pluie_3j", "rafales", "chaleur", "gel"],
                    "matiere_premiere": ["pluie_3j", "rafales"]}
RIVER_INDICATORS = ["crue", "basses_eaux"]

# Grille de quantiles : fine dans les queues (là où se jouent les alertes), grossière au centre
GRID_P = np.unique(np.concatenate([np.linspace(0, 0.02, 41), np.linspace(0.02, 0.98, 97), np.linspace(0.98, 1, 81)]))


def default_indicators(node_type: str, fluvial: bool = False) -> list[str]:
    return list(DEFAULTS_BY_TYPE.get(node_type, ["pluie_3j", "rafales"])) + (RIVER_INDICATORS if fluvial else [])


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Indicateurs d'accumulation pour UN site (df trié par date, colonnes Open-Meteo)."""
    df = df.sort_values("date").copy()
    for col in ("precipitation_sum", "temperature_2m_min", "temperature_2m_max", "wind_gusts_10m_max", "snowfall_sum"):
        if col not in df:
            df[col] = np.nan
    df["pluie_3j"] = df["precipitation_sum"].rolling(3, min_periods=3).sum()
    df["pluie_90j"] = df["precipitation_sum"].rolling(90, min_periods=80).sum()
    df["temp_min_3j"] = df["temperature_2m_min"].rolling(3, min_periods=3).min()
    df["debit_7j"] = (df["river_discharge"].rolling(7, min_periods=5).mean() if "river_discharge" in df
                      else np.nan)
    return df


@dataclass
class IndicatorCalibration:
    indicator: str
    sens: str
    q: float
    seuil: float
    grid_v: list[float]                 # valeurs aux probabilités GRID_P (période de calibration)
    n: int

    def rank(self, values) -> np.ndarray:
        """Rang dans le sens du risque, par interpolation dans la grille."""
        v = np.asarray(values, dtype=float)
        gv = np.asarray(self.grid_v, dtype=float)
        if not len(gv) or np.isnan(gv).all():
            return np.full(v.shape, np.nan)
        p = np.interp(v, gv, GRID_P[: len(gv)], left=0.0, right=1.0)
        r = p if self.sens == "haut" else 1 - p
        if self.sens == "haut" and self.indicator in PLANCHER:
            r = np.where(v < PLANCHER[self.indicator], 0.0, r)
        return np.where(np.isnan(v), np.nan, r)


@dataclass
class SiteCalibration:
    site: str
    indicators: dict[str, IndicatorCalibration] = field(default_factory=dict)
    score_grid: list[float] = field(default_factory=list)    # distribution du maximum des rangs (recalibration)
    period: str = f"2010-01-01/{FIN_CALIBRATION}"
    river: dict = field(default_factory=dict)                 # point GloFAS du fleuve principal (lat_debit, lon_debit)

    def score(self, rank_max) -> np.ndarray:
        v = np.asarray(rank_max, dtype=float)
        if not self.score_grid:
            return v
        p = np.interp(v, np.asarray(self.score_grid, dtype=float), GRID_P[: len(self.score_grid)], left=0.0, right=1.0)
        return np.where(np.isnan(v), np.nan, p)


def calibrate_site(site: str, hist: pd.DataFrame, indicators: Iterable[str],
                   fin_calibration: str = FIN_CALIBRATION) -> SiteCalibration:
    """Seuils et grilles d'un site à partir de son historique quotidien (déjà passé dans `add_indicators`)."""
    calib_rows = hist[hist["date"] <= pd.Timestamp(fin_calibration)]
    cal = SiteCalibration(site=site, period=f"{hist['date'].min().date()}/{fin_calibration}")
    for ind in indicators:
        if ind not in INDICATEURS.index:
            continue
        p = INDICATEURS.loc[ind]
        vals = calib_rows[p.colonne].dropna().to_numpy(dtype=float)
        if len(vals) < 365:                        # pas assez de données (ex. pas de rivière)
            continue
        seuil = float(np.quantile(vals, p.q))      # q = 0,99 (sens haut) ou 0,01 (sens bas)
        cal.indicators[ind] = IndicatorCalibration(ind, p.sens, float(p.q), round(seuil, 3),
                                                   [round(float(x), 3) for x in np.quantile(vals, GRID_P)], int(len(vals)))
    if cal.indicators:
        rmax = rank_matrix(calib_rows, cal).max(axis=1)
        if rmax.notna().any():
            cal.score_grid = [round(float(x), 5) for x in np.quantile(rmax.dropna().to_numpy(), GRID_P)]
    return cal


def exceeds(values: pd.Series, c: IndicatorCalibration) -> pd.Series:
    """Dépassement strict du seuil (et du plancher pour la neige), comme `depasse` dans le notebook."""
    v = pd.to_numeric(values, errors="coerce")
    if c.sens == "haut":
        return ((v > c.seuil) & (v >= PLANCHER.get(c.indicator, -np.inf))).fillna(False).astype(bool)
    return (v < c.seuil).fillna(False).astype(bool)


def rank_matrix(df: pd.DataFrame, cal: SiteCalibration) -> pd.DataFrame:
    return pd.DataFrame({ind: c.rank(df[INDICATEURS.loc[ind].colonne].to_numpy(dtype=float))
                         for ind, c in cal.indicators.items()}, index=df.index)


def evaluate_site(df: pd.DataFrame, cal: SiteCalibration) -> pd.DataFrame:
    """Drapeaux d'alerte, rangs et score météo recalibré, jour par jour (df passé dans `add_indicators`)."""
    out = df.copy()
    ranks = rank_matrix(out, cal)
    for ind, c in cal.indicators.items():
        out[f"alerte_{ind}"] = exceeds(out[INDICATEURS.loc[ind].colonne], c).to_numpy()
        out[f"rang_{ind}"] = ranks[ind].to_numpy()
    alert_cols = [f"alerte_{i}" for i in cal.indicators]
    out["alerte_meteo"] = out[alert_cols].any(axis=1) if alert_cols else False
    rmax = ranks.max(axis=1) if len(ranks.columns) else pd.Series(np.nan, index=out.index)
    out["score_meteo"] = cal.score(rmax.to_numpy())
    return out


def alerts_of(day: pd.Series, cal: SiteCalibration) -> list[dict]:
    """Indicateurs en alerte un jour donné, du plus extrême au moins extrême."""
    rows = []
    for ind, c in cal.indicators.items():
        if not bool(day.get(f"alerte_{ind}", False)):
            continue
        p = INDICATEURS.loc[ind]
        value = day.get(p.colonne)
        rank = day.get(f"rang_{ind}")
        rank = None if rank is None or pd.isna(rank) else round(float(rank), 4)
        rows.append({"indicator": ind, "label": LABELS[ind], "value": None if pd.isna(value) else round(float(value), 1),
                     "threshold": c.seuil, "unit": p.unite, "rank": rank, "level": level_of_rank(rank), "risk": p.risque})
    return sorted(rows, key=lambda r: -(r["rank"] or 0))


def calibration_to_rows(cal: SiteCalibration) -> list[dict]:
    rows = [{"site": cal.site, "indicator": ind, "sens": c.sens, "q": c.q, "seuil": c.seuil, "grid": c.grid_v, "n": c.n,
             "period": cal.period, "unit": INDICATEURS.loc[ind].unite} for ind, c in cal.indicators.items()]
    if cal.score_grid:
        rows.append({"site": cal.site, "indicator": "_score", "sens": "haut", "q": None, "seuil": None,
                     "grid": cal.score_grid, "n": None, "period": cal.period, "unit": ""})
    return rows


def calibration_from_rows(site: str, rows: Iterable[dict]) -> Optional[SiteCalibration]:
    cal = SiteCalibration(site=site)
    for r in rows:
        grid = list(r["grid"]) if r.get("grid") is not None else []
        if r["indicator"] == "_score":
            cal.score_grid = grid
        elif r["indicator"] in INDICATEURS.index:
            cal.indicators[r["indicator"]] = IndicatorCalibration(r["indicator"], r["sens"], float(r["q"] or 0.99),
                                                                  float(r["seuil"]), grid, int(r.get("n") or 0))
        cal.period = r.get("period") or cal.period
    return cal if cal.indicators else None
