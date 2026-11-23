// Page « Historique & replay » : chaque exécution du pipeline est enregistrée dans la base unifiée.
// Indice global et risque d'un nœud dans le temps, flux d'événements des trois agents, comparaison de deux exécutions.
import { Database, GitCompareArrows, History, ListFilter, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dataApi } from "../api_data";
import { useStore } from "../store";
import { AGENT_STYLE, LEVEL_STYLE, frDate } from "../theme";
import type { AgentName, RiskLevel } from "../types";
import { AgentBadge, Card, Empty } from "./ui";
import { AXIS, ChartTip, FamilyChip, GRID, Kpi, SERIES, num, pct0, signed, useAsync } from "./viz";

const MODE_LABEL = (m: string, s: string | null) => (m === "live" ? "Live" : `Replay ${s ?? ""}`);

export default function HistoryPage() {
  const { state, run } = useStore();
  const topology = run?.topology ?? "topology.yaml";
  const [node, setNode] = useState<string>("");
  const [agent, setAgent] = useState<string>("");
  const [family, setFamily] = useState<string>("");
  const [cmp, setCmp] = useState<{ a: string; b: string }>({ a: "", b: "" });
  const runs = useAsync(() => dataApi.runs(200), [run?.as_of, run?.global_risk_index]);
  const risk = useAsync(() => dataApi.risk(node || undefined, topology), [node, topology, run?.as_of]);
  const events = useAsync(() => dataApi.historyEvents({ agent: agent || undefined, family: family || undefined, topology, limit: 200 }), [agent, family, topology, run?.as_of]);
  const compare = useAsync(() => (cmp.a && cmp.b ? dataApi.compare(cmp.a, cmp.b) : Promise.resolve(null)), [cmp.a, cmp.b]);

  const sameTopo = (runs.data ?? []).filter((r) => r.topology === topology);
  // une courbe par mode (live, chaque scénario) : un replay et le live ne se mélangent pas
  const series = useMemo(() => {
    const byKey = new Map<string, Map<string, number>>();
    for (const p of risk.data?.global ?? []) {
      const key = MODE_LABEL(p.mode, p.scenario);
      if (!byKey.has(key)) byKey.set(key, new Map());
      byKey.get(key)!.set(p.as_of, p.global_risk_index);
    }
    const dates = [...new Set((risk.data?.global ?? []).map((p) => p.as_of))].sort();
    return { keys: [...byKey.keys()], rows: dates.map((d) => Object.fromEntries([["date", d], ...[...byKey].map(([k, m]) => [k, m.get(d) ?? null])])) };
  }, [risk.data]);

  const nodeRows = (risk.data?.node ?? []).map((p) => ({ date: p.as_of, risque: Math.round(p.risk * 1000) / 10, direct: Math.round(p.direct * 1000) / 10, propagé: Math.round(p.propagated * 1000) / 10 }));
  const last = sameTopo[0];

  if (runs.data && runs.data.length === 0) {
    return <Empty>Aucune exécution enregistrée pour l'instant : lancez une analyse (live ou replay), elle sera conservée ici.</Empty>;
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-extrabold tracking-tight">Historique & replay</h1>
        <p className="text-sm text-ink-mute">Chaque exécution (live ou replay) est enregistrée dans la base unifiée : on retrouve ce que l'on savait à chaque date.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <Kpi icon={Database} label="Exécutions enregistrées" value={sameTopo.length} sub={`chaîne : ${last?.topology_name || topology}`} />
        <Kpi icon={TrendingUp} label="Dernier indice" value={num(last?.global_risk_index)} unit="/ 100" sub={last ? `au ${frDate(last.as_of, { day: "numeric", month: "long", year: "numeric" })}` : ""} />
        <Kpi icon={History} label="Événements conservés" value={(events.data ?? []).length} sub={agent || family ? "avec les filtres" : "200 plus récents"} />
        <Kpi icon={ListFilter} label="Alertes (dernière exécution)" value={last?.n_alerts ?? 0} tone={last?.n_alerts ? "alert" : "ok"} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Indice global au fil des exécutions" icon={TrendingUp}>
          {series.rows.length === 0 ? <Empty>Pas encore de point.</Empty> : (
            <div className="h-[240px]">
              <ResponsiveContainer>
                <LineChart data={series.rows} margin={{ top: 8, right: 12, left: -14, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => frDate(d)} minTickGap={30} />
                  <YAxis {...AXIS} domain={[0, "auto"]} />
                  <Tooltip content={<ChartTip unit="/ 100" fmtLabel={(d) => frDate(d, { day: "numeric", month: "long", year: "numeric" })} />} />
                  {series.keys.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />}
                  <ReferenceLine y={35} stroke={LEVEL_STYLE.warning.color} strokeDasharray="4 4" />
                  {series.keys.map((k, i) => <Line key={k} dataKey={k} name={k} stroke={SERIES[i % SERIES.length]} strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Risque d'un nœud" icon={TrendingUp} action={
          <select className="select !w-56 !py-1 text-xs" value={node} onChange={(e) => setNode(e.target.value)}>
            <option value="">— choisir un nœud —</option>
            {(state?.nodes ?? []).slice().sort((a, b) => b.risk - a.risk).map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
          </select>
        }>
          {!node ? (
            <ul className="space-y-1.5">
              {(risk.data?.top ?? []).map((n) => (
                <li key={n.node_id}>
                  <button onClick={() => setNode(n.node_id)} className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1 text-left text-[12.5px] hover:bg-slate-50">
                    <span className="truncate font-semibold">{n.name}</span>
                    <span className="flex items-center gap-1">{(n.families ?? []).map((f) => <FamilyChip key={f} family={f} />)}</span>
                    <span className="tnum font-bold" style={{ color: LEVEL_STYLE[(n.level as RiskLevel) ?? "ok"].color }}>{pct0(n.risk)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : nodeRows.length === 0 ? <Empty>Ce nœud n'apparaît dans aucune exécution enregistrée.</Empty> : (
            <div className="h-[240px]">
              <ResponsiveContainer>
                <LineChart data={nodeRows} margin={{ top: 8, right: 12, left: -14, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => frDate(d)} />
                  <YAxis {...AXIS} domain={[0, 100]} />
                  <Tooltip content={<ChartTip unit="%" />} />
                  <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />
                  <Line dataKey="risque" name="Risque total" stroke={SERIES[0]} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  <Line dataKey="direct" name="Direct" stroke={SERIES[1]} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                  <Line dataKey="propagé" name="Propagé" stroke={SERIES[2]} strokeWidth={1.5} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <Card title="Flux d'événements des trois agents" icon={ListFilter} action={
        <div className="flex gap-2">
          <select className="select !w-32 !py-1 text-xs" value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">Tous agents</option>
            {(["media", "weather", "finance"] as AgentName[]).map((a) => <option key={a} value={a}>{AGENT_STYLE[a].label}</option>)}
          </select>
          <select className="select !w-40 !py-1 text-xs" value={family} onChange={(e) => setFamily(e.target.value)}>
            <option value="">Toutes familles</option>
            {["climat", "marche", "reglementaire", "financier", "operations", "approvisionnement", "cyber"].map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
      }>
        {(events.data ?? []).length === 0 ? <Empty>Aucun événement avec ces filtres.</Empty> : (
          <ul className="max-h-[380px] divide-y divide-line overflow-y-auto pr-1">
            {(events.data ?? []).map((e) => (
              <li key={`${e.event_id}-${e.mode}`} className="flex items-start gap-3 py-2">
                <span className="tnum w-20 shrink-0 text-[11.5px] font-semibold text-ink-soft">{frDate(e.date_first, { day: "numeric", month: "short", year: "2-digit" })}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] leading-snug">{e.label}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-ink-mute">
                    <AgentBadge agent={e.agent} size="xs" />
                    {e.family && <FamilyChip family={e.family} />}
                    <span>{e.mode === "live" ? "live" : e.mode.replace("replay:", "replay ")}</span>
                    <span>· vu du {frDate(e.first_seen.slice(0, 10))} au {frDate(e.last_seen.slice(0, 10))}</span>
                    {e.nodes?.length ? <span>· {e.nodes.length} nœud(s)</span> : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Comparer deux exécutions" icon={GitCompareArrows}>
        <div className="flex flex-wrap gap-2">
          {(["a", "b"] as const).map((k) => (
            <select key={k} className="select !w-80 !py-1 text-xs" value={cmp[k]} onChange={(e) => setCmp((c) => ({ ...c, [k]: e.target.value }))}>
              <option value="">{k === "a" ? "Avant…" : "Après…"}</option>
              {sameTopo.map((r) => (
                <option key={r.run_id} value={r.run_id}>{frDate(r.as_of, { day: "numeric", month: "short", year: "numeric" })} · {MODE_LABEL(r.mode, r.scenario)} · indice {num(r.global_risk_index)}</option>
              ))}
            </select>
          ))}
        </div>
        {compare.data && (
          <table className="mt-3 w-full text-[12.5px]">
            <thead className="text-left text-[11px] text-ink-mute"><tr><th className="py-1">Nœud</th><th className="text-right">Avant</th><th className="text-right">Après</th><th className="text-right">Écart</th></tr></thead>
            <tbody>
              {compare.data.nodes.filter((n) => Math.abs(n.delta) > 0.005).slice(0, 15).map((n) => (
                <tr key={n.node_id} className="tnum border-t border-line">
                  <td className="py-1.5 font-semibold">{n.name}</td>
                  <td className="text-right">{pct0(n.before)}</td>
                  <td className="text-right">{pct0(n.after)}</td>
                  <td className="text-right font-bold" style={{ color: n.delta > 0 ? LEVEL_STYLE.warning.color : LEVEL_STYLE.ok.color }}>{signed(n.delta * 100, 0)} pts</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
