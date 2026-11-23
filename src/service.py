"""Orchestrateur : lance les trois agents, alimente le moteur de graphe, garde l'état pour l'API et l'interface."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from src.agents.finance_agent import FinanceAgent
from src.agents.media_agent import MediaAgent
from src.agents.weather_agent import WeatherAgent
from src.config import settings
from src.copilot.assistant import CopilotAssistant
from src.graph.ontology_engine import CORRELATION_WINDOW_DAYS, OntologyEngine
from src.schemas.events import (AgentResult, AgentSummary, ChatRequest, ChatResponse, NormalizedEvent,
                                PipelineRunRequest, PipelineRunResult, TimelinePoint)
from src.storage import db

log = logging.getLogger("supplychain.service")


class ScenarioNotFound(Exception):
    pass


class SupplyChainService:
    def __init__(self, topology_path: Optional[Path] = None, scenario_dir: Optional[Path] = None):
        self.scenario_dir = Path(scenario_dir or settings.scenario_dir)
        self.data_dir = self.scenario_dir.parent
        self.default_topology = Path(topology_path or settings.topology_path).resolve()
        self.agent_results: dict[str, AgentResult] = {}
        self.last_run: Optional[PipelineRunResult] = None
        self._lock = asyncio.Lock()
        self.topology_path: Optional[Path] = None
        self.use_topology(self.default_topology)

    # ------------------------------------------------------------------ topologie
    def use_topology(self, path: Path) -> bool:
        """Charge une topologie et reconstruit moteur, agents et copilot. Renvoie True si elle a changé."""
        path = Path(path).resolve()
        if path == self.topology_path:
            return False
        engine = OntologyEngine.from_yaml(path)              # lève une erreur claire si la topologie est invalide
        self.engine, self.topology_path = engine, path
        names = {n.id: n.name for n in engine.nodes.values()}
        site_config = engine.weather_site_config()
        self.agents = {
            "media": MediaAgent(engine.company_referential(), engine.place_referential(), engine.soft_referential(), names),
            "weather": WeatherAgent(engine.weather_hubs(), site_config, calibrations=lambda: self._weather_calibrations(site_config)),
            "finance": FinanceAgent(engine.market_watch, names, signal_bindings=self.signal_bindings(engine),
                                    supplier_bindings=engine.supplier_bindings),
        }
        self.assistant = CopilotAssistant(engine)
        self.agent_results = {}
        if settings.persist_runs:
            try:
                db.save_bindings(self.topology_key(), engine)
            except Exception as e:                      # base indisponible : l'analyse continue sans historique
                log.warning("référentiel de liaisons non enregistré : %s", e)
        return True

    @staticmethod
    def signal_bindings(engine: OntologyEngine) -> list[dict]:
        """Signaux calibrés -> nœuds en lien exact, et nœuds exposés (nommés ou par catégorie d'intrant)."""
        out = []
        for m in engine.market_signals:
            exact = list(m.get("nodes", []))
            exposed = [n for n in [*m.get("exposed", []), *engine.nodes_for_inputs(m.get("inputs", []))] if n not in exact]
            out.append({"signal": m["signal"], "exact": exact, "exposed": list(dict.fromkeys(exposed))})
        return out

    @staticmethod
    def _weather_calibrations(site_config: dict[str, dict]) -> dict:
        """Calibrations de la base, indexées par nœud (plusieurs nœuds peuvent partager un site calibré)."""
        cals = db.load_weather_calibrations({c["site"] for c in site_config.values()})
        return {nid: cals[c["site"]] for nid, c in site_config.items() if c["site"] in cals}

    def topology_key(self) -> str:
        return self.topology_ref() or "topology.yaml"

    def topology_ref(self, path: Optional[Path] = None) -> Optional[str]:
        """Référence d'une topologie relative à data/ (None pour la topologie par défaut)."""
        path = Path(path or self.topology_path).resolve()
        if path == self.default_topology:
            return None
        try:
            return path.relative_to(self.data_dir.resolve()).as_posix()
        except ValueError:
            return str(path)

    def list_topologies(self) -> list[dict]:
        """Topologies disponibles : la topologie par défaut, data/topology*.yaml et data/topologies/*.yaml."""
        import yaml
        paths = [self.default_topology, *sorted(self.data_dir.glob("topology*.y*ml")),
                 *sorted((self.data_dir / "topologies").glob("*.y*ml"))]
        out, seen = [], set()
        for path in paths:
            path = path.resolve()
            if path in seen or not path.exists():
                continue
            seen.add(path)
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                meta = raw.get("meta", {})
                out.append({"ref": self.topology_ref(path), "file": path.name, "name": meta.get("name") or path.stem,
                            "company": meta.get("company"), "sector": meta.get("sector"),
                            "nodes": len(raw.get("nodes", [])), "default": path == self.default_topology,
                            "active": path == self.topology_path})
            except Exception:                            # fichier illisible : il n'est pas proposé
                continue
        return out

    def resolve_topology(self, ref: Optional[str]) -> Path:
        """Chemin de la topologie d'un scénario (`meta.topology`, relatif à data/). Absent : topologie par défaut."""
        if not ref:
            return self.default_topology
        path = (self.data_dir / ref).resolve()
        if self.data_dir.resolve() not in path.parents or path.suffix not in (".yaml", ".yml") or not path.exists():
            raise ScenarioNotFound(f"topologie du scénario introuvable ou hors de data/ : {ref!r}")
        return path

    # ------------------------------------------------------------------ scénarios
    def list_scenarios(self) -> list[dict]:
        out = []
        for path in sorted(self.scenario_dir.glob("*.json")):
            try:
                meta = json.loads(path.read_text(encoding="utf-8")).get("meta", {})
            except (OSError, ValueError):
                continue
            out.append({"id": path.stem, "title": meta.get("title", path.stem), "fictional": bool(meta.get("fictional")),
                        "start_date": meta.get("start_date"), "days": meta.get("days"),
                        "topology": meta.get("topology") or "topology.yaml",
                        "notice": meta.get("notice", ""), "storyline": meta.get("storyline", {})})
        return out

    def load_scenario(self, scenario_id: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", scenario_id or ""):
            raise ScenarioNotFound(f"identifiant de scénario invalide : {scenario_id!r}")
        path = self.scenario_dir / f"{scenario_id}.json"
        if not path.exists():
            raise ScenarioNotFound(f"scénario introuvable : {scenario_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ pipeline
    def _cross_fill(self, events: list[NormalizedEvent]) -> list[NormalizedEvent]:
        """Validation croisée : un événement médias reçoit les blocs météo et finance observés sur le même nœud
        à moins de quelques jours. Les blocs remplis sortent de `donnees_manquantes`."""
        links = {e.event.id: {n for n, w in self.engine.link_weights(e).items() if w >= 1.0} for e in events}   # liens exacts

        def near(a: NormalizedEvent, b: NormalizedEvent) -> bool:
            if not (a.date and b.date) or not (links[a.event.id] & links[b.event.id]):
                return False
            return abs((date.fromisoformat(a.date) - date.fromisoformat(b.date)).days) <= CORRELATION_WINDOW_DAYS

        out = []
        for ev in events:
            if ev.meta.agent == "media":
                wx = next((o.weather for o in events if o.weather and near(ev, o)), None)
                fin = next((o.finance for o in events if o.finance and near(ev, o)), None)
                missing = [m for m in ev.donnees_manquantes if not ((m == "weather" and wx) or (m == "finance" and fin))]
                ev = ev.model_copy(update={"weather": wx, "finance": fin, "donnees_manquantes": missing})
            out.append(ev)
        return out

    async def run_pipeline(self, req: PipelineRunRequest) -> PipelineRunResult:
        """Collecte par les trois agents en parallèle, puis corrélation, propagation et alertes."""
        async with self._lock:
            scenario, day, days_total, fictional = None, None, None, False
            if req.mode == "replay":
                scenario_id = req.scenario or next((s["id"] for s in self.list_scenarios()), None)
                if scenario_id is None:
                    raise ScenarioNotFound("aucun scénario de replay disponible")
                scenario = self.load_scenario(scenario_id)
                meta = scenario.get("meta", {})
                changed = self.use_topology(self.resolve_topology(meta.get("topology")))  # chaque scénario a sa chaîne
                days_total = int(meta.get("days", 1))
                day = min(req.day or days_total, days_total)
                start = date.fromisoformat(meta["start_date"])
                as_of, fictional = (start + timedelta(days=day - 1)).isoformat(), bool(meta.get("fictional"))
                first_day = start
            else:
                scenario_id = None
                changed = self.use_topology(self.resolve_topology(req.topology))  # live : topologie choisie, sinon défaut
                as_of = date.today().isoformat()
                first_day = date.today() - timedelta(days=settings.lookback_days - 1)

            async def collect(day_iso: Optional[str], use_llm: Optional[bool]) -> list[AgentResult]:
                return list(await asyncio.gather(*[
                    agent.run(mode=req.mode, scenario=scenario, as_of=day_iso, use_llm=use_llm)
                    for agent in self.agents.values()]))

            # Replay : les jours précédents sont rejoués un par un avec ce qui était connu ce jour-là (pas de fuite
            # du futur dans la courbe). La baseline suffit pour la courbe ; le LLM ne sert que pour le jour affiché.
            timeline: list[TimelinePoint] = []
            if req.mode == "replay":
                for k in range(1, day):
                    past = (start + timedelta(days=k - 1)).isoformat()
                    past_events = self._cross_fill([e for r in await collect(past, False) if r.status == "success" for e in r.events])
                    timeline.append(TimelinePoint(date=past, n_events=len(past_events),
                                                  global_risk_index=self.engine.evaluate(past_events, past).index))

            results = await collect(as_of if req.mode == "replay" else None, req.use_llm)
            self.agent_results = {r.agent: r for r in results}
            summaries = {r.agent: AgentSummary(status=r.status, error_type=r.error_type, message=r.error_message or r.message,
                                               count=r.count, degraded=r.degraded, sources=r.sources) for r in results}
            ok = [r for r in results if r.status == "success"]
            degraded = len(ok) < len(results) or any(r.degraded for r in ok)

            if not ok:                                   # panne générale : on garde l'état précédent, on ne conclut rien
                self.last_run = PipelineRunResult(
                    status="error", mode=req.mode, scenario=scenario_id, fictional=fictional, day=day, days_total=days_total, topology=self.topology_ref(), topology_name=self.engine.meta.get("company") or self.engine.meta.get("name", ""),
                    as_of=as_of, agents=summaries, degraded=True, global_risk_index=self.engine.current.index,
                    message="Aucun agent n'a pu collecter de données. Ce n'est pas une absence d'alerte : "
                            + ("la nouvelle topologie est chargée, sans aucun signal." if changed else "l'état précédent est conservé."))
                return self.last_run

            events = self._cross_fill([e for r in ok for e in r.events])
            mode_label = f"replay:{scenario_id}" if req.mode == "replay" else "live"
            evaluation = self.engine.ingest(events, as_of=as_of, mode=mode_label)

            if req.mode == "replay":
                timeline.append(TimelinePoint(date=as_of, n_events=len(events), global_risk_index=evaluation.index))
            else:                                        # live : courbe reconstruite à partir de la date des événements
                d = first_day
                while d.isoformat() <= as_of:
                    visible = [e for e in events if e.date and e.date <= d.isoformat()]
                    timeline.append(TimelinePoint(date=d.isoformat(), n_events=len(visible),
                                                  global_risk_index=self.engine.evaluate(visible, d.isoformat()).index))
                    d += timedelta(days=1)

            failed = [r.agent for r in results if r.status != "success"]
            message = f"{len(events)} événement(s), {len(evaluation.signals)} signal(aux) corrélé(s), {len(self.engine.alerts())} alerte(s)."
            if failed:
                message += f" Agents en panne : {', '.join(failed)} : le résultat est incomplet."
            elif degraded:
                message += " Résultat incomplet : au moins une source a partiellement échoué."
            if fictional:
                message += " Scénario fictif."
            self.last_run = PipelineRunResult(
                status="partial" if degraded else "success", mode=req.mode, scenario=scenario_id, fictional=fictional,
                day=day, days_total=days_total, topology=self.topology_ref(), topology_name=self.engine.meta.get("company") or self.engine.meta.get("name", ""), as_of=as_of, agents=summaries, n_events=len(events),
                n_signals=len(evaluation.signals), n_alerts=len(self.engine.alerts()),
                global_risk_index=evaluation.index, degraded=degraded, message=message, timeline=timeline)
            self._persist()
            return self.last_run

    def _persist(self) -> None:
        """Historique : chaque exécution réussie est enregistrée dans la base unifiée (jamais bloquant)."""
        if not settings.persist_runs or self.last_run is None:
            return
        try:
            payload = self.events_payload()["events"]
            for item, ev in zip(payload, self.engine.events):
                item["weights"] = self.engine.link_weights(ev)
            db.record_run(self.last_run, self.engine, payload, self.topology_key())
        except Exception as e:
            log.warning("exécution non enregistrée dans la base : %s", e)

    # ------------------------------------------------------------------ lecture
    def events_payload(self) -> dict:
        cur = self.engine.current
        extraction = {row["event_id"]: row for r in self.agent_results.values() for row in r.extraction}
        return {
            "as_of": cur.as_of, "mode": self.engine.mode,
            "events": [{"agent": e.meta.agent, "nodes": cur.links.get(e.event.id, []),
                        "link": (None if not cur.links.get(e.event.id) else
                                 "exact" if max(self.engine.link_weights(e).values()) >= 1.0 else "elargi"),
                        "node_names": self.engine.names(cur.links.get(e.event.id, [])),
                        "extraction": extraction.get(e.event.id) if e.meta.agent == "media" else None,
                        "event": e.model_dump()} for e in self.engine.events],
            "signals": [dict(s.model_dump(), node_name=self.engine.nodes[s.node_id].name) for s in cur.signals],
        }

    def chat(self, req: ChatRequest, use_llm: Optional[bool] = None) -> ChatResponse:
        return self.assistant.chat(req, use_llm=use_llm)
