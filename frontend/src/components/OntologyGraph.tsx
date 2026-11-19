// Graphe d'ontologie en couches (matière → fournisseur → port/hub → usine → produit), formes par type de nœud.
import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { useClickGuard } from "../clickGuard";
import { downstream, propagationEdges } from "../graphUtils";
import { LEVEL_STYLE, TYPE_LABEL, pct } from "../theme";
import type { GraphEdge, NodeState, NodeType } from "../types";

const COLUMN: Record<NodeType, number> = { matiere_premiere: 0, fournisseur: 1, port: 2, hub: 2, usine: 3, produit_fini: 4 };
const COL_TITLES = ["Matières", "Fournisseurs", "Ports & hubs", "Usines", "Produits finis"];
const W = 1000;
const ROW = 64;
const TOP = 48;

export function NodeShape({ type, r, fill, stroke, strokeWidth = 2 }: { type: NodeType; r: number; fill: string; stroke: string; strokeWidth?: number }) {
  const common = { fill, stroke, strokeWidth, strokeLinejoin: "round" as const };
  switch (type) {
    case "matiere_premiere": {
      const pts = Array.from({ length: 6 }, (_, i) => {
        const a = (Math.PI / 3) * i + Math.PI / 6;
        return `${r * Math.cos(a)},${r * Math.sin(a)}`;
      }).join(" ");
      return <polygon points={pts} {...common} />;
    }
    case "fournisseur":
      return <rect x={-r * 0.9} y={-r * 0.9} width={r * 1.8} height={r * 1.8} rx={r * 0.35} {...common} />;
    case "port":
      return <polygon points={`0,${-r * 1.1} ${r * 1.1},0 0,${r * 1.1} ${-r * 1.1},0`} {...common} />;
    case "hub":
      return <polygon points={`0,${-r * 1.05} ${r * 1.05},${r * 0.8} ${-r * 1.05},${r * 0.8}`} {...common} />;
    case "usine":
      return <polygon points={`${-r},${r * 0.85} ${-r},${-r * 0.2} 0,${-r} ${r},${-r * 0.2} ${r},${r * 0.85}`} {...common} />;
    default:
      return <circle r={r} {...common} />;
  }
}

export interface GraphProps {
  nodes: NodeState[];
  edges: GraphEdge[];
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  onDeselect: () => void;            // clic sec sur le fond vide
  impacted?: Map<string, number>;   // delta simulé par nœud, pour l'anneau d'impact
}

export default function OntologyGraph({ nodes, edges, selected, onSelect, onOpen, onDeselect, impacted }: GraphProps) {
  const guard = useClickGuard();
  const [hover, setHover] = useState<string | null>(null);

  const layout = useMemo(() => {
    const cols: NodeState[][] = [[], [], [], [], []];
    for (const n of nodes) cols[COLUMN[n.type]].push(n);
    const pos = new Map<string, { x: number; y: number }>();
    const preds = new Map<string, string[]>();
    for (const e of edges) if (!e.backup) preds.set(e.target, [...(preds.get(e.target) ?? []), e.source]);
    const rows = Math.max(...cols.map((c) => c.length), 1);
    const height = TOP + rows * ROW + 12;
    cols.forEach((col, ci) => {
      // Ordonnancement par barycentre des prédécesseurs : moins de croisements.
      if (ci > 0) {
        const bary = (n: NodeState) => {
          const ys = (preds.get(n.id) ?? []).map((p) => pos.get(p)?.y).filter((y): y is number => y !== undefined);
          return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : height / 2;
        };
        col.sort((a, b) => bary(a) - bary(b));
      } else col.sort((a, b) => b.criticality - a.criticality);
      const x = 70 + (ci * (W - 140)) / 4;
      const span = col.length * ROW;
      const y0 = TOP + (rows * ROW - span) / 2 + ROW / 2;
      col.forEach((n, i) => pos.set(n.id, { x, y: y0 + i * ROW }));
    });
    return { pos, height };
  }, [nodes, edges]);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const focus = hover ?? selected;
  const pathEdges = useMemo(() => {
    const s = new Set<string>();
    const n = focus ? byId.get(focus) : undefined;
    if (n) for (let i = 0; i < n.path.length - 1; i++) s.add(`${n.path[i]}>${n.path[i + 1]}`);
    return s;
  }, [focus, byId]);
  // Nœud sélectionné pour le What-If : sa propagation aval (jusqu'aux produits finis) s'illumine.
  const downEdges = useMemo(() => (hover ? new Set<string>() : propagationEdges(edges, selected)), [edges, selected, hover]);
  const downNodes = useMemo(() => (hover || !selected ? new Set<string>() : downstream(edges, selected)), [edges, selected, hover]);
  const pathNodes = new Set([...(focus ? byId.get(focus)?.path ?? [] : []), ...downNodes]);
  const hovered = hover ? byId.get(hover) : undefined;
  const hp = hover ? layout.pos.get(hover) : undefined;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${layout.height}`}
        className="h-auto w-full select-none"
        onPointerDown={guard.down}
        onClick={(e) => {
          // Clic sec dans le vide (ni sur un nœud, ni après un glisser) : désélection.
          if (!(e.target as Element).closest("[data-node]") && guard.isClick(e)) onDeselect();
        }}
      >
        {COL_TITLES.map((t, i) => (
          <text key={t} x={70 + (i * (W - 140)) / 4} y={20} textAnchor="middle" className="fill-slate-400 text-[11px] font-semibold uppercase tracking-wider">
            {t}
          </text>
        ))}
        {edges.map((e) => {
          const a = layout.pos.get(e.source);
          const b = layout.pos.get(e.target);
          if (!a || !b) return null;
          const down = downEdges.has(`${e.source}>${e.target}`);
          const onPath = down || pathEdges.has(`${e.source}>${e.target}`);
          const dx = (b.x - a.x) / 2;
          const d = `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
          const src = byId.get(e.source);
          const color = down ? "#EA580C" : onPath && src ? LEVEL_STYLE[src.level === "ok" ? "info" : src.level].color : "#CBD5E1";
          return (
            <path
              key={`${e.source}-${e.target}`}
              d={d}
              fill="none"
              stroke={color}
              strokeWidth={onPath ? 2.6 : 0.8 + e.dependency * 1.6}
              strokeDasharray={e.backup ? "4 5" : undefined}
              strokeOpacity={focus && !onPath ? 0.35 : onPath ? 0.95 : 0.8}
              style={{ transition: "stroke .2s, stroke-opacity .2s" }}
            />
          );
        })}
        {nodes.map((n) => {
          const p = layout.pos.get(n.id);
          if (!p) return null;
          const s = LEVEL_STYLE[n.level];
          const r = 10 + n.criticality * 8;
          const dim = focus && !pathNodes.has(n.id) && focus !== n.id;
          const delta = impacted?.get(n.id) ?? 0;
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              data-node={n.id}
              onClick={(e) => {
                // e.detail >= 2 : second clic d'un double-clic, réservé à l'ouverture des preuves.
                if (e.detail < 2 && guard.isClick(e)) onSelect(n.id);
              }}
              onDoubleClick={() => onOpen(n.id)}
              className="cursor-pointer"
              opacity={dim ? 0.45 : 1}
              style={{ transition: "opacity .2s" }}
            >
              {delta > 0.02 && (
                <motion.circle r={r + 7} fill="none" stroke={s.color} strokeWidth={1.5} strokeDasharray="2 3" animate={{ rotate: 360 }} transition={{ duration: 8, repeat: Infinity, ease: "linear" }} />
              )}
              {selected === n.id && <circle r={r + 6} fill="none" stroke="#0F172A" strokeOpacity={0.25} strokeWidth={2} />}
              <motion.g initial={{ scale: 0 }} animate={{ scale: hover === n.id ? 1.12 : 1 }} transition={{ type: "spring", stiffness: 300, damping: 20 }}>
                <NodeShape type={n.type} r={r} fill={s.bg} stroke={s.color} strokeWidth={n.level === "ok" ? 1.4 : 2.2} />
              </motion.g>
              <text y={r + 14} textAnchor="middle" className="pointer-events-none fill-slate-600 text-[10.5px] font-medium">
                {n.name.length > 22 ? `${n.name.slice(0, 21)}…` : n.name}
              </text>
            </g>
          );
        })}
      </svg>

      {hovered && hp && (
        <div
          className="pointer-events-none absolute z-10 w-64 rounded-xl border border-line bg-white p-3 text-xs shadow-soft"
          style={{
            left: `${(hp.x / W) * 100}%`,
            top: `${(hp.y / layout.height) * 100}%`,
            transform: `translate(${hp.x > W * 0.7 ? "calc(-100% - 18px)" : "18px"}, -50%)`,
          }}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-bold text-ink">{hovered.name}</span>
            <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ background: LEVEL_STYLE[hovered.level].bg, color: LEVEL_STYLE[hovered.level].color }}>
              {LEVEL_STYLE[hovered.level].label}
            </span>
          </div>
          <div className="mt-0.5 text-ink-mute">
            {TYPE_LABEL[hovered.type]}
            {hovered.place ? ` · ${hovered.place}` : ""}
            {hovered.country ? `, ${hovered.country}` : ""}
          </div>
          <div className="tnum mt-2 grid grid-cols-3 gap-1 text-center">
            {[
              ["Total", hovered.risk],
              ["Direct", hovered.direct],
              ["Propagé", hovered.propagated],
            ].map(([k, v]) => (
              <div key={k as string} className="rounded-lg bg-slate-50 py-1">
                <div className="text-[10px] text-ink-mute">{k}</div>
                <div className="font-bold text-ink">{pct(v as number)}</div>
              </div>
            ))}
          </div>
          <div className="mt-2 text-ink-mute">
            Criticité {pct(hovered.criticality)} · stock {hovered.stock_days} j
          </div>
          {hovered.path.length > 1 && <div className="mt-1 text-ink-soft">Chemin : {hovered.path.map((id) => byId.get(id)?.name ?? id).join(" → ")}</div>}
          <div className="mt-2 text-[10px] text-ink-mute">Clic : sélectionner pour le what-if · double-clic : preuves</div>
        </div>
      )}
    </div>
  );
}

export function ShapeLegend() {
  const types: NodeType[] = ["matiere_premiere", "fournisseur", "port", "hub", "usine", "produit_fini"];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-ink-mute">
      {types.map((t) => (
        <span key={t} className="inline-flex items-center gap-1.5">
          <svg width="16" height="16" viewBox="-9 -9 18 18">
            <NodeShape type={t} r={6} fill="#F1F5F9" stroke="#94A3B8" strokeWidth={1.4} />
          </svg>
          {TYPE_LABEL[t]}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <svg width="22" height="8">
          <line x1="0" x2="22" y1="4" y2="4" stroke="#CBD5E1" strokeWidth="1.5" strokeDasharray="4 4" />
        </svg>
        Lien de secours
      </span>
    </div>
  );
}
