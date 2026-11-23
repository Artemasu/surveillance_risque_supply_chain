// Vue « Tour de contrôle » : synthèse en langage clair, 3 indicateurs, courbe + chronologie, alertes prioritaires.
import { motion } from "framer-motion";
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, BellRing, Info, LineChart, Minus, Radar, ScrollText, Target,
} from "lucide-react";
import { useMemo } from "react";
import { useStore } from "../store";
import { AGENTS, AGENT_STYLE, LEVEL_STYLE, TYPE_LABEL, fmt1, indexLevel, pct } from "../theme";
import type { AgentName, RiskLevel } from "../types";
import AdviceStrip from "./AdviceStrip";
import RiskChart from "./RiskChart";
import SignalTimeline from "./SignalTimeline";
import { AgentBadge, Card, Empty, LevelBadge, SoftBar } from "./ui";
import VoletsStrip from "./VoletsStrip";

const LEVEL_WORD: Record<RiskLevel, string> = { ok: "Risque faible", info: "Risque modéré", warning: "Risque élevé", critical: "Risque critique" };
const TYPE_PLURAL: Record<string, string> = {
  matiere_premiere: "matière(s) première(s)", fournisseur: "fournisseur(s)", port: "port(s)", hub: "hub(s)", usine: "usine(s)", produit_fini: "produit(s) fini(s)",
};

function Synthesis() {
  const { run, state, alerts } = useStore();
  if (!run || !state) return null;
  const idx = state.global_risk_index;
  const lvl = indexLevel(idx);
  const style = LEVEL_STYLE[lvl];
  const serious = alerts.filter((a) => a.level === "warning" || a.level === "critical");
  const byType = serious.reduce<Record<string, number>>((m, a) => ({ ...m, [a.node_type]: (m[a.node_type] ?? 0) + 1 }), {});
  const parts = Object.entries(byType).map(([t, n]) => `${n} ${TYPE_PLURAL[t] ?? t}`);
  const tail = serious.length
    ? `${parts.join(", ")} en alerte ${serious.length > 1 ? "nécessitent" : "nécessite"} votre attention`
    : alerts.length
      ? `${alerts.length} point(s) à surveiller, aucune alerte franche`
      : "aucune alerte active, la chaîne est fluide";
  const failed = Object.entries(run.agents).filter(([, a]) => a.status !== "success").map(([k]) => AGENT_STYLE[k as AgentName]?.label ?? k);
  const partial = Object.entries(run.agents).filter(([, a]) => a.status === "success" && a.degraded).map(([k]) => AGENT_STYLE[k as AgentName]?.label ?? k);

  return (
    <div className="space-y-2.5">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        key={`${run.as_of}-${idx}`}
        className="card flex items-start gap-4 overflow-hidden p-5"
        style={{ background: `linear-gradient(100deg, ${style.bg} 0%, #ffffff 60%)` }}
      >
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-white shadow-sm ring-1 ring-line" style={{ color: style.color }}>
          <Radar size={22} />
        </div>
        <div className="min-w-0">
          <p className="text-lg font-semibold leading-snug text-ink sm:text-xl">
            <span style={{ color: style.color }}>{LEVEL_WORD[lvl]}</span>{" "}
            <span className="tnum">({fmt1(idx)}/100)</span> sur <span className="font-bold">{run.topology_name || "la chaîne par défaut"}</span> — {tail}.
          </p>
          <p className="mt-1 text-sm text-ink-mute">
            {run.mode === "replay" ? `Replay · jour ${run.day}/${run.days_total}` : "Live"} · situation au {run.as_of} · {run.n_events} événement(s), {run.n_signals} signal(aux)
            corrélé(s)
          </p>
        </div>
      </motion.div>
      <AdviceStrip />
      {(failed.length > 0 || partial.length > 0) && (
        <div className="flex items-start gap-2.5 rounded-xl border border-sky-100 bg-sky-50/70 px-4 py-2.5 text-sm text-sky-900">
          <Info size={16} className="mt-0.5 shrink-0" />
          <span>
            {failed.length > 0 && <>Source(s) indisponible(s) : <b>{failed.join(", ")}</b>. </>}
            {partial.length > 0 && <>Collecte partielle : <b>{partial.join(", ")}</b>. </>}
            Le résultat est incomplet — ce n'est pas une absence de risque.
          </span>
        </div>
      )}
      {run.fictional && (
        <div className="flex items-center gap-2.5 rounded-xl border border-line bg-white px-4 py-2 text-xs text-ink-mute">
          <ScrollText size={14} /> Scénario fictif écrit pour la démonstration : articles, mesures et entreprises sont inventés.
        </div>
      )}
    </div>
  );
}

function Kpis() {
  const { run, state, events, openNode } = useStore();
  const prev = run && run.timeline.length >= 2 ? run.timeline[run.timeline.length - 2].global_risk_index : null;
  const idx = state?.global_risk_index ?? 0;
  const delta = prev === null ? null : idx - prev;
  const top = useMemo(() => [...(state?.nodes ?? [])].sort((a, b) => b.risk - a.risk)[0], [state]);
  const counts = useMemo(() => {
    const c: Record<AgentName, number> = { media: 0, finance: 0, weather: 0 };
    for (const s of events?.signals ?? []) for (const a of s.agents) c[a] += 1;
    return c;
  }, [events]);
  const total = (events?.signals ?? []).length;
  const lvl = indexLevel(idx);

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="card p-5">
        <div className="label flex items-center gap-1.5">
          <Activity size={13} /> Indice de risque global
        </div>
        <div className="mt-3 flex items-end gap-3">
          <span className="tnum text-4xl font-extrabold tracking-tight" style={{ color: LEVEL_STYLE[lvl].color }}>
            {fmt1(idx)}
          </span>
          <span className="pb-1.5 text-sm font-medium text-ink-mute">/ 100</span>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <LevelBadge level={lvl} />
          {delta !== null && (
            <span className={`tnum inline-flex items-center gap-1 text-xs font-semibold ${Math.abs(delta) < 0.05 ? "text-ink-mute" : delta > 0 ? "text-orange-600" : "text-emerald-600"}`}>
              {Math.abs(delta) < 0.05 ? <Minus size={13} /> : delta > 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
              {delta > 0 ? "+" : ""}
              {fmt1(delta)} vs veille
            </span>
          )}
        </div>
      </div>

      <button onClick={() => top && openNode(top.id)} disabled={!top || top.risk < 0.01} className="card group p-5 text-left transition hover:border-slate-300 hover:shadow-soft disabled:pointer-events-none">
        <div className="label flex items-center gap-1.5">
          <Target size={13} /> Nœud le plus exposé
        </div>
        {top && top.risk >= 0.01 ? (
          <>
            <div className="mt-3 truncate text-lg font-bold text-ink">{top.name}</div>
            <div className="text-xs text-ink-mute">
              {TYPE_LABEL[top.type]}
              {top.place ? ` · ${top.place}` : ""}
              {top.country ? `, ${top.country}` : ""}
            </div>
            <div className="mt-3 flex items-center gap-3">
              <SoftBar value={top.risk} level={top.level} />
              <span className="tnum whitespace-nowrap text-sm font-bold" style={{ color: LEVEL_STYLE[top.level].color }}>
                {pct(top.risk)}
              </span>
            </div>
            <div className="mt-2 flex items-center gap-1 text-xs font-semibold text-ink-mute group-hover:text-ink-soft">
              Voir les preuves <ArrowRight size={13} className="transition group-hover:translate-x-0.5" />
            </div>
          </>
        ) : (
          <div className="mt-3 text-sm text-ink-mute">Aucun nœud exposé.</div>
        )}
      </button>

      <div className="card p-5">
        <div className="label flex items-center gap-1.5">
          <BellRing size={13} /> Signaux actifs
        </div>
        <div className="mt-3 flex items-end gap-2">
          <span className="tnum text-4xl font-extrabold tracking-tight">{total}</span>
          <span className="pb-1.5 text-sm text-ink-mute">signal(aux) corrélé(s)</span>
        </div>
        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-slate-100">
          {AGENTS.map((a) => {
            const sum = counts.media + counts.finance + counts.weather;
            return sum ? <motion.div key={a} initial={{ width: 0 }} animate={{ width: `${(counts[a] / sum) * 100}%` }} style={{ background: AGENT_STYLE[a].border }} /> : null;
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {AGENTS.map((a) => (
            <AgentBadge key={a} agent={a} count={counts[a]} muted={!counts[a]} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PriorityList() {
  const { alerts, state, openNode } = useStore();
  const items = useMemo(() => [...alerts].sort((a, b) => b.priority - a.priority), [alerts]);
  const nodes = new Map((state?.nodes ?? []).map((n) => [n.id, n]));
  if (!items.length) return <Empty>Aucune alerte active. Les nœuds restent sous surveillance.</Empty>;
  return (
    <ul className="space-y-2.5">
      {items.slice(0, 8).map((a, i) => {
        const node = nodes.get(a.node_id);
        return (
          <motion.li key={a.id} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}>
            <div className="rounded-xl border border-line bg-white p-3.5 transition hover:border-slate-300 hover:shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-ink">{a.node_name}</div>
                  <div className="text-xs text-ink-mute">
                    {TYPE_LABEL[a.node_type]}
                    {node?.place ? ` · ${node.place}` : ""}
                  </div>
                </div>
                <LevelBadge level={a.level} size="xs" />
              </div>
              <div className="mt-3 flex items-center gap-3">
                <SoftBar value={a.risk} level={a.level} />
                <span className="tnum w-11 shrink-0 whitespace-nowrap text-right text-sm font-bold" style={{ color: LEVEL_STYLE[a.level].color }}>
                  {pct(a.risk)}
                </span>
              </div>
              <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  {a.agents.map((ag) => (
                    <AgentBadge key={ag} agent={ag} size="xs" />
                  ))}
                  <span className="tnum text-[11px] text-ink-mute">
                    direct {pct(a.direct)} · propagé {pct(a.propagated)}
                  </span>
                </div>
                <button onClick={() => openNode(a.node_id)} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-sky-700 transition hover:bg-sky-50">
                  Voir les preuves <ArrowRight size={13} />
                </button>
              </div>
            </div>
          </motion.li>
        );
      })}
      {items.length > 8 && <li className="text-center text-xs text-ink-mute">+ {items.length - 8} autre(s) alerte(s) dans l'onglet Chaîne</li>}
    </ul>
  );
}

export default function Dashboard() {
  const { run } = useStore();
  const dates = (run?.timeline ?? []).map((p) => p.date);
  return (
    <div className="space-y-5">
      <Synthesis />
      <Kpis />
      <VoletsStrip />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card title="Évolution de l'indice de risque" icon={LineChart} action={run?.mode === "replay" ? <span className="text-[11px] text-ink-mute">recalculé avec ce qui était connu chaque jour</span> : undefined}>
            <RiskChart points={run?.timeline ?? []} />
          </Card>
          <Card title="Chronologie des signaux" icon={Activity}>
            <SignalTimeline dates={dates} />
          </Card>
        </div>
        <Card title="Alertes & nœuds prioritaires" icon={BellRing}>
          <PriorityList />
        </Card>
      </div>
    </div>
  );
}
