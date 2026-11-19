// Vue orbitale 3D (react-force-graph-3d) centrée sur l'entreprise : produits finis au cœur, puis anneaux des usines,
// ports & hubs, fournisseurs et matières ; signaux actifs en satellites colorés par agent. Positions fixées (pas de
// simulation de forces) pour une structure radiale stable et lisible.
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-3d";
import * as THREE from "three";
import { downstream, propagationEdges } from "../graphUtils";
import { AGENT_STYLE, LEVEL_STYLE, TYPE_LABEL, pct } from "../theme";
import type { AgentName, CorrelatedSignal, GraphEdge, NodeState, NodeType } from "../types";

const COMPANY = "__company__";
// Rayon et inclinaison (degrés) de chaque orbite : les anneaux ne sont pas coplanaires, la profondeur se lit en 3D.
const ORBIT: Record<NodeType, { r: number; tilt: number; phase: number }> = {
  produit_fini: { r: 60, tilt: 4, phase: 0 },
  usine: { r: 125, tilt: -7, phase: 0.4 },
  port: { r: 195, tilt: 9, phase: 0.9 },
  hub: { r: 195, tilt: 9, phase: 0.9 },
  fournisseur: { r: 265, tilt: -6, phase: 1.6 },
  matiere_premiere: { r: 330, tilt: 8, phase: 2.3 },
};
const HOT = "#EA580C";
const HOT_ORIGIN = "#BE123C";

interface GNode {
  id: string;
  kind: "company" | "node" | "signal";
  label: string;
  color: string;
  size: number;
  node?: NodeState;
  signal?: CorrelatedSignal;
  base?: [number, number, number];   // position de repos (satellites : centre de l'orbite)
  phase?: number;
  fx?: number;
  fy?: number;
  fz?: number;
}
interface GLink {
  source: string;
  target: string;
  kind: "supply" | "product" | "signal";
  key: string;
  backup?: boolean;
  color?: string;
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function place(r: number, angle: number, tiltDeg: number): [number, number, number] {
  const t = (tiltDeg * Math.PI) / 180;
  const x = r * Math.cos(angle);
  const y0 = r * Math.sin(angle);
  return [x, y0 * Math.cos(t), y0 * Math.sin(t)];
}

function geometryFor(type: NodeType | "company", size: number): THREE.BufferGeometry {
  switch (type) {
    case "company": return new THREE.SphereGeometry(size, 32, 24);
    case "produit_fini": return new THREE.SphereGeometry(size, 24, 16);
    case "usine": return new THREE.BoxGeometry(size * 1.5, size * 1.5, size * 1.5);
    case "port": return new THREE.OctahedronGeometry(size * 1.15);
    case "hub": return new THREE.ConeGeometry(size, size * 1.9, 4);
    case "fournisseur": return new THREE.DodecahedronGeometry(size);
    default: return new THREE.TetrahedronGeometry(size * 1.2);
  }
}

export default function OrbitalGraph({ nodes, edges, signals, companyName, selected, onSelect, onOpen }: {
  nodes: NodeState[]; edges: GraphEdge[]; signals: CorrelatedSignal[]; companyName: string;
  selected: string | null; onSelect: (id: string) => void; onOpen: (id: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraphMethods<NodeObject<GNode>, LinkObject<GNode, GLink>>>();
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, Math.floor(e.contentRect.width))));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // Structure (indépendante de la sélection) : nœuds placés sur leurs orbites, satellites, liens.
  const data = useMemo(() => {
    const gnodes: GNode[] = [{ id: COMPANY, kind: "company", label: companyName, color: "#0F172A", size: 13, fx: 0, fy: 0, fz: 0 }];
    const byType = new Map<string, NodeState[]>();
    for (const n of nodes) {
      const ring = n.type === "hub" ? "port" : n.type;
      byType.set(ring, [...(byType.get(ring) ?? []), n]);
    }
    const pos = new Map<string, [number, number, number]>();
    for (const [ring, list] of byType) {
      const o = ORBIT[ring as NodeType];
      list.forEach((n, i) => {
        const p = place(o.r, o.phase + (i / list.length) * Math.PI * 2, o.tilt);
        pos.set(n.id, p);
        gnodes.push({ id: n.id, kind: "node", label: n.name, color: LEVEL_STYLE[n.level].color, size: 4 + n.criticality * 5, node: n, fx: p[0], fy: p[1], fz: p[2] });
      });
    }
    const links: GLink[] = edges
      .filter((e) => pos.has(e.source) && pos.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, kind: "supply", key: `${e.source}>${e.target}`, backup: e.backup }));
    for (const n of nodes) if (n.type === "produit_fini") links.push({ source: n.id, target: COMPANY, kind: "product", key: `${n.id}>${COMPANY}` });

    // Satellites : chaque signal actif gravite à l'extérieur du maillon qu'il impacte.
    const perNode = new Map<string, number>();
    for (const s of signals) {
      const p = pos.get(s.node_id);
      if (!p) continue;
      const k = perNode.get(s.node_id) ?? 0;
      perNode.set(s.node_id, k + 1);
      const len = Math.hypot(...p) || 1;
      const out = 26 + k * 7;
      const base: [number, number, number] = [p[0] + (p[0] / len) * out, p[1] + (p[1] / len) * out, p[2] + (p[2] / len) * out];
      const agent = s.agents[0] as AgentName;
      gnodes.push({
        id: `sig:${s.id}`, kind: "signal", label: s.label, color: AGENT_STYLE[agent].dot, size: 2.2 + s.contribution * 4,
        signal: s, base, phase: k * 2.1, fx: base[0], fy: base[1], fz: base[2],
      });
      links.push({ source: `sig:${s.id}`, target: s.node_id, kind: "signal", key: `sig:${s.id}`, color: AGENT_STYLE[agent].dot });
    }
    return { nodes: gnodes, links };
  }, [nodes, edges, signals, companyName]);

  // Propagation du nœud sélectionné jusqu'à l'entreprise centrale.
  const hot = useMemo(() => {
    const keys = propagationEdges(edges, selected);
    const reach = selected ? downstream(edges, selected) : new Set<string>();
    for (const n of nodes) if (n.type === "produit_fini" && reach.has(n.id)) keys.add(`${n.id}>${COMPANY}`);
    if (reach.size) reach.add(COMPANY);
    return { keys, reach };
  }, [edges, nodes, selected]);

  // Géométries mises en cache : un changement de sélection ne recrée que les matériaux.
  const objects = useMemo(() => {
    const cache = new Map<string, THREE.Mesh>();
    for (const n of data.nodes) {
      const type = n.kind === "company" ? "company" : n.kind === "signal" ? "produit_fini" : n.node!.type;
      const mat = new THREE.MeshLambertMaterial({ color: n.color, transparent: true, opacity: 0.95 });
      cache.set(n.id, new THREE.Mesh(geometryFor(type, n.size), mat));
    }
    return cache;
  }, [data]);

  useEffect(() => {
    for (const [id, mesh] of objects) {
      const mat = mesh.material as THREE.MeshLambertMaterial;
      const g = data.nodes.find((n) => n.id === id)!;
      const lit = id === selected || hot.reach.has(id);
      const dim = !!selected && !lit && g.kind !== "signal";
      mat.color.set(id === selected ? HOT_ORIGIN : lit && g.kind === "node" ? HOT : g.color);
      mat.emissive.set(lit ? (id === selected ? HOT_ORIGIN : HOT) : "#000000");
      mat.emissiveIntensity = lit ? 0.35 : 0;
      mat.opacity = dim ? 0.35 : 0.95;
      mesh.scale.setScalar(id === hover ? 1.35 : id === selected ? 1.25 : 1);
    }
  }, [objects, data, hot, selected, hover]);

  useEffect(() => () => objects.forEach((m) => { m.geometry.dispose(); (m.material as THREE.Material).dispose(); }), [objects]);

  // Anneaux d'orbite discrets (un par couche) et caméra en légère plongée : les orbites se lisent d'emblée,
  // puis rotation libre à la souris.
  useEffect(() => {
    const t = setTimeout(() => {
      const g = fg.current;
      if (!g) return;
      const scene = g.scene();
      const rings = new THREE.Group();
      rings.name = "orbits";
      for (const type of ["produit_fini", "usine", "port", "fournisseur", "matiere_premiere"] as NodeType[]) {
        const o = ORBIT[type];
        const pts = Array.from({ length: 129 }, (_, i) => new THREE.Vector3(...place(o.r, (i / 128) * Math.PI * 2, o.tilt)));
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: "#CBD5E1", transparent: true, opacity: 0.7 }));
        rings.add(line);
      }
      scene.add(rings);
      g.cameraPosition({ x: 0, y: -300, z: 820 }, { x: 0, y: 0, z: 0 }, 0);
    }, 50);
    return () => {
      clearTimeout(t);
      const orbits = fg.current?.scene().getObjectByName("orbits");
      if (orbits) {
        orbits.traverse((o) => {
          if (o instanceof THREE.Line) {
            o.geometry.dispose();
            (o.material as THREE.Material).dispose();
          }
        });
        orbits.parent?.remove(orbits);
      }
    };
  }, []);

  // Satellites en orbite lente autour de leur point d'ancrage.
  const onTick = () => {
    const t = performance.now() / 1000;
    for (const n of data.nodes) {
      if (n.kind !== "signal" || !n.base) continue;
      const a = t * 0.6 + (n.phase ?? 0);
      n.fx = n.base[0] + Math.cos(a) * 6;
      n.fy = n.base[1] + Math.sin(a) * 6;
      n.fz = n.base[2] + Math.sin(a * 0.7) * 4;
    }
  };

  const tooltip = (n: GNode) => {
    const box = (body: string) => `<div style="font:12px/1.45 'Plus Jakarta Sans',Inter,sans-serif;background:#fff;color:#0F172A;border:1px solid #E2E8F0;border-radius:12px;padding:8px 12px;box-shadow:0 4px 16px rgba(15,23,42,.08);max-width:260px">${body}</div>`;
    if (n.kind === "company") return box(`<b>${esc(n.label)}</b><div style="color:#64748B">Entreprise — produits finis au centre</div>`);
    if (n.kind === "signal" && n.signal) {
      const s = n.signal;
      return box(`<b>${esc(s.agents.map((a) => AGENT_STYLE[a].label).join(" + "))}</b> · ${esc(s.node_name)}<div style="color:#475569">${esc(s.label)}</div><div style="color:#64748B">contribution ${pct(s.contribution)} · rattachement ${s.link === "exact" ? "exact" : "élargi ×0,40"}</div>`);
    }
    const d = n.node!;
    return box(`<b>${esc(d.name)}</b><div style="color:#64748B">${esc(TYPE_LABEL[d.type])}${d.place ? ` · ${esc(d.place)}` : ""}${d.country ? `, ${esc(d.country)}` : ""}</div><div style="color:${LEVEL_STYLE[d.level].color};font-weight:600">${LEVEL_STYLE[d.level].label} · risque ${pct(d.risk)}</div><div style="color:#64748B">direct ${pct(d.direct)} · propagé ${pct(d.propagated)} · stock ${d.stock_days} j</div><div style="color:#94A3B8;margin-top:2px">Clic : simuler · double-clic : preuves</div>`);
  };

  const lastClick = useRef<{ id: string; t: number } | null>(null);
  return (
    <div ref={wrap} className="relative overflow-hidden rounded-xl bg-[#f8fafc] ring-1 ring-line">
      <ForceGraph3D<GNode, GLink>
        ref={fg}
        width={width}
        height={540}
        graphData={data}
        backgroundColor="#f8fafc"
        showNavInfo={false}
        enableNodeDrag={false}
        cooldownTicks={Infinity}
        d3AlphaDecay={0}
        d3VelocityDecay={1}
        onEngineTick={onTick}
        nodeThreeObject={(n) => objects.get(n.id as string)!}
        nodeLabel={(n) => tooltip(n as GNode)}
        onNodeHover={(n) => {
          setHover((n?.id as string) ?? null);
          if (wrap.current) wrap.current.style.cursor = n ? "pointer" : "";
        }}
        onNodeClick={(n) => {
          const g = n as GNode;
          const now = Date.now();
          const dbl = lastClick.current?.id === g.id && now - lastClick.current.t < 350;
          lastClick.current = { id: g.id, t: now };
          const target = g.kind === "signal" ? g.signal!.node_id : g.kind === "node" ? g.id : null;
          if (!target) return;
          if (dbl || g.kind === "signal") onOpen(target);
          else onSelect(target);
        }}
        linkColor={(l) => (hot.keys.has(l.key) ? HOT : l.kind === "signal" ? l.color! : l.backup ? "#CBD5E1" : "#94A3B8")}
        linkOpacity={selected ? 0.35 : 0.5}
        linkWidth={(l) => (hot.keys.has(l.key) ? 2.2 : l.kind === "signal" ? 0.3 : 0.6)}
        linkDirectionalArrowLength={(l) => (l.kind === "signal" ? 0 : 3.5)}
        linkDirectionalArrowRelPos={0.92}
        linkDirectionalArrowColor={(l) => (hot.keys.has(l.key) ? HOT : "#94A3B8")}
        linkDirectionalParticles={(l) => (l.kind === "signal" || l.backup ? 0 : hot.keys.has(l.key) ? 4 : 1)}
        linkDirectionalParticleWidth={(l) => (hot.keys.has(l.key) ? 2.4 : 1.2)}
        linkDirectionalParticleSpeed={(l) => (hot.keys.has(l.key) ? 0.012 : 0.004)}
        linkDirectionalParticleColor={(l) => (hot.keys.has(l.key) ? HOT : "#64748B")}
      />
      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-lg bg-white/85 px-2.5 py-1.5 text-[11px] text-ink-mute ring-1 ring-line">
        <span className="font-semibold text-ink-soft">{companyName}</span>
        <span>au centre · orbites : produits → usines → ports & hubs → fournisseurs → matières</span>
        {(["media", "finance", "weather"] as AgentName[]).map((a) => (
          <span key={a} className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ background: AGENT_STYLE[a].dot }} /> {AGENT_STYLE[a].label}
          </span>
        ))}
      </div>
      <div className="pointer-events-none absolute right-3 top-3 rounded-lg bg-white/85 px-2.5 py-1 text-[11px] text-ink-mute ring-1 ring-line">
        Glisser : rotation · molette : zoom
      </div>
    </div>
  );
}
