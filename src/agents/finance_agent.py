"""Agent finance : tensions de marché, fournisseurs en difficulté, sanctions (yfinance + volet Finance en live).

Trois sources d'événements, toutes au format commun :
  1. instruments de la topologie (`market_watch`) : variation sur 5 séances et écart à l'historique (seuils fixes) ;
  2. signaux calibrés du volet Finance (`market_signals`) : Brent, gaz, gazole, GSCPI, change, métaux, prix de
     production... comparés au quantile de leurs variations sur 2010-2020 ; rang transmis au moteur ;
  3. fournisseurs réels suivis (`suppliers`) : chute de l'action, sanction (sur lui ou sa maison mère),
     procédure collective au BODACC.
L'agent détecte et transmet les chiffres. La gravité est calculée par le moteur de graphe.
"""
from __future__ import annotations

import asyncio
import statistics
from datetime import date
from typing import Optional

from src.agents.base import BaseAgent
from src.schemas.events import EntityRef, EventInfo, EventMeta, FinanceBlock, Location, NormalizedEvent

# Seuils de détection des instruments (à calibrer) : variation sur 5 séances, et écart à l'historique.
CHANGE_PCT, Z_SCORE, Z_MIN_CHANGE_PCT, MIN_HISTORY, MIN_SIGMA_PCT = 8.0, 2.5, 3.0, 20, 1.0
RECENT_DAYS = 10            # un signal calibré doit être en alerte sur sa dernière valeur, publiée il y a moins de...
RECENT_DAYS_MONTHLY = 45    # ... (séries mensuelles : publiées après la fin du mois)


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

    def __init__(self, market_watch: list[dict], node_names: Optional[dict[str, str]] = None,
                 signal_bindings: Optional[list[dict]] = None, supplier_bindings: Optional[list[dict]] = None):
        """signal_bindings : [{signal, exact: [nœuds], exposed: [nœuds]}] ; supplier_bindings : [{node, proxy}]."""
        self.watch = {w["id"]: w for w in market_watch}
        self.node_names = node_names or {}
        self.signal_bindings = {b["signal"]: b for b in (signal_bindings or [])}
        self.supplier_bindings = list(supplier_bindings or [])

    @staticmethod
    def _download(symbol: str) -> list[dict]:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=True)
        return [{"date": idx.strftime("%Y-%m-%d"), "close": float(close)}
                for idx, close in hist["Close"].dropna().items()]

    # ------------------------------------------------------------------ collecte
    async def collect_live(self, report: Optional[dict] = None, **kwargs) -> dict:
        """Instruments (six mois de cours), signaux calibrés et fiches des fournisseurs suivis."""
        report = {} if report is None else report
        series: dict = {}
        if self.watch:
            try:
                import yfinance  # noqa: F401
            except Exception:
                report["yfinance"] = {"status": "unavailable", "detail": "paquet yfinance non installé"}
            else:
                errors = {}
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
        if self.signal_bindings:
            series["_signals"] = await asyncio.to_thread(self._collect_signals, report)
        if self.supplier_bindings:
            series["_suppliers"] = await asyncio.to_thread(self._collect_suppliers, report)
        return series

    def _collect_signals(self, report: dict) -> list[dict]:
        from src.analytics.finance_indicators import episode_start, market_signals_status
        jour = date.today()
        situations, loaded, etat = market_signals_status(self.signal_bindings, jour)
        ok = sum(1 for s in etat.values() if s["status"] == "ok")
        missing_manual = [k for k, s in etat.items() if s["status"] == "unavailable"]
        failed = [k for k, s in etat.items() if s["status"] == "failed"]
        report["signaux_finance"] = {"status": "ok" if not failed else "partial" if ok else "failed",
                                     "signaux": len(self.signal_bindings), "lus": ok, "echecs": failed,
                                     "fichiers_manuels_absents": missing_manual}
        import pandas as pd
        for s in situations:
            s["debut_episode"] = episode_start(loaded[s["signal"]], s["signal"], pd.Timestamp(jour)) if s["en_alerte"] else None
        return situations

    def _collect_suppliers(self, report: dict) -> list[dict]:
        from src.analytics.finance_indicators import supplier_sheet
        from src.connectors import registries as reg
        listes, etat = reg.listes_sanctions()
        report["sanctions"] = {"status": "ok" if all(e["status"] == "ok" for e in etat.values())
                               else "partial" if any(e["status"] == "ok" for e in etat.values()) else "failed", **etat}
        fiches, errors = [], {}
        for b in self.supplier_bindings:
            try:
                fiche = supplier_sheet(b["proxy"], date.today(), listes)
                fiches.append({**fiche, "node": b["node"]})
            except Exception as e:                       # un fournisseur illisible ne bloque pas les autres
                errors[b["proxy"]] = f"{type(e).__name__} : {str(e)[:80]}"
        lues = [f for f in fiches if f.get("sources_lues")]       # une fiche sans aucune source lue ne prouve rien
        complete = all(not f.get("donnees_manquantes") for f in lues)
        report["fournisseurs"] = {"status": "ok" if len(lues) == len(self.supplier_bindings) and complete and not errors
                                  else "partial" if lues else "failed",
                                  "suivis": len(self.supplier_bindings), "fiches": len(lues), "echecs": errors}
        return lues

    async def collect_replay(self, scenario: dict, as_of: Optional[str] = None, report: Optional[dict] = None) -> dict:
        report = {} if report is None else report
        series: dict = {wid: [dict(p, provider="replay") for p in rows if not as_of or p["date"] <= as_of]
                        for wid, rows in scenario.get("finance", {}).items() if wid in self.watch}
        # Signaux calibrés rejoués : séries (date, valeur) du scénario, seuils calculés sur la série elle-même
        if scenario.get("finance_signals") and self.signal_bindings:
            series["_signals"] = self._replay_signals(scenario["finance_signals"], as_of)
        if scenario.get("finance_suppliers"):
            series["_suppliers"] = [f for f in scenario["finance_suppliers"] if not as_of or f.get("date", "") <= as_of]
        report["scenario"] = {"status": "ok", "instruments": len([k for k in series if not k.startswith("_")])}
        return series

    def _replay_signals(self, data: dict, as_of: Optional[str]) -> list[dict]:
        import pandas as pd
        from src.analytics.finance_indicators import episode_start, situation
        jour = pd.Timestamp(as_of or date.today())
        out = []
        for sig, rows in data.items():
            if sig not in self.signal_bindings:
                continue
            serie = pd.DataFrame(rows).assign(date=lambda d: pd.to_datetime(d["date"]))[["date", "valeur"]]
            sit = situation(sig, serie, jour)
            if sit:
                sit["source_id"] = f"replay:{sig}:{sit['date_valeur']}"
                sit["debut_episode"] = episode_start(serie, sig, jour) if sit["en_alerte"] else None
                out.append(sit)
        return out

    # ------------------------------------------------------------------ extraction
    async def extract_events(self, raw: dict, **kwargs) -> list[NormalizedEvent]:
        events = self._instrument_events({k: v for k, v in raw.items() if not k.startswith("_")})
        events += self._signal_events(raw.get("_signals") or [])
        events += self._supplier_events(raw.get("_suppliers") or [])
        return events

    def _instrument_events(self, raw: dict[str, list[dict]]) -> list[NormalizedEvent]:
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

    def _signal_events(self, situations: list[dict]) -> list[NormalizedEvent]:
        """Un événement par signal calibré en alerte sur sa dernière valeur connue."""
        events = []
        for s in sorted(situations, key=lambda x: x["signal"]):
            b = self.signal_bindings.get(s["signal"])
            if not b or not s.get("en_alerte"):
                continue
            mensuel = s.get("horizon", 20) <= 3 or s["mesure"] == "niveau"
            age = (date.today() - date.fromisoformat(s["date_valeur"])).days
            if not s["source_id"].startswith("replay:") and age > (RECENT_DAYS_MONTHLY if mensuel else RECENT_DAYS):
                continue
            ents = [EntityRef(id=f"NODE:{n}", name=self.node_names.get(n, n), role="touché") for n in b.get("exact", [])]
            ents += [EntityRef(id=f"NODE:{n}", name=self.node_names.get(n, n), role="exposé")
                     for n in b.get("exposed", []) if n not in b.get("exact", [])]
            if not ents:
                continue
            unit = "%" if s["mesure"] == "variation_%" else s.get("unite", "")
            mesure = (f"{s['indicateur']:+.1f} % en {s['horizon']} obs." if s["mesure"] == "variation_%"
                      else f"niveau {s['indicateur']:.2f} {s.get('unite', '')}")
            label = f"{s['nom']} : {mesure} (seuil {s['seuil']:+.1f}{'' if unit != '%' else ' %'}) — {s['impact']}"
            first = s.get("debut_episode") or s["date_valeur"]
            provider = "replay" if s["source_id"].startswith("replay:") else str(s.get("source", "")).split()[0].lower() or "finance"
            events.append(NormalizedEvent(
                event=EventInfo(id=f"fin_{s['signal']}_{first}", type="tension_marche", label=label),
                date=first, location=Location(), entities=ents,
                finance=FinanceBlock(instrument=s["signal"], name=s["nom"], date=s["date_valeur"], close=s.get("valeur_brute"),
                                     provider=provider, source_id=s["source_id"], kind="signal", family=s["famille"],
                                     indicator=s["indicateur"], measure=s["mesure"], horizon=s["horizon"],
                                     threshold=s["seuil"], rank=s.get("rang"), unit=s.get("unite"), impact=s["impact"]),
                donnees_manquantes=["media", "weather", "location"],
                meta=EventMeta(agent="finance", confidence=0.8, extractor="seuils_calibres",
                               detail=f"seuil = quantile {'haut' if s['sens'] == 'haut' else 'bas'} des variations 2010-2020")))
        return events

    def _supplier_events(self, fiches: list[dict]) -> list[NormalizedEvent]:
        """Fiches fournisseurs : chute de l'action, sanction, procédure collective -> un événement chacun."""
        events = []
        for f in fiches:
            nid = f["node"]
            ent = [EntityRef(id=f"NODE:{nid}", name=self.node_names.get(nid, nid), role="touché")]
            day = f.get("date") or date.today().isoformat()
            b = f.get("bourse") or {}
            if b.get("en_alerte"):
                events.append(NormalizedEvent(
                    event=EventInfo(id=f"fin_bourse_{f['cle']}_{b['date_valeur']}", type="difficulte_financiere",
                                    label=f"{f['fournisseur']} : action {b['variation_20j_%']:+.0f} % en 20 séances (seuil {b['seuil']:+.0f} %)"),
                    date=b["date_valeur"], location=Location(name=f.get("pays")), entities=ent,
                    finance=FinanceBlock(instrument=f"bourse_{f['cle']}", name=f"Bourse : {f['fournisseur']}", date=b["date_valeur"],
                                         close=b.get("cours"), provider="yfinance", source_id=b.get("source_id") or f"yfinance:{f['cle']}:{b['date_valeur']}",
                                         kind="bourse", family="fournisseurs", indicator=b["variation_20j_%"], measure="variation_%",
                                         horizon=20, threshold=b.get("seuil"), rank=b.get("rang"), unit="%",
                                         impact=f"{f['produit']} : fournisseur en difficulté, faillite possible"),
                    donnees_manquantes=["media", "weather"],
                    meta=EventMeta(agent="finance", confidence=0.75, extractor="seuils_calibres", detail="chute de l'action")))
            if f.get("sanctions"):
                first = min((s.get("date_inscription") or day) for s in f["sanctions"])
                roles = ", ".join(sorted({s["role"] for s in f["sanctions"]}))
                listes = ", ".join(sorted({s["liste"] for s in f["sanctions"]}))
                events.append(NormalizedEvent(
                    event=EventInfo(id=f"fin_sanction_{f['cle']}_{first}", type="sanction",
                                    label=f"{f['fournisseur']} : sanction ({roles}) — {listes}"),
                    date=first, location=Location(name=f.get("pays")), entities=ent,
                    finance=FinanceBlock(instrument=f"sanction_{f['cle']}", name=f"Sanctions : {f['fournisseur']}", date=day,
                                         provider="listes de sanctions", source_id=f["sanctions"][0]["source_id"] or f"sanctions:{f['cle']}",
                                         kind="sanction", family="sanctions et propriété",
                                         detail="; ".join(f"{s['entite']} sur {s['liste']} ({s['nom_sur_liste']})" for s in f["sanctions"][:4]),
                                         impact="Ruptures d'approvisionnement, paiements bloqués"),
                    donnees_manquantes=["media", "weather"],
                    meta=EventMeta(agent="finance", confidence=0.9, extractor="listes", detail=f"correspondance de nom sur {listes}")))
            if f.get("procedures_collectives"):
                last = max(f["procedures_collectives"], key=lambda p: p["date"])
                events.append(NormalizedEvent(
                    event=EventInfo(id=f"fin_bodacc_{f['cle']}_{last['date']}", type="faillite",
                                    label=f"{f['fournisseur']} : procédure collective publiée au BODACC le {last['date']} ({last.get('type') or ''})"),
                    date=last["date"], location=Location(name=f.get("pays")), entities=ent,
                    finance=FinanceBlock(instrument=f"bodacc_{f['cle']}", name=f"BODACC : {f['fournisseur']}", date=last["date"],
                                         provider="BODACC", source_id=last.get("source_id") or f"bodacc:{f['cle']}",
                                         kind="procedure", family="santé des fournisseurs", detail=last.get("detail"),
                                         impact="Fournisseur en sauvegarde, redressement ou liquidation"),
                    donnees_manquantes=["media", "weather"],
                    meta=EventMeta(agent="finance", confidence=0.95, extractor="bodacc", detail="annonce officielle")))
        return events
