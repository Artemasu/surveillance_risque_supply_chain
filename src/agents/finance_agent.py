"""Agent finance : décrochages de prix sur les matières premières et le fret (yfinance en live, scénario en replay).

L'agent détecte une variation anormale et transmet les chiffres bruts. Il ne calcule pas de gravité.
"""
from __future__ import annotations

import asyncio
import statistics
from typing import Optional

from src.agents.base import BaseAgent
from src.schemas.events import EntityRef, EventInfo, EventMeta, FinanceBlock, Location, NormalizedEvent

# Seuils de détection (à calibrer) : variation sur 5 séances, et écart à l'historique de l'instrument.
CHANGE_PCT, Z_SCORE, Z_MIN_CHANGE_PCT, MIN_HISTORY, MIN_SIGMA_PCT = 8.0, 2.5, 3.0, 20, 1.0


def five_day_changes(closes: list[float]) -> list[Optional[float]]:
    return [None if i < 5 or not closes[i - 5] else 100.0 * (closes[i] / closes[i - 5] - 1.0) for i in range(len(closes))]


def zscore_at(changes: list[Optional[float]], i: int) -> Optional[float]:
    """Écart de la variation du jour i à l'historique qui précède (hors les 5 dernières séances, qui se recouvrent)."""
    hist = [c for c in changes[:max(0, i - 5)] if c is not None]
    if len(hist) < MIN_HISTORY or changes[i] is None:
        return None
    sd = max(statistics.pstdev(hist), MIN_SIGMA_PCT)     # plancher : un historique trop calme ne doit pas gonfler l'écart
    return (changes[i] - statistics.fmean(hist)) / sd


def is_anomaly(change: Optional[float], z: Optional[float]) -> bool:
    if change is None:
        return False
    return abs(change) >= CHANGE_PCT or (z is not None and abs(z) >= Z_SCORE and abs(change) >= Z_MIN_CHANGE_PCT)


class FinanceAgent(BaseAgent):
    name = "finance"

    def __init__(self, market_watch: list[dict], node_names: Optional[dict[str, str]] = None):
        self.watch = {w["id"]: w for w in market_watch}
        self.node_names = node_names or {}

    @staticmethod
    def _download(symbol: str) -> list[dict]:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=True)
        return [{"date": idx.strftime("%Y-%m-%d"), "close": float(close)}
                for idx, close in hist["Close"].dropna().items()]

    async def collect_live(self, report: Optional[dict] = None, **kwargs) -> dict[str, list[dict]]:
        """Six mois de cours quotidiens par instrument (symbole `yf` de la topologie)."""
        report = {} if report is None else report
        try:
            import yfinance  # noqa: F401
        except Exception:
            report["yfinance"] = {"status": "unavailable", "detail": "paquet yfinance non installé"}
            return {}
        series, errors = {}, {}
        for wid, w in self.watch.items():
            try:
                rows = await asyncio.to_thread(self._download, w["yf"])
                if len(rows) < 10:
                    raise ValueError("série vide ou trop courte")
                series[wid] = rows
            except Exception as e:
                errors[wid] = f"{type(e).__name__} : {str(e)[:80]}"
        report["yfinance"] = {"status": "ok" if not errors else "partial" if series else "failed",
                              "instruments": len(self.watch), "reponses": len(series), "echecs": errors}
        return series

    async def collect_replay(self, scenario: dict, as_of: Optional[str] = None, report: Optional[dict] = None) -> dict[str, list[dict]]:
        report = {} if report is None else report
        series = {wid: [dict(p, provider="replay") for p in rows if not as_of or p["date"] <= as_of]
                  for wid, rows in scenario.get("finance", {}).items() if wid in self.watch}
        report["scenario"] = {"status": "ok", "instruments": len(series)}
        return series

    async def extract_events(self, raw: dict[str, list[dict]], **kwargs) -> list[NormalizedEvent]:
        """Un événement par instrument en anomalie sur l'une des 3 dernières séances ; date = début de l'épisode."""
        events = []
        for wid, rows in sorted(raw.items()):
            watch = self.watch.get(wid)
            if not watch or len(rows) < 6:
                continue
            closes = [float(p["close"]) for p in rows]
            changes = five_day_changes(closes)
            flags = [is_anomaly(changes[i], zscore_at(changes, i)) for i in range(len(rows))]
            recent = [i for i in range(max(0, len(rows) - 3), len(rows)) if flags[i]]
            if not recent:
                continue
            last = recent[-1]
            first = last
            while first > 0 and flags[first - 1]:
                first -= 1
            change, z = changes[last], zscore_at(changes, last)
            provider = "replay" if rows[last].get("provider") == "replay" else watch.get("provider", "yfinance")
            label = f"{watch['name']} : {change:+.1f} % en 5 séances" + ("" if z is None else " (écart à l'historique : plus de 10 sigma)" if abs(z) > 10 else f" (écart à l'historique : {z:+.1f} sigma)")
            events.append(NormalizedEvent(
                event=EventInfo(id=f"fin_{wid}_{rows[first]['date']}", type="tension_marche", label=label),
                date=rows[first]["date"], location=Location(),
                entities=[EntityRef(id=f"NODE:{nid}", name=self.node_names.get(nid, nid), role="touché")
                          for nid in watch.get("nodes", [])],
                finance=FinanceBlock(instrument=wid, name=watch["name"], date=rows[last]["date"], close=round(closes[last], 4),
                                     change_5d_pct=round(change, 2), zscore=round(z, 2) if z is not None else None,
                                     provider=provider, source_id=f"{provider}:{wid}:{rows[last]['date']}"),
                donnees_manquantes=["media", "weather", "location"],
                meta=EventMeta(agent="finance", confidence=0.8, extractor="seuils",      # 0,8 : convention
                               detail=f"seuils : |variation 5 j| >= {CHANGE_PCT:.0f} % ou écart >= {Z_SCORE} sigma")))
        return events
