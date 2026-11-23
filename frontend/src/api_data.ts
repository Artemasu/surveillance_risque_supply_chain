// Client des volets Météo et Finance, de l'historique et des stress tests (src/api/routes_data.py).
import { API_URL, ApiError } from "./api";
import type {
  FinanceOverview, FinRule, FinSeries, HistoryEvent, HistoryRun, NodeRiskPoint, StressTest, WeatherOverview, WxSeries,
} from "./types_data";

async function call<T>(path: string, method: "GET" | "POST" = "GET"): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers: { "Content-Type": "application/json" } });
  } catch {
    throw new ApiError(0, `API injoignable sur ${API_URL}`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* corps non JSON */
    }
    throw new ApiError(res.status, `API ${res.status} : ${detail}`);
  }
  return res.json() as Promise<T>;
}

const q = (p: Record<string, string | number | undefined | null>) => {
  const s = Object.entries(p)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return s.length ? `?${s.join("&")}` : "";
};

export type HeatCell = { site: string; indicator: string; rank: number | null; value: number | null; alert: boolean };
export type DieselRow = { pays: string; date: string; prix: number; var_4s: number; decalage_semaines: number | null; correlation: number | null };

export const dataApi = {
  weather: () => call<WeatherOverview>("/weather/overview"),
  weatherSeries: (site: string, indicator: string, days = 365) =>
    call<WxSeries>(`/weather/sites/${encodeURIComponent(site)}/series${q({ indicator, days })}`),
  weatherHeatmap: () => call<{ cells: HeatCell[]; indicators: string[] }>("/weather/heatmap"),
  weatherEpisodes: (site: string, years = 15) => call<{ mois: string; jours: number }[]>(`/weather/episodes${q({ site, years })}`),
  finance: () => call<FinanceOverview>("/finance/overview"),
  financeSeries: (signal: string, start = "2019-01-01") => call<FinSeries>(`/finance/signals/${encodeURIComponent(signal)}/series${q({ start })}`),
  base100: (start = "2019-01-01") => call<{ signals: string[]; series: Record<string, number | string | null>[] }>(`/finance/base100${q({ start })}`),
  financeScore: (start = "2019-01-01") => call<{ date: string; score: number | null; alert: boolean }[]>(`/finance/score${q({ start })}`),
  supplier: (cle: string) => call<Record<string, any>>(`/finance/suppliers/${encodeURIComponent(cle)}`),
  rules: (since = "2022-01-01", zone?: string) => call<FinRule[]>(`/finance/rules${q({ since, zone })}`),
  diesel: () => call<{ countries: DieselRow[] }>("/finance/diesel"),
  financeValidation: () => call<{ cases: any[]; noise: { signal: string; episodes_per_year: number }[] }>("/finance/validation"),
  runs: (limit = 100) => call<HistoryRun[]>(`/history/runs${q({ limit })}`),
  risk: (node_id?: string, topology?: string) =>
    call<{ global: HistoryRun[]; node: NodeRiskPoint[]; top: { node_id: string; name: string; type: string; risk: number; level: string; families: string[] }[] }>(
      `/history/risk${q({ node_id, topology })}`,
    ),
  historyEvents: (p: { agent?: string; family?: string; topology?: string; limit?: number }) => call<HistoryEvent[]>(`/history/events${q(p)}`),
  compare: (a: string, b: string) =>
    call<{ nodes: { node_id: string; name: string; type: string; before: number | null; after: number | null; delta: number; level: string | null }[] }>(
      `/history/compare${q({ a, b })}`,
    ),
  stressTests: () => call<StressTest[]>("/graph/stress-tests"),
  sources: () => call<{ db: string; ready: boolean; counts: Record<string, number>; sources: any[]; calibrated_hubs: string[] }>("/sources/status"),
  job: (name: "forecast-meteo" | "ingest-finance") => call<{ job: string; result: any }>(`/jobs/${name}`, "POST"),

  // Explorateur de la base unifiée (lecture seule)
  dbSummary: () => call<DbSummary>("/database/summary"),
  dbTables: () => call<DbTableInfo[]>("/database/tables"),
  dbTable: (name: string, p: DbQuery) => call<DbPage>(`/database/tables/${encodeURIComponent(name)}${q(p as Record<string, string | number | undefined | null>)}`),
  dbValues: (name: string, column: string) => call<string[]>(`/database/tables/${encodeURIComponent(name)}/values${q({ column })}`),
  dbCsvUrl: (name: string, p: DbQuery) => `${API_URL}/database/tables/${encodeURIComponent(name)}${q({ ...(p as Record<string, string | number | undefined | null>), format: "csv", limit: undefined, offset: undefined })}`,
  unifiedGraph: () => call<UnifiedGraph>("/database/unified-graph"),
};

export interface DbSummary {
  ready: boolean;
  db: string;
  size_mb?: number;
  tables?: number;
  rows_total?: number;
  domains: {
    media?: { evenements: number; articles: number };
    weather?: { indicateurs: number; sites: number; seuils: number; previsions: number; jours_en_alerte: number };
    finance?: { valeurs: number; signaux: number; fournisseurs: number; sanctions: number; regles: number };
    unified?: { evenements: number; liens: number; liaisons_referentiel: number; executions: number; historique_noeuds: number; par_agent: Record<string, number> };
  };
}

export interface DbTableInfo {
  name: string;
  label: string;
  domain: "media" | "weather" | "finance" | "unified";
  description: string;
  has_date: boolean;
  filters: string[];
  alert: boolean;
  rank: string | null;
  available: boolean;
}

export interface DbQuery {
  limit?: number;
  offset?: number;
  q?: string;
  date_from?: string;
  date_to?: string;
  site?: string;
  symbol?: string;
  indicator?: string;
  family?: string;
  agent?: string;
  zone?: string;
  type?: string;
  topology?: string;
  alert?: string;
  min_rank?: number;
}

export interface DbPage {
  name: string;
  label: string;
  total: number;
  limit: number;
  offset: number;
  columns: string[];
  rows: Record<string, any>[];
}

export interface UGNode {
  id: string;
  name: string;
  type: import("./types").NodeType;
  tier: number;
  country?: string | null;
  place?: string | null;
  criticality: number;
  stock_days: number;
  risk: number;
  direct: number;
  propagated: number;
  level: import("./types").RiskLevel;
  signal_ids: string[];
  families: string[];
}

export interface UGEvent {
  id: string;
  agent: import("./types").AgentName;
  type: string;
  family: string | null;
  date: string | null;
  label: string;
  confidence: number;
  intensity: number | null;
  sources: string[];
  links: { node_id: string; weight: number; link: string }[];
}

export interface UnifiedGraph {
  topology: string;
  topology_name: string;
  run: { run_id: string; as_of: string; mode: string; scenario: string | null } | null;
  nodes: UGNode[];
  edges: import("./types").GraphEdge[];
  events: UGEvent[];
}
