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
};
