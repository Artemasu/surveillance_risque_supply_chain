// Briques de visualisation partagées par les pages Météo, Finance et Historique.
// Palette : catégorielle à ordre fixe (jamais recyclée), séquentielle bleue pour les rangs, statuts réservés aux niveaux.
import { motion } from "framer-motion";
import { Loader2, RefreshCw, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

/** Ordre catégoriel fixe (palette de référence validée daltonisme) : la couleur suit l'entité, jamais son rang. */
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];

/** Rampe séquentielle (un seul ton, clair -> foncé) pour les rangs 0,5 -> 1. */
const SEQ = ["#f1f5f9", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
export function rankColor(rank: number | null | undefined): string {
  if (rank == null) return "#f8fafc";
  if (rank < 0.5) return SEQ[0];
  const steps = [0.7, 0.8, 0.9, 0.95, 0.98, 0.99];
  const passed = steps.filter((s) => rank >= s).length;        // 0 à 6 paliers franchis
  return SEQ[Math.min(SEQ.length - 1, 1 + passed)];
}
export const rankInk = (rank: number | null | undefined) => (rank != null && rank >= 0.95 ? "#ffffff" : "#334155");

/** Statuts (réservés, toujours avec icône ou libellé). */
export const STATUS = { ok: "#10B981", watch: "#D97706", alert: "#EA580C", critical: "#BE123C" };

/** Familles d'aléa du moteur de graphe. */
export const FAMILY_STYLE: Record<string, { label: string; color: string; bg: string; emoji: string }> = {
  climat: { label: "Climat", color: "#0f766e", bg: "#ccfbf1", emoji: "☔" },
  marche: { label: "Marché", color: "#b45309", bg: "#fef3c7", emoji: "💸" },
  reglementaire: { label: "Réglementaire", color: "#7c3aed", bg: "#ede9fe", emoji: "⚖️" },
  financier: { label: "Financier", color: "#be123c", bg: "#ffe4e6", emoji: "📉" },
  operations: { label: "Opérations", color: "#c2410c", bg: "#ffedd5", emoji: "✊" },
  cyber: { label: "Cyber", color: "#1d4ed8", bg: "#dbeafe", emoji: "🛡️" },
  approvisionnement: { label: "Approvisionnement", color: "#4d7c0f", bg: "#ecfccb", emoji: "📦" },
};

export const pct0 = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)} %`);
export const pct1 = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`);
export const num = (v: number | null | undefined, d = 1) =>
  v == null || Number.isNaN(v) ? "—" : v.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: d });
export const signed = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v > 0 ? "+" : ""}${num(v, d)}`);

/** Rang lisible : « 1 % des jours les plus extrêmes ». */
export function rankText(rank: number | null | undefined): string {
  if (rank == null) return "rang inconnu";
  const top = Math.max(0.1, (1 - rank) * 100);
  if (rank < 0.5) return "valeur courante";
  return `parmi les ${top < 1 ? top.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) : Math.round(top)} % les plus extrêmes`;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError((e as Error).message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function Kpi({ icon: Icon, label, value, unit, sub, tone = "ink", onClick }: {
  icon: LucideIcon; label: string; value: ReactNode; unit?: string; sub?: ReactNode; tone?: "ink" | "alert" | "ok" | "watch"; onClick?: () => void;
}) {
  const color = tone === "alert" ? STATUS.alert : tone === "ok" ? STATUS.ok : tone === "watch" ? STATUS.watch : "#0f172a";
  const Tag = onClick ? "button" : "div";
  return (
    <Tag onClick={onClick} className={`card p-4 text-left ${onClick ? "transition hover:border-slate-300 hover:shadow-soft" : ""}`}>
      <div className="label flex items-center gap-1.5">
        <Icon size={13} /> {label}
      </div>
      <div className="mt-2 flex items-end gap-1.5">
        <span className="tnum text-[28px] font-extrabold leading-none tracking-tight" style={{ color }}>
          {value}
        </span>
        {unit && <span className="pb-0.5 text-xs font-medium text-ink-mute">{unit}</span>}
      </div>
      {sub && <div className="mt-1.5 text-[11.5px] leading-snug text-ink-mute">{sub}</div>}
    </Tag>
  );
}

/** Jauge de rang : position de la valeur dans l'historique de calibration, repère au seuil. */
export function RankGauge({ rank, alert, threshold = 0.99 }: { rank: number | null; alert: boolean; threshold?: number }) {
  return (
    <div className="relative h-1.5 w-full overflow-visible rounded-full bg-slate-100" title={rankText(rank)}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: alert ? STATUS.alert : "#3987e5" }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(2, (rank ?? 0) * 100)}%` }}
        transition={{ type: "spring", stiffness: 120, damping: 20 }}
      />
      <span className="absolute -top-0.5 h-2.5 w-0.5 rounded bg-slate-400" style={{ left: `${threshold * 100}%` }} />
    </div>
  );
}

export function AlertPill({ alert, label }: { alert: boolean; label?: string }) {
  return alert ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2 py-0.5 text-[11px] font-semibold text-orange-700 ring-1 ring-orange-100">
      <span className="h-1.5 w-1.5 rounded-full bg-orange-500" /> {label ?? "Alerte"}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> {label ?? "Normal"}
    </span>
  );
}

export function FamilyChip({ family }: { family: string }) {
  const f = FAMILY_STYLE[family] ?? { label: family, color: "#475569", bg: "#f1f5f9", emoji: "•" };
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: f.bg, color: f.color }}>
      <span aria-hidden>{f.emoji}</span> {f.label}
    </span>
  );
}

export function JobButton({ label, run, onDone }: { label: string; run: () => Promise<unknown>; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="flex items-center gap-2">
      {msg && <span className="max-w-[320px] truncate text-[11px] text-ink-mute" title={msg}>{msg}</span>}
      <button
        className="btn-ghost"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setMsg(null);
          try {
            await run();
            setMsg("Mis à jour.");
            onDone();
          } catch (e) {
            setMsg((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        {busy ? "Collecte en cours…" : label}
      </button>
    </div>
  );
}

/** Info-bulle Recharts sobre : valeurs en encre, pastille de couleur pour l'identité. */
export function ChartTip({ active, payload, label, unit, fmtLabel }: {
  active?: boolean; payload?: any[]; label?: string; unit?: string; fmtLabel?: (l: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-line bg-white/95 px-3 py-2 text-xs shadow-soft">
      <div className="mb-1 font-semibold text-ink">{fmtLabel ? fmtLabel(String(label)) : label}</div>
      {payload
        .filter((p) => p.value != null && !String(p.dataKey).startsWith("_"))
        .map((p) => (
          <div key={String(p.dataKey)} className="flex items-center gap-2 text-ink-soft">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color ?? p.stroke }} />
            <span>{p.name}</span>
            <span className="tnum ml-auto pl-3 font-semibold text-ink">
              {Array.isArray(p.value) ? `${num(p.value[0])} – ${num(p.value[1])}` : num(p.value, 2)} {unit ?? ""}
            </span>
          </div>
        ))}
    </div>
  );
}

export const AXIS = { stroke: "#94a3b8", fontSize: 11, tickLine: false, axisLine: false } as const;
export const GRID = { stroke: "#eef2f6", vertical: false } as const;

export function NotReady({ message }: { message?: string }) {
  return (
    <div className="card mx-auto max-w-2xl p-8 text-center">
      <h2 className="text-lg font-bold">Pas encore de données</h2>
      <p className="mt-2 text-sm text-ink-soft">{message ?? "La base unifiée est vide."}</p>
      <pre className="mt-4 rounded-xl bg-slate-50 p-3 text-left text-xs text-ink-soft">python -m src.jobs import-notebooks</pre>
    </div>
  );
}
