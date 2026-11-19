// Carte mondiale claire : hubs géolocalisés et routes logistiques (arcs géodésiques), projection Natural Earth.
import { geoGraticule10, geoNaturalEarth1, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { useMemo, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import world from "world-atlas/countries-110m.json";
import { LEVEL_STYLE, TYPE_LABEL, pct } from "../theme";
import type { GraphEdge, NodeState } from "../types";
import { NodeShape } from "./OntologyGraph";

const W = 1000;
const H = 520;

const topo = world as unknown as Topology<{ countries: GeometryCollection }>;
const LAND = feature(topo, topo.objects.countries) as FeatureCollection<Geometry>;

export default function WorldMap({ nodes, edges, selected, onSelect, onOpen }: {
  nodes: NodeState[]; edges: GraphEdge[]; selected: string | null; onSelect: (id: string) => void; onOpen: (id: string) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const geo = nodes.filter((n) => n.lat != null && n.lon != null);
  const { path, proj } = useMemo(() => {
    const pts = geo.map((n) => [n.lon as number, n.lat as number]);
    const p = geoNaturalEarth1();
    if (pts.length >= 2) p.fitExtent([[60, 50], [W - 60, H - 50]], { type: "MultiPoint", coordinates: pts });
    else p.fitSize([W, H], LAND);
    return { path: geoPath(p), proj: p };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo.map((n) => n.id).join("|")]);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const focus = hover ?? selected;
  const focusPath = new Set<string>();
  const fn = focus ? byId.get(focus) : undefined;
  if (fn) for (let i = 0; i < fn.path.length - 1; i++) focusPath.add(`${fn.path[i]}>${fn.path[i + 1]}`);
  const hovered = hover ? byId.get(hover) : undefined;
  const hp = hovered ? proj([hovered.lon as number, hovered.lat as number]) : null;

  return (
    <div className="relative overflow-hidden rounded-xl bg-gradient-to-b from-sky-50/60 to-white ring-1 ring-line">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full">
        <path d={path(geoGraticule10()) ?? ""} fill="none" stroke="#E2E8F0" strokeWidth={0.5} />
        {LAND.features.map((f: Feature<Geometry>, i: number) => (
          <path key={i} d={path(f) ?? ""} fill="#EEF2F6" stroke="#FFFFFF" strokeWidth={0.7} />
        ))}
        {edges.map((e) => {
          const a = byId.get(e.source);
          const b = byId.get(e.target);
          if (!a || !b || a.lat == null || b.lat == null || a.lon == null || b.lon == null) return null;
          const on = focusPath.has(`${e.source}>${e.target}`);
          const d = path({ type: "LineString", coordinates: [[a.lon, a.lat], [b.lon, b.lat]] });
          return (
            <path
              key={`${e.source}-${e.target}`}
              d={d ?? ""}
              fill="none"
              stroke={on ? LEVEL_STYLE[a.level === "ok" ? "info" : a.level].color : "#94A3B8"}
              strokeOpacity={on ? 0.95 : focus ? 0.18 : 0.4}
              strokeWidth={on ? 2.4 : 1}
              strokeDasharray={e.backup ? "4 4" : undefined}
            />
          );
        })}
        {geo
          .slice()
          .sort((a, b) => a.risk - b.risk)
          .map((n) => {
            const p = proj([n.lon as number, n.lat as number]);
            if (!p) return null;
            const s = LEVEL_STYLE[n.level];
            const r = 6 + n.criticality * 5;
            return (
              <g
                key={n.id}
                transform={`translate(${p[0]},${p[1]})`}
                className="cursor-pointer"
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect(n.id)}
                onDoubleClick={() => onOpen(n.id)}
              >
                {n.level !== "ok" && <circle r={r + 6} fill={s.color} opacity={0.12} />}
                {selected === n.id && <circle r={r + 5} fill="none" stroke="#0F172A" strokeOpacity={0.3} strokeWidth={1.5} />}
                <NodeShape type={n.type} r={r} fill={s.bg} stroke={s.color} strokeWidth={1.8} />
              </g>
            );
          })}
      </svg>
      {hovered && hp && (
        <div
          className="pointer-events-none absolute z-10 w-56 rounded-xl border border-line bg-white p-3 text-xs shadow-soft"
          style={{ left: `${(hp[0] / W) * 100}%`, top: `${(hp[1] / H) * 100}%`, transform: `translate(${hp[0] > W * 0.7 ? "calc(-100% - 14px)" : "14px"}, -50%)` }}
        >
          <div className="font-bold text-ink">{hovered.name}</div>
          <div className="text-ink-mute">
            {TYPE_LABEL[hovered.type]} · {hovered.place ?? "—"}
            {hovered.country ? `, ${hovered.country}` : ""}
          </div>
          <div className="tnum mt-1.5 font-semibold" style={{ color: LEVEL_STYLE[hovered.level].color }}>
            {LEVEL_STYLE[hovered.level].label} · risque {pct(hovered.risk)}
          </div>
        </div>
      )}
      {geo.length < nodes.length && (
        <div className="absolute bottom-2 left-3 text-[11px] text-ink-mute">{nodes.length - geo.length} nœud(s) sans coordonnées non affiché(s)</div>
      )}
    </div>
  );
}
