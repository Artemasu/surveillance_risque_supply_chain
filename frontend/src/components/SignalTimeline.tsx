// Chronologie des événements : une ligne par domaine (Médias / Finance / Météo), un point par jour.
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, Link2Off } from "lucide-react";
import { useMemo, useState } from "react";
import { useStore } from "../store";
import { AGENTS, AGENT_STYLE, frDate } from "../theme";
import type { AgentName, EventEnvelope } from "../types";
import { AGENT_ICON, AgentBadge, Empty } from "./ui";

export default function SignalTimeline({ dates }: { dates: string[] }) {
  const { events, openEvent } = useStore();
  const [sel, setSel] = useState<{ agent: AgentName; date: string } | null>(null);

  const { grid, cols } = useMemo(() => {
    const g = new Map<string, EventEnvelope[]>();
    const all = new Set(dates);
    for (const e of events?.events ?? []) {
      if (!e.event.date) continue;
      all.add(e.event.date);
      const k = `${e.agent}|${e.event.date}`;
      g.set(k, [...(g.get(k) ?? []), e]);
    }
    return { grid: g, cols: [...all].sort() };
  }, [events, dates]);

  if (!events?.events.length) return <Empty>Aucun événement daté pour l'instant.</Empty>;
  const selected = sel ? grid.get(`${sel.agent}|${sel.date}`) ?? [] : [];

  return (
    <div>
      <div className="overflow-x-auto scroll-thin">
        <div className="min-w-[480px]">
          <div className="grid items-center gap-y-2" style={{ gridTemplateColumns: `92px repeat(${cols.length}, minmax(34px, 1fr))` }}>
            <div />
            {cols.map((d) => (
              <div key={d} className="text-center text-[10px] font-medium text-ink-mute">
                {frDate(d)}
              </div>
            ))}
            {AGENTS.map((a) => {
              const s = AGENT_STYLE[a];
              const Icon = AGENT_ICON[a];
              return (
                <div key={a} className="contents">
                  <div className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: s.text }}>
                    <Icon size={13} /> {s.label}
                  </div>
                  {cols.map((d) => {
                    const list = grid.get(`${a}|${d}`);
                    const n = list?.length ?? 0;
                    const linked = list?.some((e) => e.nodes.length > 0);
                    const active = sel?.agent === a && sel.date === d;
                    return (
                      <div key={d} className="relative flex h-9 items-center justify-center">
                        <div className="absolute inset-x-0 top-1/2 h-px" style={{ background: s.bg2 }} />
                        {n > 0 && (
                          <motion.button
                            initial={{ scale: 0 }}
                            animate={{ scale: active ? 1.18 : 1 }}
                            whileHover={{ scale: 1.15 }}
                            onClick={() => setSel(active ? null : { agent: a, date: d })}
                            className="relative grid place-items-center rounded-full border-2 text-[10px] font-bold"
                            title={`${n} événement(s) ${s.label} le ${frDate(d)}${linked ? "" : " — non rattaché(s) au graphe"}`}
                            style={{
                              width: 18 + Math.min(n - 1, 4) * 4,
                              height: 18 + Math.min(n - 1, 4) * 4,
                              background: linked ? s.bg : "#fff",
                              borderColor: active ? s.text : s.border,
                              borderStyle: linked ? "solid" : "dashed",
                              color: s.text,
                            }}
                          >
                            {n > 1 ? n : ""}
                          </motion.button>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-ink-mute">Cliquez sur un point pour lister ses événements. Pointillés : événement détecté mais non rattaché à un nœud (signal faible).</p>

      <AnimatePresence>
        {sel && selected.length > 0 && (
          <motion.ul
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 space-y-1.5 overflow-hidden"
          >
            {selected.map((e) => (
              <li key={e.event.event.id}>
                <button
                  onClick={() => openEvent(e)}
                  className="group flex w-full items-center gap-3 rounded-xl border border-line bg-white px-3 py-2 text-left text-sm transition hover:border-slate-300 hover:shadow-sm"
                >
                  <AgentBadge agent={e.agent} size="xs" />
                  <span className="min-w-0 flex-1 truncate text-ink-soft">{e.event.event.label}</span>
                  {e.nodes.length === 0 ? (
                    <span className="flex items-center gap-1 text-[11px] text-ink-mute">
                      <Link2Off size={12} /> non rattaché
                    </span>
                  ) : (
                    <span className="truncate text-[11px] text-ink-mute">{e.node_names.join(", ")}</span>
                  )}
                  <ChevronRight size={15} className="text-ink-mute transition group-hover:translate-x-0.5" />
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
