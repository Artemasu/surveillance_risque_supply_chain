// Miroir TypeScript des modèles Pydantic de src/schemas/events.py et src/api/main.py.

export type AgentName = "media" | "weather" | "finance";
export type NodeType = "matiere_premiere" | "fournisseur" | "port" | "hub" | "usine" | "produit_fini";
export type RiskLevel = "ok" | "info" | "warning" | "critical";

export interface AgentSummary {
  status: string;
  error_type?: string | null;
  message: string;
  count: number;
  degraded: boolean;
  sources: Record<string, any>;
}

export interface TimelinePoint {
  date: string;
  global_risk_index: number;
  n_events: number;
}

export interface PipelineRunResult {
  status: "success" | "partial" | "error";
  mode: string;
  scenario?: string | null;
  fictional: boolean;
  day?: number | null;
  days_total?: number | null;
  as_of?: string | null;
  topology?: string | null;
  topology_name: string;
  agents: Record<string, AgentSummary>;
  n_events: number;
  n_signals: number;
  n_alerts: number;
  global_risk_index: number;
  degraded: boolean;
  message: string;
  timeline: TimelinePoint[];
  /** Recommandation fournie par le backend / LLM, si une version future de l'API l'expose. */
  recommendation?: string | null;
}

export interface PipelineRunRequest {
  mode: "live" | "replay";
  scenario?: string | null;
  day?: number | null;
  use_llm?: boolean | null;
  topology?: string | null;
}

export interface Health {
  status: string;
  nodes: number;
  edges: number;
  llm_enabled: boolean;
  llm_model: string;
  llm_model_active?: string;
  llm_auto?: boolean;
  last_run?: PipelineRunResult | null;
}

export interface Scenario {
  id: string;
  title: string;
  fictional: boolean;
  start_date?: string | null;
  days?: number | null;
  topology: string;
  notice: string;
  storyline: Record<string, string>;
}

export interface Topology {
  ref: string | null;
  file: string;
  name: string;
  company?: string | null;
  sector?: string | null;
  nodes: number;
  default: boolean;
  active: boolean;
}

// Inscription d'un client (src/onboarding.py)
export interface Gabarit {
  id: string;
  label: string;
  noeuds: number;
}

export interface Inscription {
  entreprise: { raison_sociale: string; secteur: string; pays: string; taille: string };
  contact: { prenom: string; nom: string; email: string; fonction: string | null };
  gabarit: string | null;
  chaine: {
    sites: { nom: string; ville: string; pays: string; stock_jours: number }[];
    points_logistiques: { nom: string; ville: string; pays: string; type: "port" | "hub" }[];
    fournisseurs: { nom: string; ville: string; pays: string; categorie: string; site: string; part_pct: number; passage: string | null; stock_jours: number; critique: boolean }[];
    produits: { nom: string; site: string }[];
  } | null;
  pseudonymiser_fournisseurs: boolean;
  mot_de_passe: string;
  consentements: { traitement: boolean; habilitation: boolean; version_notice: string };
}

export interface InscriptionResultat {
  client_id: string;
  topology_ref: string;
  scenario_id: string;
  noeuds: number;
  liens: number;
  points_faibles: string[];
  conservation_jusqu_au: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  input: string;
  dependency: number;
  lead_time_days: number;
  backup: boolean;
  capacity: number;
}

export interface NodeState {
  id: string;
  name: string;
  type: NodeType;
  tier: number;
  criticality: number;
  country?: string | null;
  place?: string | null;
  lat?: number | null;
  lon?: number | null;
  stock_days: number;
  aliases: string[];
  company: boolean;
  weather_watch: boolean;
  keywords: string[];
  direct: number;
  propagated: number;
  risk: number;
  level: RiskLevel;
  path: string[];
  signal_ids: string[];
}

export interface GraphState {
  as_of?: string | null;
  mode?: string | null;
  global_risk_index: number;
  critical_nodes: string[];
  nodes: NodeState[];
  edges: GraphEdge[];
}

export interface Alert {
  id: string;
  node_id: string;
  node_name: string;
  node_type: NodeType;
  level: RiskLevel;
  risk: number;
  direct: number;
  propagated: number;
  priority: number;
  rule: string;
  path: string[];
  path_names: string[];
  agents: AgentName[];
  signal_ids: string[];
  source_ids: string[];
  summary: string;
  date?: string | null;
}

export interface CorrelatedSignal {
  id: string;
  node_id: string;
  node_name: string;
  family: string;
  types: string[];
  agents: AgentName[];
  event_ids: string[];
  source_ids: string[];
  first_date?: string | null;
  last_date?: string | null;
  severity: number;
  confidence: number;
  contribution: number;
  corroborated: boolean;
  link: "exact" | "elargi";
  label: string;
}

export interface NormalizedEvent {
  event: { id: string; type: string; label: string };
  date?: string | null;
  location: { name?: string | null; lat?: number | null; lon?: number | null };
  entities: { id?: string | null; name: string; role: string }[];
  weather?: Record<string, any> | null;
  finance?: Record<string, any> | null;
  media: { titre: string; date?: string | null; source_id: string }[];
  donnees_manquantes: string[];
  meta: { agent: AgentName; confidence: number; extractor: string; detail: string };
}

export interface EventEnvelope {
  agent: AgentName;
  nodes: string[];
  link: "exact" | "elargi" | null;
  node_names: string[];
  extraction: Record<string, any> | null;
  event: NormalizedEvent;
}

export interface EventsResponse {
  as_of?: string | null;
  mode?: string | null;
  events: EventEnvelope[];
  signals: CorrelatedSignal[];
}

export interface NodeImpact {
  node_id: string;
  name: string;
  type: NodeType;
  baseline: number;
  simulated: number;
  delta: number;
  level: RiskLevel;
  path: string[];
}

export interface MitigationAction {
  kind: "reallocation" | "route_secours" | "stock" | "surveillance";
  target: string;
  description: string;
  capacity?: number | null;
  lead_time_days?: number | null;
}

export interface SimulationResult {
  node_id: string;
  node_name: string;
  severity: number;
  baseline_index: number;
  simulated_index: number;
  impacts: NodeImpact[];
  threatened_products: NodeImpact[];
  nodes: NodeState[];
  mitigation: {
    node_id: string;
    node_name: string;
    actions: MitigationAction[];
    coverage: Record<string, number>;
    threatened_products: string[];
  };
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, any>;
  result: any;
}

export interface ChatResponse {
  answer: string;
  mode: "llm" | "deterministic";
  tool_calls: ToolCall[];
  context: Record<string, any>;
  note: string;
}
