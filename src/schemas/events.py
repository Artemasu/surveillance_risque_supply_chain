"""Modèles Pydantic v2 : contrat commun des agents, graphe, alertes, simulation, API.

Le contrat d'événement reprend celui du notebook v2 (event, date, location, entities, media,
donnees_manquantes) et y ajoute les blocs `weather` et `finance` du README, plus un bloc `meta`.
Tous les modèles refusent les clés inconnues (extra="forbid").
"""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EventType = Literal["greve", "catastrophe", "sanction", "faillite", "cyberattaque", "penurie", "logistique",
                    "meteo_extreme", "tension_marche", "difficulte_financiere", "aucun"]
MEDIA_EVENT_TYPES = ["greve", "catastrophe", "sanction", "faillite", "cyberattaque", "penurie", "logistique", "aucun"]
AgentName = Literal["media", "weather", "finance"]
# « exposé » : nœud rattaché par un indice large (matière première, mot-clé sectoriel, pays), jamais par le LLM.
Role = Literal["touché", "mentionné", "exposé"]
NodeType = Literal["matiere_premiere", "fournisseur", "port", "hub", "usine", "produit_fini"]
RiskLevel = Literal["ok", "info", "warning", "critical"]

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- événement normalisé
class EventInfo(Strict):
    id: str = Field(min_length=1)
    type: EventType
    label: str = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label vide")
        return v


class Location(Strict):
    name: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)


class EntityRef(Strict):
    id: Optional[str] = None          # "LEI:..." si connu, sinon "SUP:<id interne>", sinon None. Jamais inventé.
    name: str = Field(min_length=1)
    role: Role


class MediaRef(Strict):
    titre: str
    date: Optional[str] = None
    source_id: str = Field(min_length=1)


class WeatherBlock(Strict):
    """Mesures brutes. La conversion en gravité est faite par le moteur de graphe, pas par l'agent."""
    hub: str
    date: str                                   # jour concerné par la mesure ou la prévision
    wind_max_kmh: Optional[float] = Field(default=None, ge=0)
    gust_max_kmh: Optional[float] = Field(default=None, ge=0)
    precip_mm: Optional[float] = Field(default=None, ge=0)
    weather_code: Optional[int] = None
    forecast: bool = False
    provider: str = "open-meteo"
    source_id: str = Field(min_length=1)
    # Seuils calibrés par site (volet Météo) : absents quand l'agent applique les seuils fixes de repli
    indicator: Optional[str] = None             # pluie_3j, pluie_90j, rafales, neige, chaleur, gel, crue, basses_eaux
    value: Optional[float] = None               # valeur de l'indicateur dominant
    threshold: Optional[float] = None           # seuil propre au site (quantile 99 % ou 1 % sur 2010-2020)
    unit: Optional[str] = None
    rank: Optional[float] = Field(default=None, ge=0, le=1)   # 0,99 = parmi les 1 % de jours les plus extrêmes du site
    level: Optional[str] = None                 # normal, inhabituel, exceptionnel
    score: Optional[float] = Field(default=None, ge=0, le=1)  # score météo recalibré du site ce jour-là
    risk: Optional[str] = None                  # conséquence supply chain de l'indicateur
    indicators: list[dict[str, Any]] = Field(default_factory=list)   # tous les indicateurs en alerte au pic
    temp_max_c: Optional[float] = None
    temp_min_c: Optional[float] = None
    snow_cm: Optional[float] = None
    discharge_m3s: Optional[float] = None


class FinanceBlock(Strict):
    instrument: str
    name: str
    date: str
    close: Optional[float] = None
    change_5d_pct: Optional[float] = None
    zscore: Optional[float] = None
    provider: str = "yfinance"
    source_id: str = Field(min_length=1)
    # Volet Finance : signaux calibrés, fiches fournisseurs, sanctions, procédures collectives
    kind: Literal["instrument", "signal", "bourse", "sanction", "procedure", "regle"] = "instrument"
    family: Optional[str] = None                # énergie, fret, change, métaux, prix fournisseurs, fournisseurs...
    indicator: Optional[float] = None           # variation % sur l'horizon, ou niveau (GSCPI)
    measure: Optional[str] = None               # variation_% ou niveau
    horizon: Optional[int] = None
    threshold: Optional[float] = None
    rank: Optional[float] = Field(default=None, ge=0, le=1)
    unit: Optional[str] = None
    impact: Optional[str] = None
    detail: Optional[str] = None
    url: Optional[str] = None


class EventMeta(Strict):
    agent: AgentName
    confidence: float = Field(ge=0, le=1)       # confiance de qualification (pas un score de gravité)
    extractor: str                              # "baseline", "llm", "seuils"
    detail: str = ""


class NormalizedEvent(Strict):
    event: EventInfo
    date: Optional[str] = None                  # date du premier signal, AAAA-MM-JJ, toujours calculée par le code
    location: Location
    entities: list[EntityRef] = Field(default_factory=list)
    weather: Optional[WeatherBlock] = None
    finance: Optional[FinanceBlock] = None
    media: list[MediaRef] = Field(default_factory=list)
    donnees_manquantes: list[str] = Field(default_factory=list)
    meta: EventMeta

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _DATE_RE.fullmatch(v):
            raise ValueError("date invalide : format attendu AAAA-MM-JJ")
        return v

    @model_validator(mode="after")
    def _no_fact_without_source(self) -> "NormalizedEvent":
        agent = self.meta.agent
        if agent == "media" and not self.media:
            raise ValueError("un événement médias doit citer au moins un article (source_id)")
        if agent == "weather" and self.weather is None:
            raise ValueError("un événement météo doit porter un bloc weather")
        if agent == "finance" and self.finance is None:
            raise ValueError("un événement finance doit porter un bloc finance")
        return self

    @property
    def source_ids(self) -> list[str]:
        ids = [m.source_id for m in self.media]
        if self.weather:
            ids.append(self.weather.source_id)
        if self.finance:
            ids.append(self.finance.source_id)
        return list(dict.fromkeys(ids))


# --------------------------------------------------------------------------- réponse d'un agent
class AgentResult(Strict):
    """Contrat de réponse du notebook v2 : une absence d'alerte et une panne ne se ressemblent jamais."""
    agent: AgentName
    status: Literal["success", "error"]
    error_type: Optional[Literal["network_failure", "source_unavailable", "invalid_request", "internal_error"]] = None
    error_message: Optional[str] = None
    mode: str
    count: int = 0
    events: list[NormalizedEvent] = Field(default_factory=list)
    degraded: bool = False
    sources: dict[str, Any] = Field(default_factory=dict)
    extraction: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""


# --------------------------------------------------------------------------- graphe
class GraphNode(Strict):
    id: str
    name: str
    type: NodeType
    tier: int = Field(ge=0, le=5)               # 0 = produit fini ... 4 = matière première
    criticality: float = Field(ge=0, le=1)
    country: Optional[str] = None
    place: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    stock_days: float = Field(default=0, ge=0)
    aliases: list[str] = Field(default_factory=list)
    company: bool = False                       # True : entre dans le référentiel entreprises de l'agent médias
    weather_watch: bool = False
    keywords: list[str] = Field(default_factory=list)   # mots-clés sectoriels pour le rattachement élargi des articles


class GraphEdge(Strict):
    source: str
    target: str
    input: str                                  # catégorie d'intrant fournie à la cible
    dependency: float = Field(ge=0, le=1)       # part de l'intrant couverte par cette source (0 pour un secours)
    lead_time_days: float = Field(default=0, ge=0)
    backup: bool = False                        # lien de secours : hors propagation, proposé en mitigation
    capacity: float = Field(default=0, ge=0, le=1)   # part maximale activable (secours ou réserve d'un lien actif)


class NodeState(GraphNode):
    direct: float = 0.0
    propagated: float = 0.0
    risk: float = 0.0
    level: RiskLevel = "ok"
    path: list[str] = Field(default_factory=list)       # chemin dominant qui explique le risque
    signal_ids: list[str] = Field(default_factory=list)


class CorrelatedSignal(Strict):
    """Signaux de plusieurs sources regroupés sur un même nœud et une même famille d'aléa."""
    id: str
    node_id: str
    family: str
    types: list[str]
    agents: list[AgentName]
    event_ids: list[str]
    source_ids: list[str]
    first_date: Optional[str]
    last_date: Optional[str]
    severity: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1)     # severity x confidence x fraîcheur
    corroborated: bool
    link: Literal["exact", "elargi"] = "exact"      # elargi : aucun événement du signal ne cite le nœud par son nom
    label: str


class Alert(Strict):
    id: str
    node_id: str
    node_name: str
    node_type: NodeType
    level: RiskLevel
    risk: float
    direct: float
    propagated: float
    priority: float                             # risk pondéré par la criticité du nœud
    rule: str
    path: list[str]
    path_names: list[str]
    agents: list[AgentName]
    signal_ids: list[str]
    source_ids: list[str]
    summary: str
    date: Optional[str] = None


class GraphState(Strict):
    as_of: Optional[str] = None
    mode: Optional[str] = None
    global_risk_index: float = 0.0
    critical_nodes: list[str] = Field(default_factory=list)
    nodes: list[NodeState]
    edges: list[GraphEdge]


# --------------------------------------------------------------------------- simulation
class SimulationRequest(Strict):
    node_id: str = Field(min_length=1)
    severity: float = Field(ge=0, le=1)
    extra: dict[str, float] = Field(default_factory=dict)   # stress test : autres nœuds touchés en même temps
    scenario: Optional[str] = None                           # identifiant d'un stress test prédéfini (affichage)


class NodeImpact(Strict):
    node_id: str
    name: str
    type: NodeType
    baseline: float
    simulated: float
    delta: float
    level: RiskLevel
    path: list[str]


class MitigationAction(Strict):
    kind: Literal["reallocation", "route_secours", "stock", "surveillance"]
    target: str
    description: str
    capacity: Optional[float] = None
    lead_time_days: Optional[float] = None


class MitigationPlan(Strict):
    node_id: str
    node_name: str
    actions: list[MitigationAction]
    coverage: dict[str, float] = Field(default_factory=dict)   # par client direct : part de l'intrant récupérable
    threatened_products: list[str] = Field(default_factory=list)


class SimulationResult(Strict):
    node_id: str
    node_name: str
    severity: float
    baseline_index: float
    simulated_index: float
    impacts: list[NodeImpact]
    threatened_products: list[NodeImpact]
    nodes: list[NodeState]                      # état simulé complet, pour colorer le graphe
    mitigation: MitigationPlan


# --------------------------------------------------------------------------- pipeline / API
class PipelineRunRequest(Strict):
    mode: Literal["live", "replay"] = "replay"
    scenario: Optional[str] = None
    day: Optional[int] = Field(default=None, ge=1)
    use_llm: Optional[bool] = None
    topology: Optional[str] = None      # mode live : topologie cible, relative à data/ (ex. "topologies/pharma_helvia.yaml")


class AgentSummary(Strict):
    status: str
    error_type: Optional[str] = None
    message: str = ""
    count: int = 0
    degraded: bool = False
    sources: dict[str, Any] = Field(default_factory=dict)


class TimelinePoint(Strict):
    date: str
    global_risk_index: float
    n_events: int


class PipelineRunResult(Strict):
    status: Literal["success", "partial", "error"]
    mode: str
    scenario: Optional[str] = None
    fictional: bool = False
    day: Optional[int] = None
    days_total: Optional[int] = None
    as_of: Optional[str] = None
    topology: Optional[str] = None              # topologie chargée pour cette exécution (None : topologie par défaut)
    topology_name: str = ""
    agents: dict[str, AgentSummary]
    n_events: int = 0
    n_signals: int = 0
    n_alerts: int = 0
    global_risk_index: float = 0.0
    degraded: bool = False
    message: str = ""
    timeline: list[TimelinePoint] = Field(default_factory=list)


class ChatTurn(Strict):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(Strict):
    message: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class ToolCall(Strict):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class ChatResponse(Strict):
    answer: str
    mode: Literal["llm", "deterministic"]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    note: str = ""
