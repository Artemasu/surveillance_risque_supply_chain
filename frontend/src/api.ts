// Client HTTP de l'API FastAPI (src/api/main.py). URL surchargeable par VITE_API_URL.
import type {
  Alert, ChatResponse, ChatTurn, EventsResponse, Gabarit, GraphState, Health, Inscription, InscriptionResultat,
  PipelineRunRequest, PipelineRunResult, Scenario, SimulationResult, Topology,
} from "./types";
import { session, type Profil } from "./session";

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
      headers: {
        "Content-Type": "application/json",
        ...(session.jeton() ? { Authorization: `Bearer ${session.jeton()}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, `API injoignable sur ${API_URL}. Lancez : uvicorn src.api.main:app --port 8000`);
  }
  // Session expirée ou invalide : retour à la page de connexion (sauf pendant la connexion elle-même).
  if (res.status === 401 && path !== "/auth/connexion" && session.jeton()) {
    session.fermer();
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

/** Téléchargement authentifié (un lien <a href> ne transmettrait pas le jeton). */
export async function telecharger(url: string, nomFichier: string): Promise<void> {
  const jeton = session.jeton();
  const res = await fetch(url, { headers: jeton ? { Authorization: `Bearer ${jeton}` } : {} });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status} : téléchargement refusé`);
  const lien = document.createElement("a");
  lien.href = URL.createObjectURL(await res.blob());
  lien.download = nomFichier;
  lien.click();
  URL.revokeObjectURL(lien.href);
}

const post = <T>(path: string, body: unknown) => http<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => http<Health>("/health"),
  scenarios: () => http<Scenario[]>("/scenarios"),
  topologies: () => http<Topology[]>("/topologies"),
  run: (req: PipelineRunRequest) => post<PipelineRunResult>("/pipeline/run", req),
  state: () => http<GraphState>("/graph/state"),
  simulate: (node_id: string, severity: number, extra?: Record<string, number>, scenario?: string) =>
    post<SimulationResult>("/graph/simulate", { node_id, severity, extra: extra ?? {}, scenario: scenario ?? null }),
  alerts: () => http<Alert[]>("/alerts"),
  events: () => http<EventsResponse>("/events"),
  chat: (message: string, history: ChatTurn[], context: Record<string, unknown>) =>
    post<ChatResponse>("/chat", { message, history, context }),
  clientParams: () => http<{ gabarits: Gabarit[]; version_notice: string; conservation_annees: number }>("/clients/parametres"),
  inscription: (body: Inscription) => post<InscriptionResultat>("/clients/inscription", body),
  connexion: (email: string, mot_de_passe: string) => post<{ jeton: string; profil: Profil }>("/auth/connexion", { email, mot_de_passe }),
  exportClient: (id: string) => http<Record<string, unknown>>(`/clients/${id}/export`),
  supprimerClient: (id: string) => http<{ supprimes: string[] }>(`/clients/${id}`, { method: "DELETE" }),
};
