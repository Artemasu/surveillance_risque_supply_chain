// Panneau What-If : nœud + gravité de panne → impact propagé, produits menacés, plan de mitigation.
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, ChevronDown, FlaskConical, Loader2, PackageX, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { dataApi } from "../api_data";
import { useStore } from "../store";
import { LEVEL_STYLE, TYPE_LABEL, fmt1, indexLevel, pct } from "../theme";
import type { NodeState, SimulationResult } from "../types";
import type { StressTest } from "../types_data";
import { Empty, LevelBadge } from "./ui";
import { FAMILY_STYLE, FamilyChip } from "./viz";

const KIND_LABEL = { reallocation: "Réallocation", route_secours: "Route de secours", stock: "Stock", surveillance: "Surveillance" } as const;

export default function WhatIfPanel({ nodes, onResult }: { nodes: NodeState[]; onResult: (r: SimulationResult | null) => void }) {
  const { whatIfNode, setWhatIfNode, openNode, run } = useStore();
  const [severity, setSeverity] = useState(80);
  const [res, setRes] = useState<SimulationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Stress tests tirés des volets Météo et Finance : plusieurs nœuds touchés en même temps
  const [tests, setTests] = useState<StressTest[]>([]);
  const [stress, setStress] = useState<StressTest | null>(null);
  useEffect(() => {
    dataApi.stressTests().then(setTests).catch(() => setTests([]));
    setStress(null);
  }, [run?.topology, run?.scenario]);
  useEffect(() => {
    if (stress && whatIfNode !== Object.keys(stress.shocks)[0]) setStress(null);    // choix manuel d'un nœud
  }, [whatIfNode, stress]);

  const pickStress = (id: string) => {
    const t = tests.find((x) => x.id === id) ?? null;
    setStress(t);
    if (t) setWhatIfNode(Object.keys(t.shocks)[0]);
  };

  useEffect(() => {
    if (!whatIfNode) {
      setRes(null);
      onResult(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setBusy(true);
      setErr(null);
      try {
        const r = stress
          ? await api.simulate(whatIfNode, stress.shocks[whatIfNode] ?? severity / 100, stress.shocks, stress.id)
          : await api.simulate(whatIfNode, severity / 100);
        if (!cancelled) {
          setRes(r);
          onResult(r);
        }
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [whatIfNode, severity, onResult, stress]);

  const families = [...new Set(tests.map((t) => t.family))];
  const nodeName = (id: string) => nodes.find((n) => n.id === id)?.name ?? id;

  const sorted = [...nodes].sort((a, b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name));
  const dIdx = res ? res.simulated_index - res.baseline_index : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-violet-50 text-violet-600 ring-1 ring-violet-100">
          <FlaskConical size={16} />
        </div>
        <div>
          <div className="text-[15px] font-bold">Simulation What-If</div>
          <div className="text-[11px] text-ink-mute">L'état réel n'est jamais modifié.</div>
        </div>
      </div>

      {tests.length > 0 && (
        <label className="block">
          <span className="label">Stress test (volets Météo et Finance)</span>
          <div className="relative mt-1.5">
            <select className="select" value={stress?.id ?? ""} onChange={(e) => (e.target.value ? pickStress(e.target.value) : (setStress(null), setWhatIfNode(null)))}>
              <option value="">— Aucun : panne d'un seul nœud —</option>
              {families.map((f) => (
                <optgroup key={f} label={FAMILY_STYLE[f]?.label ?? f}>
                  {tests.filter((t) => t.family === f).map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </optgroup>
              ))}
            </select>
            <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-mute" />
          </div>
          {stress && (
            <div className="mt-2 rounded-xl border border-violet-100 bg-violet-50/50 p-2.5 text-[11.5px] text-violet-900">
              <div className="mb-1 flex items-center gap-1.5"><FamilyChip family={stress.family} /> {stress.detail}</div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(stress.shocks).map(([n, s]) => (
                  <span key={n} className="tnum rounded-md bg-white px-1.5 py-0.5 ring-1 ring-violet-100">{nodeName(n)} · {pct(s)}</span>
                ))}
              </div>
              <div className="mt-1 text-[10.5px] text-violet-700/80">Gravités calculées comme le moteur le ferait pour un événement au centile 99,5 (liens exposés pondérés).</div>
            </div>
          )}
        </label>
      )}

      <label className="block">
        <span className="label">Nœud en panne</span>
        <div className="relative mt-1.5">
          <select className="select" value={whatIfNode ?? ""} onChange={(e) => setWhatIfNode(e.target.value || null)}>
            <option value="">— Choisir un nœud (ou cliquer sur le graphe) —</option>
            {sorted.map((n) => (
              <option key={n.id} value={n.id}>
                {TYPE_LABEL[n.type]} · {n.name}
              </option>
            ))}
          </select>
          <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-mute" />
        </div>
      </label>

      <div>
        <div className="flex items-center justify-between">
          <span className="label">Gravité de la panne</span>
          <span className="tnum text-sm font-bold" style={{ color: LEVEL_STYLE[indexLevel(severity)].color }}>
            {severity} %
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={severity}
          onChange={(e) => setSeverity(Number(e.target.value))}
          disabled={!!stress}
          title={stress ? "Gravités fixées par le stress test" : undefined}
          className={`range mt-2 w-full ${stress ? "opacity-40" : ""}`}
          style={{ ["--pct" as string]: `${severity}%`, ["--fill" as string]: LEVEL_STYLE[indexLevel(severity)].color + "88", ["--thumb" as string]: LEVEL_STYLE[indexLevel(severity)].color }}
        />
        <div className="mt-1 flex justify-between text-[10px] text-ink-mute">
          <span>perturbation légère</span>
          <span>arrêt total</span>
        </div>
      </div>

      {err && <div className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-800">{err}</div>}

      {!whatIfNode ? (
        <Empty>Sélectionnez un nœud pour visualiser l'impact propagé sur la chaîne.</Empty>
      ) : (
        <AnimatePresence mode="wait">
          {res && (
            <motion.div key={res.node_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-4">
              <div className="flex items-center gap-3 rounded-xl bg-slate-50 p-3">
                <div className="text-center">
                  <div className="text-[10px] text-ink-mute">Indice actuel</div>
                  <div className="tnum text-lg font-bold" style={{ color: LEVEL_STYLE[indexLevel(res.baseline_index)].color }}>
                    {fmt1(res.baseline_index)}
                  </div>
                </div>
                <ArrowRight size={16} className="text-ink-mute" />
                <div className="text-center">
                  <div className="text-[10px] text-ink-mute">Indice simulé</div>
                  <div className="tnum text-lg font-bold" style={{ color: LEVEL_STYLE[indexLevel(res.simulated_index)].color }}>
                    {fmt1(res.simulated_index)}
                  </div>
                </div>
                <div className="ml-auto flex items-center gap-2">
                  {busy && <Loader2 size={14} className="animate-spin text-ink-mute" />}
                  <span className="tnum rounded-full bg-white px-2.5 py-1 text-xs font-bold ring-1 ring-line">
                    {dIdx >= 0 ? "+" : ""}
                    {fmt1(dIdx)} pts
                  </span>
                </div>
              </div>

              <div>
                <div className="label mb-2">Nœuds les plus impactés</div>
                <ul className="space-y-1.5">
                  {res.impacts.filter((i) => i.delta > 0.005).slice(0, 6).map((i) => (
                    <li key={i.node_id} className="flex items-center gap-2 text-sm">
                      <span className="min-w-0 flex-1 truncate text-ink-soft">{i.name}</span>
                      <span className="tnum text-xs text-ink-mute">
                        {pct(i.baseline)} → <b style={{ color: LEVEL_STYLE[i.level].color }}>{pct(i.simulated)}</b>
                      </span>
                      <LevelBadge level={i.level} size="xs" />
                    </li>
                  ))}
                  {!res.impacts.some((i) => i.delta > 0.005) && <li className="text-xs text-ink-mute">Aucun impact propagé notable à cette gravité.</li>}
                </ul>
              </div>

              {res.threatened_products.length > 0 && (
                <div className="rounded-xl border border-orange-100 bg-orange-50/60 p-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-bold text-orange-800">
                    <PackageX size={14} /> Produits finis menacés
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {res.threatened_products.map((p) => (
                      <span key={p.node_id} className="tnum rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-orange-800 ring-1 ring-orange-100">
                        {p.name} · {pct(p.simulated)}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {res.mitigation.actions.length > 0 && (
                <div>
                  <div className="label mb-2 flex items-center gap-1.5">
                    <ShieldCheck size={13} /> Plan de mitigation proposé
                  </div>
                  <ul className="space-y-1.5">
                    {res.mitigation.actions.map((a, k) => (
                      <li key={k} className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 text-xs text-emerald-900">
                        <span className="mr-1.5 font-bold">{KIND_LABEL[a.kind]}</span>
                        {a.description}
                        {(a.capacity != null || a.lead_time_days != null) && (
                          <span className="tnum ml-1 text-emerald-700/80">
                            ({a.capacity != null ? `capacité ${pct(a.capacity)}` : ""}
                            {a.capacity != null && a.lead_time_days != null ? ", " : ""}
                            {a.lead_time_days != null ? `délai ${a.lead_time_days} j` : ""})
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex gap-2">
                <button className="btn-ghost flex-1 justify-center text-xs" onClick={() => openNode(res.node_id)}>
                  Voir les preuves du nœud
                </button>
                <button className="btn-ghost text-xs" onClick={() => setWhatIfNode(null)} title="Revenir à l'état réel">
                  <X size={14} /> Réinitialiser
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  );
}
