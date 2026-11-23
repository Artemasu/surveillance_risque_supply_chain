"""Open-Meteo (gratuit en usage non commercial, sans clé, licence CC-BY 4.0) — repris de `meteo_collecte.py`.

    historique()   réanalyse ERA5, la météo « observée » (1940 -> il y a ~5 jours)
    prevision()    prévisions quotidiennes jusqu'à 16 jours (cache de 3 heures)
    debit()        débit des rivières, modèle GloFAS (m³/s)
    trouver_fleuve() cellule GloFAS au plus fort débit autour d'un point (le fleuve principal)
    climatologie() normales 1991-2020 (référence officielle de l'OMM)
    geocoder()     nom de lieu -> coordonnées
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from src.connectors.http_cache import SourceError, fetch_json

URL_GEOCODAGE = "https://geocoding-api.open-meteo.com/v1/search"
URL_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
URL_PREVISION = "https://api.open-meteo.com/v1/forecast"
URL_DEBIT = "https://flood-api.open-meteo.com/v1/flood"
NS = "openmeteo"

VARIABLES_JOUR = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "precipitation_hours",
                  "snowfall_sum", "wind_speed_10m_max", "wind_gusts_10m_max", "weather_code"]
REFERENCE = ("1991-01-01", "2020-12-31")
RETARD_ERA5 = 6            # jours : en deçà, l'archive n'est pas encore consolidée, on prend la prévision
HORIZON_PREVISION = 16
DEBIT_MIN_PLAUSIBLE = 20   # m³/s : en dessous, sans doute un ruisseau, pas un fleuve
FORECAST_TTL_DAYS = 0.125  # 3 heures


def as_date(d) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    return pd.Timestamp(d).date()


def _frame(data: dict, bloc: str = "daily") -> pd.DataFrame:
    if bloc not in data:
        raise SourceError(f"réponse Open-Meteo sans bloc « {bloc} »")
    df = pd.DataFrame(data[bloc])
    df["time"] = pd.to_datetime(df["time"])
    return df.rename(columns={"time": "date"})


def geocoder(nom: str, pays: Optional[str] = None) -> dict:
    params = {"name": nom, "count": 1, "language": "fr", "format": "json"}
    if pays:
        params["countryCode"] = pays
    res = fetch_json(URL_GEOCODAGE, params, namespace=NS, ttl_days=30).get("results") or []
    if not res:
        raise SourceError(f"lieu introuvable : « {nom} »")
    r = res[0]
    return {"nom": r.get("name", nom), "lat": r["latitude"], "lon": r["longitude"], "pays": r.get("country"),
            "code_pays": r.get("country_code"), "fuseau": r.get("timezone")}


def historique(lat: float, lon: float, debut, fin, variables: Iterable[str] = VARIABLES_JOUR) -> pd.DataFrame:
    """Météo quotidienne observée (ERA5), de debut à fin inclus. Historique figé : cache permanent."""
    params = dict(latitude=round(lat, 3), longitude=round(lon, 3), start_date=str(as_date(debut)),
                  end_date=str(as_date(fin)), daily=",".join(variables), timezone="auto")
    return _frame(fetch_json(URL_ARCHIVE, params, namespace=NS, ttl_days=None, pause=0.6))


def prevision(lat: float, lon: float, jours: int = HORIZON_PREVISION, past_days: int = 3,
              variables: Iterable[str] = VARIABLES_JOUR) -> pd.DataFrame:
    """Les `past_days` derniers jours et les `jours` prochains (prévision, cache de 3 heures)."""
    params = dict(latitude=round(lat, 3), longitude=round(lon, 3), daily=",".join(variables), timezone="auto",
                  forecast_days=jours, past_days=past_days)
    return _frame(fetch_json(URL_PREVISION, params, namespace=NS, ttl_days=FORECAST_TTL_DAYS))


def debit(lat: float, lon: float, debut=None, fin=None, past_days: int = 0, forecast_days: int = 0) -> pd.DataFrame:
    """Débit quotidien de la rivière (GloFAS), m³/s. Période figée (cache permanent) ou fenêtre glissante (3 h)."""
    params = dict(latitude=round(lat, 3), longitude=round(lon, 3), daily="river_discharge")
    if debut is not None:
        params.update(start_date=str(as_date(debut)), end_date=str(as_date(fin or debut)))
        ttl = None if as_date(fin or debut) < date.today() - timedelta(days=30) else FORECAST_TTL_DAYS
    else:
        params.update(past_days=past_days, forecast_days=forecast_days)
        ttl = FORECAST_TTL_DAYS
    return _frame(fetch_json(URL_DEBIT, params, namespace=NS, ttl_days=ttl))


def trouver_fleuve(lat: float, lon: float, rayon: float = 0.1, pas: float = 0.05) -> dict:
    """Cherche autour du point la cellule au plus fort débit médian (2015-2016) : le fleuve principal."""
    meilleur = {"lat_debit": lat, "lon_debit": lon, "debit_median": float("nan")}
    for dlat in np.arange(-rayon, rayon + 1e-9, pas):
        for dlon in np.arange(-rayon, rayon + 1e-9, pas):
            la, lo = round(lat + dlat, 3), round(lon + dlon, 3)
            try:
                med = debit(la, lo, "2015-01-01", "2016-12-31")["river_discharge"].median()
            except SourceError:
                continue
            if pd.notna(med) and not (med <= meilleur["debit_median"]):
                meilleur = {"lat_debit": la, "lon_debit": lo, "debit_median": float(med)}
    meilleur["plausible"] = bool(meilleur["debit_median"] >= DEBIT_MIN_PLAUSIBLE)
    return meilleur


def climatologie(lat: float, lon: float, reference=REFERENCE) -> pd.DataFrame:
    """Météo quotidienne 1991-2020, pour situer un jour par rapport à la normale."""
    df = historique(lat, lon, reference[0], reference[1],
                    variables=["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_gusts_10m_max"])
    df["pluie_3j"] = df["precipitation_sum"].rolling(3, min_periods=3).sum()
    return df
