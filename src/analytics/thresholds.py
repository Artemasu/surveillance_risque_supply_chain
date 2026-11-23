"""Méthode commune aux volets Météo et Finance.

    seuil      quantile q (sens « haut ») ou 1-q (sens « bas ») des valeurs de la période de calibration (2010-2020)
    rang       part des valeurs de calibration moins extrêmes que la valeur : 0,99 = parmi les 1 % les plus extrêmes
    épisodes   jours d'alerte consécutifs (un trou de moins de `ecart_max` jours ne coupe pas l'épisode)
    recalibrer le maximum de plusieurs rangs est biaisé vers le haut ; on le replace dans sa propre distribution
               de calibration (méthode du volet Météo, appliquée aussi au score finance pour les rendre comparables)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

FIN_CALIBRATION = "2020-12-31"


def calibration_values(values: pd.Series, fin_calibration: str = FIN_CALIBRATION, min_points: int = 250) -> pd.Series:
    """Valeurs jusqu'à `fin_calibration` ; pour une série trop récente, ses 3 premières années."""
    v = values.dropna()
    calib = v[v.index <= pd.Timestamp(fin_calibration)]
    if len(calib) < min_points and len(v):
        start = v.index[0]
        calib = v[(v.index >= start) & (v.index <= start + pd.DateOffset(years=3))]
    return calib


def threshold(calib: pd.Series | np.ndarray, sens: str, q: float, min_points: int = 30) -> float:
    arr = np.asarray(pd.Series(calib).dropna(), dtype=float)
    if len(arr) < min_points:
        return float("nan")
    return float(np.quantile(arr, q if sens == "haut" else 1 - q))


def is_alert(value, seuil: float, sens: str):
    """Fonctionne sur un scalaire ou une série ; NaN -> pas d'alerte."""
    if isinstance(value, (pd.Series, np.ndarray)):
        v = pd.Series(value, dtype=float)
        if np.isnan(seuil):
            return pd.Series(False, index=v.index)
        return (v >= seuil) if sens == "haut" else (v <= seuil)
    if value is None or pd.isna(value) or pd.isna(seuil):
        return False
    return bool(value >= seuil) if sens == "haut" else bool(value <= seuil)


def ranks(values, calib, sens: str, plancher: Optional[float] = None) -> np.ndarray:
    """Rang de chaque valeur dans la période de calibration (sens du risque). NaN conservés."""
    ref = np.sort(np.asarray(pd.Series(calib).dropna(), dtype=float))
    v = np.asarray(values, dtype=float)
    if not len(ref):
        return np.full(v.shape, np.nan)
    if sens == "haut":
        r = np.searchsorted(ref, v, side="left") / len(ref)
        if plancher is not None:
            r = np.where(v < plancher, 0.0, r)
    else:
        r = 1 - np.searchsorted(ref, v, side="right") / len(ref)
    return np.where(np.isnan(v), np.nan, r)


def rank_of(value, calib, sens: str) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    r = ranks([value], calib, sens)[0]
    return None if np.isnan(r) else round(float(r), 4)


def level_of_rank(rank: Optional[float]) -> str:
    if rank is None:
        return "inconnu"
    return "exceptionnel" if rank >= 0.99 else "inhabituel" if rank >= 0.90 else "normal"


def recalibrated_score(rank_max: pd.Series, calib_mask: pd.Series) -> pd.Series:
    """Score 0-1 : part des jours de calibration où le maximum des rangs était plus faible (0,5 = jour médian)."""
    ref = np.sort(rank_max[calib_mask].dropna().to_numpy())
    if not len(ref):
        return pd.Series(np.nan, index=rank_max.index)
    v = rank_max.to_numpy(dtype=float)
    return pd.Series(np.where(np.isnan(v), np.nan, np.searchsorted(ref, v, side="left") / len(ref)), index=rank_max.index)


def episodes(flags: pd.Series, ecart_max: int = 7) -> pd.DataFrame:
    """Jours d'alerte (index de dates) regroupés en épisodes : debut, fin, jours."""
    days = flags[flags.fillna(False).astype(bool)].index.sort_values()
    rows = []
    for d in days:
        if rows and (d - rows[-1]["fin"]).days <= ecart_max:
            rows[-1]["fin"] = d
            rows[-1]["jours"] += 1
        else:
            rows.append({"debut": d, "fin": d, "jours": 1})
    return pd.DataFrame(rows, columns=["debut", "fin", "jours"])


def intensity_from_rank(rank: Optional[float]) -> Optional[float]:
    """Intensité commune aux agents (0,3 à 1) : rang 0,90 -> 0,3 ; rang 0,999 et plus -> 1."""
    if rank is None or pd.isna(rank):
        return None
    return float(min(1.0, max(0.3, 0.3 + 0.7 * (rank - 0.90) / 0.099)))
