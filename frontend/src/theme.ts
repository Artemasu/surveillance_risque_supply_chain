// Identité visuelle : couleurs pastel par agent, niveaux de risque doux, libellés français.
import type { AgentName, NodeType, RiskLevel } from "./types";

export const AGENTS: AgentName[] = ["media", "finance", "weather"];

export const AGENT_STYLE: Record<AgentName, { label: string; bg: string; bg2: string; border: string; text: string; dot: string }> = {
  // Charte A.E.G.I.S. : moutarde (médias), bleu canard (finance), vert olive (météo) — voir tailwind.config.js.
  media: { label: "Médias", bg: "#FBF1D0", bg2: "#FDF6E1", border: "#ECB920", text: "#6E5200", dot: "#ECB920" },
  finance: { label: "Finance", bg: "#D6EDEF", bg2: "#E8F4F5", border: "#5FAFB8", text: "#01545D", dot: "#017F8D" },
  weather: { label: "Météo", bg: "#EEF2DC", bg2: "#F4F6E8", border: "#A2B153", text: "#4A5520", dot: "#A2B153" },
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
