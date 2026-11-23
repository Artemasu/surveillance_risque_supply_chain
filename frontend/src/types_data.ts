// Miroir TypeScript des réponses des volets Météo et Finance, de l'historique et des stress tests
// (src/api/routes_data.py).
import type { AgentName, NodeType } from "./types";

export interface WxIndicatorToday {
  indicator: string;
  value: number | null;
  threshold: number | null;
  rank: number | null;
  alert: boolean;
}

export interface WxSite {
  site: string;
  name: string;
  country?: string | null;
  lat: number;
  lon: number;
  role?: string | null;
  fluvial: boolean;
  indicators: string[];
  climat?: string | null;
  origin?: string | null;
  last_date?: string | null;
  score: number | null;
  alert_today: boolean;
  indicators_today: WxIndicatorToday[];
  forecast_alerts: number;
  forecast_max_rank: number | null;
  episodes_per_year: number | null;
  nodes: { node_id: string; name: string; type: NodeType; products: string[] }[];
}

export interface WxForecastRow {
  site: string;
  run_date: string;
  date: string;
  indicator: string;
  value: number;
  threshold: number;
  rank: number | null;
  alert: boolean;
  unit: string;
  risk: string;
  score: number | null;
}

export interface ValidationCase {
  agent: string;
  cas: string;
  cible: string;
  indicator: string;
  detected: boolean;
  lead_days: number | null;
  payload?: Record<string, any>;
}

export interface WeatherOverview {
  ready: boolean;
  message?: string;
  kpis: {
    sites: number; sites_in_topology: number; alerts_today: number; forecast_alerts: number; forecast_sites: number;
    best_lead_days: number | null; episodes_per_year: number | null; forecast_run: string | null; cases: number;
    cases_detected: number; hubs_calibrated: number; hubs_watched: number;
  };
  sites: WxSite[];
  forecast: WxForecastRow[];
  validation: ValidationCase[];
  indicators: Record<string, { label: string; unit: string; risk: string; sens: string }>;
}

export interface WxSeriesPoint {
  date: string;
  value: number | null;
  threshold: number | null;
  rank: number | null;
  alert: boolean;
  p10: number | null;
  p50: number | null;
  p90: number | null;
}

export interface WxSeries {
  site: string;
  indicator: string;
  label: string;
  unit: string | null;
  sens: string | null;
  threshold: number | null;
  series: WxSeriesPoint[];
  forecast: { date: string; value: number; threshold: number; rank: number | null; alert: boolean }[];
}

export interface FinSignal {
  signal: string;
  nom: string;
  famille: string;
  date_valeur: string;
  valeur_brute: number;
  indicateur: number;
  mesure: "variation_%" | "niveau";
  horizon: number;
  seuil: number | null;
  sens: "haut" | "bas";
  en_alerte: boolean;
  rang: number | null;
  niveau: string;
  unite: string;
  impact: string;
  source: string;
  source_id: string;
  nodes: { node_id: string; name: string; link: "exact" | "exposé" }[];
}

export interface FinSupplier {
  cle: string;
  nom: string;
  pays: string;
  en_alerte: boolean;
  alertes: string[];
  bourse: { "variation_20j_%": number; seuil?: number | null; en_alerte?: boolean; rang?: number | null; date_valeur?: string } | null;
  proprietaires: { type: string; nom: string; lei?: string | null; source?: string }[];
  sanctions: number;
  procedures: number;
  produit?: string;
  node?: string | null;
  node_name?: string | null;
  updated_at?: string;
  origine?: string;
}

export interface FinRule {
  id: string;
  zone: string;
  famille: string | null;
  publication: string;
  entree_en_vigueur: string | null;
  titre: string;
  effet?: string | null;
  url: string | null;
  delai_jours: number | null;
}

export interface FinanceOverview {
  ready: boolean;
  message?: string;
  kpis: {
    signals: number; signals_alert: number; score: number | null; score_date: string | null; gscpi: number | null;
    gscpi_alert: boolean; eur_usd: number | null; eur_usd_var: number | null; suppliers: number; suppliers_alert: number;
    rules_90d: number; last_value: string;
  };
  signals: FinSignal[];
  suppliers: FinSupplier[];
  rules_recent: FinRule[];
}

export interface FinSeriesPoint {
  date: string;
  valeur: number | null;
  indicateur: number | null;
  seuil: number | null;
  rang: number | null;
  alerte: boolean | null;
}

export interface FinSeries {
  signal: string;
  nom: string;
  famille: string;
  unite: string;
  sens: "haut" | "bas";
  mesure: string;
  horizon: number;
  impact: string;
  source: string;
  seuil: number | null;
  series: FinSeriesPoint[];
}

export interface StressTest {
  id: string;
  family: string;
  agent: AgentName;
  label: string;
  detail: string;
  shocks: Record<string, number>;
}

export interface HistoryRun {
  run_id: string;
  started_at: string;
  mode: string;
  scenario: string | null;
  topology: string;
  topology_name: string;
  as_of: string;
  status: string;
  global_risk_index: number;
  n_events: number;
  n_signals: number;
  n_alerts: number;
  message: string;
}

export interface HistoryEvent {
  event_id: string;
  topology: string;
  agent: AgentName;
  type: string;
  family: string | null;
  date_first: string | null;
  label: string;
  confidence: number;
  first_seen: string;
  last_seen: string;
  mode: string;
  source_ids: string[];
  nodes: string[] | null;
}

export interface NodeRiskPoint {
  run_id: string;
  as_of: string;
  mode: string;
  scenario: string | null;
  direct: number;
  propagated: number;
  risk: number;
  level: string;
}
