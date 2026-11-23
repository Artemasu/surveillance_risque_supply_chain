"""API REST FastAPI. Documentation OpenAPI automatique sur /docs.

    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.api.routes_data import router as data_router
from src.api.routes_database import router as database_router
from src.config import settings
from src.schemas.events import (Alert, ChatRequest, ChatResponse, GraphState, PipelineRunRequest, PipelineRunResult,
                                SimulationRequest, SimulationResult)
from src.service import ScenarioNotFound, SupplyChainService
from src.utils.llm import active_model


class Health(BaseModel):
    status: str
    nodes: int
    edges: int
    llm_enabled: bool
    llm_model: str                       # modèle configuré (OLLAMA_MODEL, benchmark local ou défaut)
    llm_model_active: str = ""           # modèle réellement utilisé (repli sur un modèle installé si absent)
    llm_auto: bool = False               # True : aucun modèle imposé par variable d'environnement
    last_run: Optional[PipelineRunResult] = None


class EventsResponse(BaseModel):
    as_of: Optional[str] = None
    mode: Optional[str] = None
    events: list[dict[str, Any]]
    signals: list[dict[str, Any]]


def create_app(service: Optional[SupplyChainService] = None) -> FastAPI:
    app = FastAPI(
        title="A.E.G.I.S. API",
        version="1.0.0",
        description="**A.E.G.I.S.** — Automated Early-warning & Graph Intelligence for Supply-chain. "
                    "Agents médias, météo et finance ; graphe d'ontologie NetworkX ; simulation what-if ; copilot.")
    app.state.service = service or SupplyChainService()
    # Front-end React (frontend/, serveur Vite) : seul ajout à l'API, aucune logique métier modifiée.
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def svc(request: Request) -> SupplyChainService:
        return request.app.state.service

    @app.get("/health", response_model=Health, tags=["système"])
    def health(request: Request) -> Health:
        s = svc(request)
        return Health(status="ok", nodes=len(s.engine.nodes), edges=len(s.engine.edges), llm_enabled=settings.use_llm,
                      llm_model=settings.llm_model, llm_model_active=active_model(), llm_auto=settings.llm_auto,
                      last_run=s.last_run)

    @app.get("/scenarios", tags=["pipeline"])
    def scenarios(request: Request) -> list[dict]:
        """Scénarios de replay disponibles dans data/replay_scenarios."""
        return svc(request).list_scenarios()

    @app.get("/topologies", tags=["pipeline"])
    def topologies(request: Request) -> list[dict]:
        """Topologies disponibles (une par entreprise ou secteur). `ref` se passe à /pipeline/run en mode live."""
        return svc(request).list_topologies()

    @app.post("/pipeline/run", response_model=PipelineRunResult, tags=["pipeline"])
    async def pipeline_run(req: PipelineRunRequest, request: Request) -> PipelineRunResult:
        """Lance les trois agents puis le moteur de graphe. `status="error"` signale une panne de collecte,
        jamais une absence d'alerte."""
        try:
            return await svc(request).run_pipeline(req)
        except ScenarioNotFound as e:
            raise HTTPException(status_code=404, detail=str(e))
        except (ValueError, OSError) as e:               # topologie présente mais invalide
            raise HTTPException(status_code=400, detail=f"topologie invalide : {e}")

    @app.get("/graph/state", response_model=GraphState, tags=["graphe"])
    def graph_state(request: Request) -> GraphState:
        """Nœuds avec leur risque direct, propagé et total, et liens du graphe."""
        return svc(request).engine.state()

    @app.post("/graph/simulate", response_model=SimulationResult, tags=["graphe"])
    def graph_simulate(req: SimulationRequest, request: Request) -> SimulationResult:
        """Simulation what-if d'une panne. L'état réel n'est pas modifié."""
        try:
            return svc(request).engine.simulate_disruption(req.node_id, req.severity, req.extra or None)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"nœud inconnu : {req.node_id}")

    @app.get("/alerts", response_model=list[Alert], tags=["alertes"])
    def alerts(request: Request, level: Optional[str] = Query(None, pattern="^(warning|critical)$"),
               agent: Optional[str] = Query(None, pattern="^(media|weather|finance)$")) -> list[Alert]:
        """Alertes priorisées et expliquées (règle, chemin dans le graphe, sources)."""
        out = svc(request).engine.alerts()
        if level:
            out = [a for a in out if a.level == level]
        if agent:
            out = [a for a in out if agent in a.agents]
        return out

    @app.get("/events", response_model=EventsResponse, tags=["alertes"])
    def events(request: Request) -> EventsResponse:
        """Événements normalisés des agents (JSON du contrat commun) et signaux corrélés par nœud."""
        return EventsResponse(**svc(request).events_payload())

    @app.post("/chat", response_model=ChatResponse, tags=["copilot"])
    def chat(req: ChatRequest, request: Request) -> ChatResponse:
        """Copilot : LLM avec outils si disponible, sinon réponse déterministe à partir du graphe."""
        return svc(request).chat(req)

    app.include_router(data_router)          # volets Météo et Finance, historique, stress tests
    app.include_router(database_router)      # explorateur de la base unifiée et du graphe (lecture seule)
    return app


app = create_app()
