// Vue « Chaîne & simulation » : graphe (colonnes 2D ou orbites 3D) / carte (plan 2D ou globe 3D) / tableau,
// + panneau What-If intégré. Les vues 3D et la carte sont chargées à la demande (three.js, MapLibre).
import { AnimatePresence, motion } from "framer-motion";
import { Box, FlaskConical, Globe2, Loader2, Network, Rows3, Table2 } from "lucide-react";
import { Suspense, lazy, useCallback, useMemo, useState } from "react";
import { useStore } from "../store";
import { LEVEL_ORDER, LEVEL_STYLE } from "../theme";
import type { SimulationResult } from "../types";
import ChainTable from "./ChainTable";
import OntologyGraph, { ShapeLegend } from "./OntologyGraph";
import WhatIfPanel from "./WhatIfPanel";
import { Empty, Segmented } from "./ui";

const MapView = lazy(() => import("./MapView"));
const OrbitalGraph = lazy(() => import("./OrbitalGraph"));

type Tab = "graph" | "map" | "table";

function Loading({ label }: { label: string }) {
  return (
    <div className="grid h-[520px] place-items-center rounded-xl bg-slate-50 text-sm text-ink-mute ring-1 ring-line">
      <span className="inline-flex items-center gap-2">
        <Loader2 size={15} className="animate-spin" /> {label}
      </span>
    </div>
  );
}

export default function ChainView() {
  const { state, events, run, whatIfNode, setWhatIfNode, openNode } = useStore();
  const [tab, setTab] = useState<Tab>("graph");
  const [graphMode, setGraphMode] = useState<"2d" | "3d">("2d");
  const [sim, setSim] = useState<SimulationResult | null>(null);
  const onResult = useCallback((r: SimulationResult | null) => setSim(r), []);

  const nodes = sim?.nodes ?? state?.nodes ?? [];
  const impacted = useMemo(() => new Map((sim?.impacts ?? []).map((i) => [i.node_id, i.delta])), [sim]);

  if (!state) return <Empty>Lancez une analyse pour afficher la chaîne d'approvisionnement.</Empty>;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="card min-w-0 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: "graph", label: "Graphe", icon: Network },
              { value: "map", label: "Carte", icon: Globe2 },
              { value: "table", label: "Tableau", icon: Table2 },
            ]}
          />
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-mute">
            {sim && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-2.5 py-1 font-semibold text-violet-700 ring-1 ring-violet-100">
                <FlaskConical size={12} /> Vue simulée : {sim.node_name} à {Math.round(sim.severity * 100)} %
              </span>
            )}
            {LEVEL_ORDER.map((l) => (
              <span key={l} className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ background: LEVEL_STYLE[l].color }} />
                {LEVEL_STYLE[l].label}
              </span>
            ))}
            {tab === "graph" && (
              <Segmented
                value={graphMode}
                onChange={setGraphMode}
                options={[
                  { value: "2d", label: "2D", icon: Rows3 },
                  { value: "3d", label: "3D", icon: Box },
                ]}
              />
            )}
          </div>
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={`${tab}-${graphMode}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
            {tab === "graph" && graphMode === "2d" && (
              <>
                <OntologyGraph nodes={nodes} edges={state.edges} selected={whatIfNode} onSelect={setWhatIfNode} onOpen={openNode} impacted={impacted} />
                <div className="mt-3">
                  <ShapeLegend />
                </div>
              </>
            )}
            {tab === "graph" && graphMode === "3d" && (
              <Suspense fallback={<Loading label="Chargement de la vue orbitale 3D…" />}>
                <OrbitalGraph
                  nodes={nodes}
                  edges={state.edges}
                  signals={events?.signals ?? []}
                  companyName={run?.topology_name || "Entreprise"}
                  selected={whatIfNode}
                  onSelect={setWhatIfNode}
                  onOpen={openNode}
                />
              </Suspense>
            )}
            {tab === "map" && (
              <Suspense fallback={<Loading label="Chargement de la carte…" />}>
                <MapView nodes={nodes} edges={state.edges} selected={whatIfNode} onSelect={setWhatIfNode} onOpen={openNode} />
              </Suspense>
            )}
            {tab === "table" && <ChainTable nodes={nodes} onOpen={openNode} />}
          </motion.div>
        </AnimatePresence>
        <p className="mt-3 text-[11px] text-ink-mute">
          Survolez un nœud pour voir son chemin de propagation. Clic : le simuler dans le panneau What-If (la propagation aval s'illumine) · double-clic : ouvrir ses preuves.
        </p>
      </section>
      <aside className="card h-fit p-5 xl:sticky xl:top-28">
        <WhatIfPanel nodes={state.nodes} onResult={onResult} />
      </aside>
    </div>
  );
}
