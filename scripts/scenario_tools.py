"""Outils communs aux scripts qui fabriquent des scénarios de replay (données FICTIVES, graine fixe)."""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Optional

from src.graph.ontology_engine import OntologyEngine

HISTORY_DAYS = 45        # historique de cours avant le premier jour, nécessaire au calcul de l'écart


def day_map(start: date, days: int) -> dict[int, str]:
    return {k: (start + timedelta(days=k - 1)).isoformat() for k in range(1, days + 1)}


def build_media(prefix: str, days: dict[int, str], articles: list[tuple]) -> list[dict]:
    """articles : (jour, "HH:MM", langue, titre, texte). source_id = replay:<prefix>:<numéro>."""
    return [{"source_id": f"replay:{prefix}:{i:03d}", "published_at": f"{days[day]}T{hour}:00Z", "language": lang,
             "title": title, "text": text} for i, (day, hour, lang, title, text) in enumerate(articles, start=1)]


def build_weather(engine: OntologyEngine, days: dict[int, str], rng: random.Random,
                  overrides: Optional[dict] = None) -> list[dict]:
    """Un relevé calme par hub et par jour, sauf exceptions.

    overrides : {(nœud, jour d'émission, jour concerné): (vent moyen km/h, rafales km/h, pluie mm)}.
    Émission = jour concerné : relevé. Émission avant : prévision, visible dès le jour d'émission.
    """
    overrides = overrides or {}
    rows = []
    for hub in engine.weather_hubs():
        for day in days:
            wind, gust, rain = overrides.get(
                (hub.id, day, day), (rng.randint(10, 28), rng.randint(25, 45), rng.choice([0, 0, 0, 2, 5, 8])))
            rows.append({"node_id": hub.id, "date": days[day], "issued": days[day], "wind_max_kmh": wind,
                         "gust_max_kmh": gust, "precip_mm": rain, "weather_code": 65 if rain > 50 else 3,
                         "source_id": f"replay:meteo:{hub.id}:{days[day]}:releve"})
    for (node_id, issued, target), (wind, gust, rain) in overrides.items():
        if issued < target:
            rows.append({"node_id": node_id, "date": days[target], "issued": days[issued], "wind_max_kmh": wind,
                         "gust_max_kmh": gust, "precip_mm": rain, "weather_code": 65,
                         "source_id": f"replay:meteo:{node_id}:{days[target]}:prevision-J{issued}"})
    return rows


def build_finance(engine: OntologyEngine, start: date, n_days: int, rng: random.Random,
                  paths: Optional[dict] = None) -> dict[str, list[dict]]:
    """Cours quotidiens par instrument : bruit faible, plus les variations (%) de `paths` pendant le scénario."""
    paths = paths or {}
    out = {}
    for watch in engine.market_watch:
        close, rows = 100.0, []
        for offset in range(-HISTORY_DAYS, n_days):
            if offset >= 0:
                close *= 1 + (paths.get(watch["id"], [0.0] * n_days)[offset] + rng.uniform(-0.3, 0.3)) / 100
            else:
                close *= 1 + rng.uniform(-0.4, 0.4) / 100
            rows.append({"date": (start + timedelta(days=offset)).isoformat(), "close": round(close, 3)})
        out[watch["id"]] = rows
    return out
