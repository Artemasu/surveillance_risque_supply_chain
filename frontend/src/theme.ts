// Identité visuelle : couleurs pastel par agent, niveaux de risque doux, libellés français.
import type { AgentName, NodeType, RiskLevel } from "./types";

export const AGENTS: AgentName[] = ["media", "finance", "weather"];

export const AGENT_STYLE: Record<AgentName, { label: string; bg: string; bg2: string; border: string; text: string; dot: string }> = {
  media: { label: "Médias", bg: "#FEF9C3", bg2: "#FEF3C7", border: "#FDE047", text: "#854D0E", dot: "#EAB308" },
  finance: { label: "Finance", bg: "#DBEAFE", bg2: "#E0F2FE", border: "#93C5FD", text: "#1E40AF", dot: "#3B82F6" },
  weather: { label: "Météo", bg: "#DCFCE7", bg2: "#D1FAE5", border: "#86EFAC", text: "#166534", dot: "#22C55E" },
};

export const LEVEL_STYLE: Record<RiskLevel, { label: string; color: string; bg: string }> = {
  ok: { label: "Normal", color: "#10B981", bg: "#ECFDF5" },
  info: { label: "À surveiller", color: "#D97706", bg: "#FFFBEB" },
  warning: { label: "Alerte", color: "#EA580C", bg: "#FFF7ED" },
  critical: { label: "Critique", color: "#BE123C", bg: "#FFF1F2" },
};

export const LEVEL_ORDER: RiskLevel[] = ["ok", "info", "warning", "critical"];

export const TYPE_LABEL: Record<NodeType, string> = {
  matiere_premiere: "Matière première",
  fournisseur: "Fournisseur",
  port: "Port",
  hub: "Hub",
  usine: "Usine",
  produit_fini: "Produit fini",
};

/** Niveau d'un score 0–100, mêmes seuils que le moteur (LEVEL_THRESHOLDS : 60 / 35 / 15). */
export function indexLevel(index: number): RiskLevel {
  if (index >= 60) return "critical";
  if (index >= 35) return "warning";
  if (index >= 15) return "info";
  return "ok";
}

export const fmt1 = (v: number) => v.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const pct = (v: number) => `${Math.round(v * 100)} %`;

export function frDate(iso?: string | null, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }) {
  if (!iso) return "—";
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fr-FR", opts);
}
