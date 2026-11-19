// Briques visuelles partagées : badges pastel, barres de progression, sélecteurs segmentés.
import { motion } from "framer-motion";
import { Banknote, CloudSun, Newspaper, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { AGENT_STYLE, LEVEL_STYLE } from "../theme";
import type { AgentName, RiskLevel } from "../types";

export const AGENT_ICON: Record<AgentName, LucideIcon> = { media: Newspaper, finance: Banknote, weather: CloudSun };

export function AgentBadge({ agent, count, size = "sm", muted }: { agent: AgentName; count?: number; size?: "xs" | "sm"; muted?: boolean }) {
  const s = AGENT_STYLE[agent];
  const Icon = AGENT_ICON[agent];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${size === "xs" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"} ${muted ? "opacity-50" : ""}`}
      style={{ background: s.bg, borderColor: s.border, color: s.text }}
    >
      <Icon size={size === "xs" ? 11 : 13} strokeWidth={2.2} />
      {s.label}
      {count !== undefined && <span className="tnum rounded-full bg-white/70 px-1.5 text-[11px]">{count}</span>}
    </span>
  );
}

export function LevelBadge({ level, size = "sm" }: { level: RiskLevel; size?: "xs" | "sm" }) {
  const s = LEVEL_STYLE[level];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${size === "xs" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"}`}
      style={{ background: s.bg, color: s.color }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

export function SoftBar({ value, level, height = 6 }: { value: number; level: RiskLevel; height?: number }) {
  const s = LEVEL_STYLE[level];
  return (
    <div className="w-full overflow-hidden rounded-full bg-slate-100" style={{ height }}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: `linear-gradient(90deg, ${s.color}99, ${s.color})` }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
        transition={{ type: "spring", stiffness: 120, damping: 20 }}
      />
    </div>
  );
}

export function Segmented<T extends string>({
  value, onChange, options,
}: { value: T; onChange: (v: T) => void; options: { value: T; label: string; icon?: LucideIcon }[] }) {
  return (
    <div className="relative inline-flex rounded-xl border border-line bg-slate-50 p-1">
      {options.map((o) => {
        const active = o.value === value;
        const Icon = o.icon;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`relative z-10 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors ${active ? "text-ink" : "text-ink-mute hover:text-ink-soft"}`}
          >
            {active && (
              <motion.span
                layoutId={`seg-${options.map((x) => x.value).join("-")}`}
                className="absolute inset-0 -z-10 rounded-lg bg-white shadow-sm ring-1 ring-line"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
            {Icon && <Icon size={15} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Card({ title, icon: Icon, action, children, className = "" }: { title?: string; icon?: LucideIcon; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-[15px] font-bold text-ink">
            {Icon && <Icon size={17} className="text-ink-mute" />}
            {title}
          </h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line bg-slate-50/60 px-4 py-8 text-center text-sm text-ink-mute">{children}</div>;
}
