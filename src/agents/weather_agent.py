"""Agent météo : conditions extrêmes sur les hubs du graphe (Open-Meteo en live, scénario en replay).

Deux régimes, choisis hub par hub :
  - seuils calibrés (volet Météo) : si le hub a été calibré (`python -m src.jobs calibrate-meteo`), chaque
    indicateur (pluie 3 j / 90 j, rafales, neige, chaleur, gel, crue, basses eaux) est comparé au quantile 99 %
    (ou 1 %) du site sur 2010-2020, et l'événement porte son rang ; prévisions jusqu'à 16 jours ;
  - seuils fixes de repli (rafales >= 90 km/h, vent >= 75 km/h, pluie >= 60 mm) : hubs non calibrés, replay.
L'agent détecte un dépassement et transmet les mesures. La gravité est calculée par le moteur de graphe.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd

from src.agents.base import BaseAgent
from src.analytics.weather_indicators import (INDICATEURS, SiteCalibration, add_indicators, alerts_of, evaluate_site)
from src.schemas.events import (EntityRef, EventInfo, EventMeta, GraphNode, Location, NormalizedEvent, WeatherBlock)
from src.utils.http import http_get

log = logging.getLogger("supplychain.agents")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
DAILY = ["wind_speed_10m_max", "wind_gusts_10m_max", "precipitation_sum", "weather_code",
         "temperature_2m_max", "temperature_2m_min", "snowfall_sum"]
# Seuils fixes de repli (hubs non calibrés) : tempête (vent moyen), rafales violentes, pluie diluvienne sur 24 h.
WIND_KMH, GUST_KMH, RAIN_MM = 75.0, 90.0, 60.0
FORECAST_DAYS = 16


def is_extreme(obs: dict) -> bool:
    return ((obs.get("gust_max_kmh") or 0) >= GUST_KMH or (obs.get("wind_max_kmh") or 0) >= WIND_KMH
            or (obs.get("precip_mm") or 0) >= RAIN_MM)


def _num(x) -> Optional[float]:
    try:
        return None if x is None or pd.isna(x) else round(float(x), 2)
    except (TypeError, ValueError):
        return None


class WeatherAgent(BaseAgent):
    name = "weather"

    def __init__(self, hubs: list[GraphNode], site_config: Optional[dict[str, dict]] = None,
                 calibrations: Optional[Callable[[], dict[str, SiteCalibration]]] = None):
        self.hubs = {h.id: h for h in hubs}
        self.site_config = site_config or {}
        self._calibrations_loader = calibrations
        self.calibrations: dict[str, SiteCalibration] = {}

    def _load_calibrations(self) -> None:
        self.calibrations = {}
        if self._calibrations_loader is None:
            return
        try:
            self.calibrations = {k: v for k, v in (self._calibrations_loader() or {}).items() if k in self.hubs}
        except Exception as e:                      # base absente ou illisible : repli sur les seuils fixes
            log.warning("calibrations météo indisponibles : %s", e)

    # ------------------------------------------------------------------ collecte
    async def collect_live(self, report: Optional[dict] = None, **kwargs) -> list[dict]:
        """Une requête Open-Meteo pour tous les hubs : derniers jours et 16 jours de prévision (+ débit GloFAS)."""
        report = {} if report is None else report
        self._load_calibrations()
        hubs = list(self.hubs.values())
        if not hubs:
            report["open_meteo"] = {"status": "ok", "hubs": 0, "observations": 0}
            return []
        long_window = any("pluie_90j" in c.indicators for c in self.calibrations.values())
        past_days = 92 if long_window else 3
        params = {"latitude": ",".join(f"{h.lat:.4f}" for h in hubs), "longitude": ",".join(f"{h.lon:.4f}" for h in hubs),
                  "daily": ",".join(DAILY), "past_days": past_days, "forecast_days": FORECAST_DAYS, "timezone": "UTC"}
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
                col = lambda k, i: (daily.get(k) or [None] * len(daily["time"]))[i]  # noqa: E731
                for i, day in enumerate(daily["time"]):
                    obs.append({"node_id": hub.id, "date": day, "issued": min(day, today), "forecast": day > today,
                                "wind_max_kmh": col("wind_speed_10m_max", i), "gust_max_kmh": col("wind_gusts_10m_max", i),
                                "precip_mm": col("precipitation_sum", i), "weather_code": col("weather_code", i),
                                "temp_max_c": col("temperature_2m_max", i), "temp_min_c": col("temperature_2m_min", i),
                                "snow_cm": col("snowfall_sum", i), "provider": "open-meteo",
                                "source_id": f"openmeteo:{hub.id}:{day}"})
        except (ValueError, KeyError, TypeError, IndexError) as e:
            report["open_meteo"] = {"status": "failed", "detail": f"réponse illisible ({type(e).__name__})"}
            return []
        report["open_meteo"] = {"status": "ok" if len(payload) == len(hubs) else "partial", "hubs": len(hubs),
                                "observations": len(obs), "calibres": len(self.calibrations),
                                "seuils": "calibrés par site" if len(self.calibrations) == len(hubs) else
                                "calibrés pour une partie des hubs, fixes pour les autres" if self.calibrations else
                                "fixes (aucune calibration : python -m src.jobs calibrate-meteo)"}
        await self._collect_discharge(obs, report)
        return obs

    async def _collect_discharge(self, obs: list[dict], report: dict) -> None:
        """Débit des rivières pour les hubs fluviaux calibrés (point GloFAS mémorisé à la calibration)."""
        rivers = {nid: c for nid, c in self.calibrations.items() if {"crue", "basses_eaux"} & set(c.indicators)}
        if not rivers:
            return
        ok, by_key = 0, {(o["node_id"], o["date"]): o for o in obs}
        for nid in rivers:
            point = rivers[nid].river or self.site_config.get(nid, {})
            lat, lon = point.get("lat_debit") or self.hubs[nid].lat, point.get("lon_debit") or self.hubs[nid].lon
            params = {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "daily": "river_discharge",
                      "past_days": 10, "forecast_days": FORECAST_DAYS}
            r = await asyncio.to_thread(http_get, FLOOD_URL, params, None, None, {"Accept": "application/json"}, {})
            try:
                daily = r.json()["daily"] if r is not None else None
            except (ValueError, KeyError):
                daily = None
            if not daily:
                continue
            ok += 1
            for day, q in zip(daily["time"], daily["river_discharge"]):
                if (nid, day) in by_key:
                    by_key[(nid, day)]["discharge_m3s"] = q
        report["glofas"] = {"status": "ok" if ok == len(rivers) else "partial" if ok else "failed",
                            "hubs_fluviaux": len(rivers), "reponses": ok}

    async def collect_replay(self, scenario: dict, as_of: Optional[str] = None, report: Optional[dict] = None) -> list[dict]:
        """Relevés et prévisions du scénario connus le jour `as_of` (champ `issued`). Seuils fixes."""
        report = {} if report is None else report
        self.calibrations = {}
        obs = [dict(o, provider="replay", forecast=bool(as_of and o["date"] > as_of))
               for o in scenario.get("weather", []) if not as_of or o.get("issued", o["date"]) <= as_of]
        report["scenario"] = {"status": "ok", "observations": len(obs)}
        return obs

    # ------------------------------------------------------------------ extraction
    async def extract_events(self, raw: list[dict], **kwargs) -> list[NormalizedEvent]:
        latest: dict[tuple[str, str], dict] = {}
        for o in raw:                                    # une prévision plus récente remplace l'ancienne pour le même jour
            key = (o["node_id"], o["date"])
            if key not in latest or o.get("issued", "") >= latest[key].get("issued", ""):
                latest[key] = o
        by_node: dict[str, list[dict]] = defaultdict(list)
        for o in latest.values():
            if o["node_id"] in self.hubs:
                by_node[o["node_id"]].append(o)
        events = []
        for node_id in sorted(by_node):
            cal = self.calibrations.get(node_id)
            ev = (self._calibrated_event(node_id, by_node[node_id], raw, cal) if cal
                  else self._fixed_event(node_id, by_node[node_id], raw))
            if ev:
                events.append(ev)
        return events

    def _fixed_event(self, node_id: str, rows: list[dict], raw: list[dict]) -> Optional[NormalizedEvent]:
        """Seuils fixes : le pic sert de mesure, la première émission sert de date."""
        extreme = [o for o in rows if is_extreme(o)]
        if not extreme:
            return None
        hub = self.hubs[node_id]
        first = min((o.get("issued") or o["date"]) for o in raw if o["node_id"] == node_id and is_extreme(o))
        peak = max(extreme, key=lambda o: ((o.get("gust_max_kmh") or 0) / GUST_KMH, (o.get("precip_mm") or 0) / RAIN_MM))
        kind = "Prévision" if peak.get("forecast") else "Relevé"
        label = (f"{kind} météo extrême à {hub.name} le {peak['date']} : rafales {peak.get('gust_max_kmh') or 0:.0f} km/h, "
                 f"pluie {peak.get('precip_mm') or 0:.0f} mm")
        return NormalizedEvent(
            event=EventInfo(id=f"wx_{node_id}_{first}", type="meteo_extreme", label=label),
            date=first, location=Location(name=hub.place or hub.name, lat=hub.lat, lon=hub.lon),
            entities=[EntityRef(id=f"NODE:{node_id}", name=hub.name, role="touché")],
            weather=WeatherBlock(hub=node_id, date=peak["date"], wind_max_kmh=peak.get("wind_max_kmh"),
                                 gust_max_kmh=peak.get("gust_max_kmh"), precip_mm=peak.get("precip_mm"),
                                 weather_code=peak.get("weather_code"), forecast=bool(peak.get("forecast")),
                                 provider=peak.get("provider", "open-meteo"), source_id=peak["source_id"],
                                 temp_max_c=_num(peak.get("temp_max_c")), temp_min_c=_num(peak.get("temp_min_c")),
                                 snow_cm=_num(peak.get("snow_cm"))),
            donnees_manquantes=["media", "finance"],
            # 0,9 pour un relevé, 0,7 pour une prévision : convention, à calibrer
            meta=EventMeta(agent="weather", confidence=0.7 if peak.get("forecast") else 0.9, extractor="seuils",
                           detail=f"seuils fixes : rafales >= {GUST_KMH:.0f} km/h, vent >= {WIND_KMH:.0f} km/h ou pluie >= {RAIN_MM:.0f} mm"))

    def _calibrated_event(self, node_id: str, rows: list[dict], raw: list[dict], cal: SiteCalibration) -> Optional[NormalizedEvent]:
        """Seuils propres au site : un événement par hub, au jour le plus extrême parmi les jours en alerte."""
        df = pd.DataFrame(sorted(rows, key=lambda o: o["date"]))
        df["date"] = pd.to_datetime(df["date"])
        df = df.rename(columns={"precip_mm": "precipitation_sum", "gust_max_kmh": "wind_gusts_10m_max",
                                "temp_max_c": "temperature_2m_max", "temp_min_c": "temperature_2m_min",
                                "snow_cm": "snowfall_sum", "discharge_m3s": "river_discharge"})
        for col in ("precipitation_sum", "wind_gusts_10m_max", "temperature_2m_max", "temperature_2m_min", "snowfall_sum",
                    "river_discharge"):
            df[col] = pd.to_numeric(df[col], errors="coerce") if col in df else float("nan")
        ev = evaluate_site(add_indicators(df), cal)
        horizon_start = pd.Timestamp(date.today() - timedelta(days=2))
        alert_days = ev[ev["alerte_meteo"].astype(bool) & (ev["date"] >= horizon_start)]
        if alert_days.empty:
            return None
        best_idx, best_alerts, best_rank = None, [], -1.0
        for idx, day in alert_days.iterrows():
            al = alerts_of(day, cal)
            top = max((a["rank"] or 0) for a in al) if al else 0
            if al and top > best_rank:
                best_idx, best_alerts, best_rank = idx, al, top
        if best_idx is None:
            return None
        peak_row, peak = ev.loc[best_idx], best_alerts[0]
        peak_day = peak_row["date"].date().isoformat()
        src = next(o for o in rows if o["date"] == peak_day)
        first_alert = alert_days["date"].min().date().isoformat()
        first = min(first_alert, min(o.get("issued") or o["date"] for o in rows if o["date"] >= first_alert))
        hub = self.hubs[node_id]
        forecast = bool(src.get("forecast"))
        ahead = (date.fromisoformat(peak_day) - date.today()).days
        confidence = 0.9 if not forecast else 0.7 if ahead <= 5 else 0.55        # convention : la prévision s'use
        kind = f"Prévision J+{ahead}" if forecast else "Relevé"
        others = ", ".join(a["label"] for a in best_alerts[1:])
        label = (f"{kind} à {hub.name} le {peak_day} : {peak['label']} {peak['value']} {peak['unit']} "
                 f"(seuil du site {peak['threshold']:.0f} {peak['unit']}, {peak['level']})" + (f" ; aussi {others}" if others else ""))
        score = peak_row.get("score_meteo")
        return NormalizedEvent(
            event=EventInfo(id=f"wx_{node_id}_{first}", type="meteo_extreme", label=label),
            date=first, location=Location(name=hub.place or hub.name, lat=hub.lat, lon=hub.lon),
            entities=[EntityRef(id=f"NODE:{node_id}", name=hub.name, role="touché")],
            weather=WeatherBlock(hub=node_id, date=peak_day, wind_max_kmh=_num(src.get("wind_max_kmh")),
                                 gust_max_kmh=_num(src.get("gust_max_kmh")), precip_mm=_num(src.get("precip_mm")),
                                 weather_code=src.get("weather_code"), forecast=forecast,
                                 provider=src.get("provider", "open-meteo"), source_id=src["source_id"],
                                 indicator=peak["indicator"], value=peak["value"], threshold=peak["threshold"],
                                 unit=peak["unit"], rank=peak["rank"], level=peak["level"], risk=peak["risk"],
                                 score=None if score is None or pd.isna(score) else round(float(score), 4),
                                 indicators=best_alerts, temp_max_c=_num(src.get("temp_max_c")),
                                 temp_min_c=_num(src.get("temp_min_c")), snow_cm=_num(src.get("snow_cm")),
                                 discharge_m3s=_num(src.get("discharge_m3s"))),
            donnees_manquantes=["media", "finance"],
            meta=EventMeta(agent="weather", confidence=confidence, extractor="seuils_calibres",
                           detail=f"seuils propres au site ({cal.period}) : " + ", ".join(
                               f"{i} {c.seuil:g} {INDICATEURS.loc[i].unite}" for i, c in cal.indicators.items())))
