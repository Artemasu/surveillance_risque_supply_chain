// Client HTTP de l'API FastAPI (src/api/main.py). URL surchargeable par VITE_API_URL.
import type {
  Alert, ChatResponse, ChatTurn, EventsResponse, GraphState, Health, PipelineRunRequest, PipelineRunResult,
  Scenario, SimulationResult, Topology,
} from "./types";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, `API injoignable sur ${API_URL}. Lancez : uvicorn src.api.main:app --port 8000`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* corps non JSON */
    }
    throw new ApiError(res.status, `API ${res.status} : ${detail}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => http<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => http<Health>("/health"),
  scenarios: () => http<Scenario[]>("/scenarios"),
  topologies: () => http<Topology[]>("/topologies"),
  run: (req: PipelineRunRequest) => post<PipelineRunResult>("/pipeline/run", req),
  state: () => http<GraphState>("/graph/state"),
  simulate: (node_id: string, severity: number) => post<SimulationResult>("/graph/simulate", { node_id, severity }),
  alerts: () => http<Alert[]>("/alerts"),
  events: () => http<EventsResponse>("/events"),
  chat: (message: string, history: ChatTurn[], context: Record<string, unknown>) =>
    post<ChatResponse>("/chat", { message, history, context }),
};
