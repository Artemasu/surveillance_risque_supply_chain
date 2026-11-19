"""Agent météo : conditions extrêmes sur les hubs du graphe (Open-Meteo en live, scénario en replay).

L'agent détecte un dépassement de seuil et transmet les mesures brutes. Il ne calcule pas de gravité.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
from typing import Optional

from src.agents.base import BaseAgent
from src.schemas.events import (EntityRef, EventInfo, EventMeta, GraphNode, Location, NormalizedEvent, WeatherBlock)
from src.utils.http import http_get

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ["wind_speed_10m_max", "wind_gusts_10m_max", "precipitation_sum", "weather_code"]
# Seuils de détection (à calibrer) : tempête (vent moyen), rafales violentes, pluie diluvienne sur 24 h.
WIND_KMH, GUST_KMH, RAIN_MM = 75.0, 90.0, 60.0


def is_extreme(obs: dict) -> bool:
    return ((obs.get("gust_max_kmh") or 0) >= GUST_KMH or (obs.get("wind_max_kmh") or 0) >= WIND_KMH
            or (obs.get("precip_mm") or 0) >= RAIN_MM)


class WeatherAgent(BaseAgent):
    name = "weather"

    def __init__(self, hubs: list[GraphNode]):
        self.hubs = {h.id: h for h in hubs}

    async def collect_live(self, report: Optional[dict] = None, past_days: int = 2, forecast_days: int = 4, **kwargs) -> list[dict]:
        """Une seule requête Open-Meteo pour tous les hubs : mesures des derniers jours et prévisions."""
        report = {} if report is None else report
        hubs = list(self.hubs.values())
        if not hubs:
            report["open_meteo"] = {"status": "ok", "hubs": 0, "observations": 0}
            return []
        params = {"latitude": ",".join(f"{h.lat:.4f}" for h in hubs), "longitude": ",".join(f"{h.lon:.4f}" for h in hubs),
                  "daily": ",".join(DAILY), "past_days": past_days, "forecast_days": forecast_days, "timezone": "UTC"}
        info: dict = {}
        r = await asyncio.to_thread(http_get, OPEN_METEO_URL, params, None, None, {"Accept": "application/json"}, info)
        if r is None:
            report["open_meteo"] = {"status": "failed", "detail": f"HTTP {info['status']}" if info.get("status") else info.get("error") or "pas de réponse"}
            return []
        try:
            payload = r.json()
            payload = payload if isinstance(payload, list) else [payload]
            today, obs = date.today().isoformat(), []
            for hub, loc in zip(hubs, payload):
                daily = loc["daily"]
                for i, day in enumerate(daily["time"]):
                    obs.append({"node_id": hub.id, "date": day, "issued": min(day, today), "forecast": day > today,
                                "wind_max_kmh": daily["wind_speed_10m_max"][i], "gust_max_kmh": daily["wind_gusts_10m_max"][i],
                                "precip_mm": daily["precipitation_sum"][i], "weather_code": daily["weather_code"][i],
                                "provider": "open-meteo", "source_id": f"openmeteo:{hub.id}:{day}"})
        except (ValueError, KeyError, TypeError, IndexError) as e:
            report["open_meteo"] = {"status": "failed", "detail": f"réponse illisible ({type(e).__name__})"}
            return []
        report["open_meteo"] = {"status": "ok" if len(payload) == len(hubs) else "partial", "hubs": len(hubs), "observations": len(obs)}
        return obs

    async def collect_replay(self, scenario: dict, as_of: Optional[str] = None, report: Optional[dict] = None) -> list[dict]:
        """Relevés et prévisions du scénario connus le jour `as_of` (champ `issued`)."""
        report = {} if report is None else report
        obs = [dict(o, provider="replay", forecast=bool(as_of and o["date"] > as_of))
               for o in scenario.get("weather", []) if not as_of or o.get("issued", o["date"]) <= as_of]
        report["scenario"] = {"status": "ok", "observations": len(obs)}
        return obs

    async def extract_events(self, raw: list[dict], **kwargs) -> list[NormalizedEvent]:
        """Un événement par hub en dépassement : le pic sert de mesure, la première émission sert de date."""
        latest: dict[tuple[str, str], dict] = {}
        for o in raw:                                    # une prévision plus récente remplace l'ancienne pour le même jour
            key = (o["node_id"], o["date"])
            if key not in latest or o.get("issued", "") >= latest[key].get("issued", ""):
                latest[key] = o
        first_seen: dict[str, str] = {}
        for o in raw:
            if o["node_id"] in self.hubs and is_extreme(o):
                issued = o.get("issued") or o["date"]
                first_seen[o["node_id"]] = min(first_seen.get(o["node_id"], issued), issued)
        by_hub: dict[str, list[dict]] = defaultdict(list)
        for o in latest.values():
            if o["node_id"] in self.hubs and is_extreme(o):
                by_hub[o["node_id"]].append(o)

        events = []
        for node_id, rows in sorted(by_hub.items()):
            hub = self.hubs[node_id]
            peak = max(rows, key=lambda o: ((o.get("gust_max_kmh") or 0) / GUST_KMH, (o.get("precip_mm") or 0) / RAIN_MM))
            first = first_seen[node_id]
            kind = "Prévision" if peak.get("forecast") else "Relevé"
            label = (f"{kind} météo extrême à {hub.name} le {peak['date']} : rafales {peak.get('gust_max_kmh') or 0:.0f} km/h, "
                     f"pluie {peak.get('precip_mm') or 0:.0f} mm")
            events.append(NormalizedEvent(
                event=EventInfo(id=f"wx_{node_id}_{first}", type="meteo_extreme", label=label),
                date=first,
                location=Location(name=hub.place or hub.name, lat=hub.lat, lon=hub.lon),
                entities=[EntityRef(id=f"NODE:{node_id}", name=hub.name, role="touché")],
                weather=WeatherBlock(hub=node_id, date=peak["date"], wind_max_kmh=peak.get("wind_max_kmh"),
                                     gust_max_kmh=peak.get("gust_max_kmh"), precip_mm=peak.get("precip_mm"),
                                     weather_code=peak.get("weather_code"), forecast=bool(peak.get("forecast")),
                                     provider=peak.get("provider", "open-meteo"), source_id=peak["source_id"]),
                donnees_manquantes=["media", "finance"],
                # 0,9 pour un relevé, 0,7 pour une prévision : convention, à calibrer
                meta=EventMeta(agent="weather", confidence=0.7 if peak.get("forecast") else 0.9, extractor="seuils",
                               detail=f"seuils : rafales >= {GUST_KMH:.0f} km/h, vent >= {WIND_KMH:.0f} km/h ou pluie >= {RAIN_MM:.0f} mm")))
        return events
