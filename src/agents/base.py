"""Classe de base des agents. Chaque agent sait collecter (live ou replay) et extraire des événements normalisés.

`run()` applique à tous les agents le contrat de réponse du notebook v2 :
  - status="success", count=0 : la collecte a marché, il n'y a rien à signaler ;
  - status="error" : la collecte a échoué, on ne peut pas conclure ;
  - degraded=True : résultat exploitable mais incomplet.
Règle zéro démo : `collect_live` ne renvoie jamais de données de scénario. S'il n'obtient rien, il renvoie une
liste vide et l'état des sources dit pourquoi.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.config import settings
from src.schemas.events import AgentResult, NormalizedEvent

log = logging.getLogger("supplychain.agents")


class BaseAgent(ABC):
    name: str = "base"

    @abstractmethod
    async def collect_live(self, report: Optional[dict] = None, **kwargs) -> Any:
        """Données brutes des derniers jours. `report` reçoit l'état de chaque source (ok, partial, failed, unavailable)."""

    @abstractmethod
    async def collect_replay(self, scenario: dict, as_of: Optional[str] = None, report: Optional[dict] = None) -> Any:
        """Données brutes d'un scénario, limitées à ce qui était connu le jour `as_of` (pas de fuite du futur)."""

    @abstractmethod
    async def extract_events(self, raw: Any, **kwargs) -> list[NormalizedEvent]:
        """Données brutes -> événements au format commun."""

    def _extraction_log(self) -> list[dict]:
        return []

    async def run(self, mode: str = "live", scenario: Optional[dict] = None, as_of: Optional[str] = None,
                  **kwargs) -> AgentResult:
        """Collecte puis extraction. Ne lève jamais d'exception."""
        report: dict[str, Any] = {}
        base = {"agent": self.name, "mode": mode, "sources": report}
        try:
            if mode == "live":
                raw = await self.collect_live(report=report)
            elif mode == "replay":
                if not scenario:
                    return AgentResult(**base, status="error", error_type="invalid_request",
                                       error_message="le mode replay demande un scénario")
                raw = await self.collect_replay(scenario, as_of=as_of, report=report)
            else:
                return AgentResult(**base, status="error", error_type="invalid_request",
                                   error_message=f"mode inconnu : {mode!r} (attendu : live ou replay)")

            states = [s.get("status") for s in report.values()]
            if not any(s in ("ok", "partial") for s in states):
                if states and all(s == "unavailable" for s in states):
                    detail = " ; ".join(str(s.get("detail", "")) for s in report.values())
                    return AgentResult(**base, status="error", error_type="source_unavailable",
                                       error_message=f"Aucune source utilisable : {detail}")
                return AgentResult(**base, status="error", error_type="network_failure",
                                   error_message=f"Aucune source {self.name} n'a pu être lue. Ce n'est pas une absence d'événement.")
            degraded = any(s != "ok" for s in states)

            # Rattachement élargi (agent médias) : en live par défaut, réglable par BROAD_LINKING.
            kwargs.setdefault("broad_linking", settings.broad_linking == "always"
                              or (settings.broad_linking == "live" and mode == "live"))
            events = await self.extract_events(raw, **kwargs)
            message = (f"{len(events)} événement(s)." if events else "Collecte réussie : aucun événement à signaler.")
            if degraded:
                message += " Résultat incomplet : au moins une source a partiellement échoué (voir sources)."
            return AgentResult(**base, status="success", count=len(events), events=events, degraded=degraded,
                               extraction=self._extraction_log(), message=message)
        except Exception as e:                       # filet de sécurité : un agent ne fait jamais tomber le pipeline
            log.exception("agent %s : erreur inattendue", self.name)
            return AgentResult(**base, status="error", error_type="internal_error",
                               error_message=f"{type(e).__name__} : {e}")
