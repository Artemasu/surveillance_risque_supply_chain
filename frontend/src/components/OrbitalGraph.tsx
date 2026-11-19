// Vue orbitale 3D (react-force-graph-3d) : une sphère volumétrique centrée sur l'entreprise.
// Entreprise au centre (0, 0, 0), puis coquilles sphériques concentriques (produits finis, usines, ports & hubs,
// fournisseurs & matières) peuplées par une distribution de Fibonacci sur la sphère : les maillons occupent tout le
// volume en X, Y et Z, jamais un plan. Signaux actifs en satellites sur de petites orbites 3D autour des maillons
// touchés. Positions fixées (pas de simulation de forces) ; légère rotation automatique, en pause pendant
// l'interaction.
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-3d";
import * as THREE from "three";
import { useClickGuard } from "../clickGuard";
import { downstream, propagationEdges } from "../graphUtils";
import { AGENT_STYLE, LEVEL_STYLE, TYPE_LABEL, pct } from "../theme";
import type { AgentName, CorrelatedSignal, GraphEdge, NodeState, NodeType } from "../types";

type Vec3 = [number, number, number];

const COMPANY = "__company__";
// Coquilles du cœur vers l'extérieur ; `twist` décale la spirale de Fibonacci d'une coquille à l'autre pour que les
// nœuds de deux coquilles voisines ne s'alignent pas sur les mêmes rayons.
const SHELLS: { id: string; r: number; types: NodeType[]; twist: number }[] = [
  { id: "produits", r: 55, types: ["produit_fini"], twist: 0 },
  { id: "usines", r: 125, types: ["usine"], twist: 0.9 },
  { id: "ports", r: 195, types: ["port", "hub"], twist: 1.7 },
  { id: "amont", r: 270, types: ["fournisseur", "matiere_premiere"], twist: 2.6 },
];
const SHELL_OF = new Map<NodeType, number>(SHELLS.flatMap((s, i) => s.types.map((t) => [t, i] as const)));
const HOT = "#EA580C";
const HOT_ORIGIN = "#BE123C";
const AUTO_ROTATE_SPEED = 0.55;      // OrbitControls : ~110 s par tour
const RESUME_AFTER_MS = 12_000;      // reprise de la rotation après une interaction

interface GNode {
  id: string;
  kind: "company" | "node" | "signal";
  label: string;
  color: string;
  size: number;
  node?: NodeState;
  signal?: CorrelatedSignal;
  orbit?: { center: Vec3; u: Vec3; v: Vec3; r: number; phase: number; speed: number };   // satellites
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
const norm = (v: Vec3): Vec3 => {
  const l = Math.hypot(...v) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

/** Point i parmi n sur la sphère unité (spirale de Fibonacci) : phi = acos(1 - 2(i + 0,5)/n), theta = pi(1 + sqrt 5) i. */
function fibonacci(i: number, n: number, twist = 0): Vec3 {
  const phi = Math.acos(1 - (2 * (i + 0.5)) / n);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i + twist;
  return [Math.sin(phi) * Math.cos(theta), Math.sin(phi) * Math.sin(theta), Math.cos(phi)];
}

/**
 * Positions des maillons. Chaque coquille est remplie de l'intérieur vers l'extérieur ; un maillon prend l'emplacement
 * de Fibonacci libre le plus proche de la direction moyenne de ses clients déjà placés : les liens restent courts au
 * lieu de traverser la sphère de part en part.
 */
function layout(nodes: NodeState[], edges: GraphEdge[]): Map<string, Vec3> {
  const pos = new Map<string, Vec3>();
  const clients = new Map<string, string[]>();
  for (const e of edges) if (!e.backup) clients.set(e.source, [...(clients.get(e.source) ?? []), e.target]);
  SHELLS.forEach((shell, si) => {
    const members = nodes.filter((n) => SHELL_OF.get(n.type) === si).sort((a, b) => b.criticality - a.criticality || a.id.localeCompare(b.id));
    const slots = members.map((_, i) => fibonacci(i, members.length, shell.twist));
    const free = new Set(slots.map((_, i) => i));
    for (const n of members) {
      const targets = (clients.get(n.id) ?? []).map((c) => pos.get(c)).filter((p): p is Vec3 => !!p);
      const want = targets.length ? norm(targets.reduce<Vec3>((s, p) => [s[0] + p[0], s[1] + p[1], s[2] + p[2]], [0, 0, 0])) : null;
      let best = [...free][0];
      if (want) for (const i of free) if (dot(slots[i], want) > dot(slots[best], want)) best = i;
      free.delete(best);
      const d = slots[best];
      pos.set(n.id, [d[0] * shell.r, d[1] * shell.r, d[2] * shell.r]);
    }
  });
  return pos;
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

export default function OrbitalGraph({ nodes, edges, signals, companyName, selected, onSelect, onOpen, onDeselect }: {
  nodes: NodeState[]; edges: GraphEdge[]; signals: CorrelatedSignal[]; companyName: string;
  selected: string | null; onSelect: (id: string) => void; onOpen: (id: string) => void; onDeselect: () => void;
}) {
  const guard = useClickGuard();
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

  // Structure (indépendante de la sélection) : maillons sur leurs coquilles, satellites, liens.
  const data = useMemo(() => {
    const gnodes: GNode[] = [{ id: COMPANY, kind: "company", label: companyName, color: "#0F172A", size: 13, fx: 0, fy: 0, fz: 0 }];
    const pos = layout(nodes, edges);
    for (const n of nodes) {
      const p = pos.get(n.id);
      if (!p) continue;
      gnodes.push({ id: n.id, kind: "node", label: n.name, color: LEVEL_STYLE[n.level].color, size: 4 + n.criticality * 5, node: n, fx: p[0], fy: p[1], fz: p[2] });
    }
    const links: GLink[] = edges
      .filter((e) => pos.has(e.source) && pos.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, kind: "supply", key: `${e.source}>${e.target}`, backup: e.backup }));
    for (const n of nodes) if (n.type === "produit_fini") links.push({ source: n.id, target: COMPANY, kind: "product", key: `${n.id}>${COMPANY}` });

    // Satellites : centre d'orbite légèrement à l'extérieur du maillon touché, plan d'orbite propre à chaque signal
    // (axe tiré d'une spirale de Fibonacci), donc un mouvement sur les trois axes.
    const perNode = new Map<string, number>();
    signals.forEach((s, si) => {
      const p = pos.get(s.node_id);
      if (!p) return;
      const k = perNode.get(s.node_id) ?? 0;
      perNode.set(s.node_id, k + 1);
      const out = norm(p);
      const center: Vec3 = [p[0] + out[0] * 14, p[1] + out[1] * 14, p[2] + out[2] * 14];
      const axis = fibonacci(si, Math.max(signals.length, 2), 0.7);
      const u = norm(cross(axis, Math.abs(axis[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]));
      const v = cross(axis, u);
      const agent = s.agents[0] as AgentName;
      gnodes.push({
        id: `sig:${s.id}`, kind: "signal", label: s.label, color: AGENT_STYLE[agent].dot, size: 2.2 + s.contribution * 4, signal: s,
        orbit: { center, u, v, r: 16 + k * 6, phase: k * 2.3 + si * 0.37, speed: 0.45 + (si % 3) * 0.08 },
        fx: center[0] + u[0] * 16, fy: center[1] + u[1] * 16, fz: center[2] + u[2] * 16,
      });
      links.push({ source: `sig:${s.id}`, target: s.node_id, kind: "signal", key: `sig:${s.id}`, color: AGENT_STYLE[agent].dot });
    });
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

  // Géométries mises en cache : un changement de sélection ne modifie que les matériaux.
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

  // Coquilles translucides (repères de volume), caméra en vue de trois quarts, rotation automatique lente.
  useEffect(() => {
    let resume: number | undefined;
    let controls: (THREE.EventDispatcher<{ start: object; end: object }> & { autoRotate: boolean; autoRotateSpeed: number }) | undefined;
    const pause = () => {
      if (!controls) return;
      controls.autoRotate = false;
      window.clearTimeout(resume);
    };
    const scheduleResume = () => {
      window.clearTimeout(resume);
      resume = window.setTimeout(() => controls && (controls.autoRotate = true), RESUME_AFTER_MS);
    };
    const el = wrap.current;
    const t = setTimeout(() => {
      const g = fg.current;
      if (!g) return;
      const shells = new THREE.Group();
      shells.name = "shells";
      for (const s of SHELLS) {
        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(s.r, 48, 32),
          new THREE.MeshBasicMaterial({ color: "#94A3B8", transparent: true, opacity: 0.035, depthWrite: false, side: THREE.DoubleSide }),
        );
        const outline = new THREE.Mesh(
          new THREE.SphereGeometry(s.r, 18, 10),
          new THREE.MeshBasicMaterial({ color: "#CBD5E1", wireframe: true, transparent: true, opacity: 0.07, depthWrite: false }),
        );
        shells.add(sphere, outline);
      }
      g.scene().add(shells);
      g.cameraPosition({ x: 470, y: -430, z: 420 }, { x: 0, y: 0, z: 0 }, 0);
      controls = g.controls() as typeof controls;
      if (controls) {
        controls.autoRotate = true;
        controls.autoRotateSpeed = AUTO_ROTATE_SPEED;
        controls.addEventListener("start", pause);        // glisser, molette
        controls.addEventListener("end", scheduleResume);
      }
      el?.addEventListener("pointerdown", pause);          // clic sur un nœud
      el?.addEventListener("pointerup", scheduleResume);
    }, 50);
    return () => {
      clearTimeout(t);
      window.clearTimeout(resume);
      controls?.removeEventListener("start", pause);
      controls?.removeEventListener("end", scheduleResume);
      el?.removeEventListener("pointerdown", pause);
      el?.removeEventListener("pointerup", scheduleResume);
      const shells = fg.current?.scene().getObjectByName("shells");
      if (shells) {
        shells.traverse((o) => {
          if (o instanceof THREE.Mesh) {
            o.geometry.dispose();
            (o.material as THREE.Material).dispose();
          }
        });
        shells.parent?.remove(shells);
      }
    };
  }, []);

  // Satellites : orbite lente dans leur propre plan 3D autour du maillon touché.
  const onTick = () => {
    const t = performance.now() / 1000;
    for (const n of data.nodes) {
      const o = n.orbit;
      if (!o) continue;
      const a = t * o.speed + o.phase;
      const c = Math.cos(a) * o.r;
      const s = Math.sin(a) * o.r;
      n.fx = o.center[0] + o.u[0] * c + o.v[0] * s;
      n.fy = o.center[1] + o.u[1] * c + o.v[1] * s;
      n.fz = o.center[2] + o.u[2] * c + o.v[2] * s;
    }
  };

  const tooltip = (n: GNode) => {
    const box = (body: string) => `<div style="font:12px/1.45 'Plus Jakarta Sans',Inter,sans-serif;background:#fff;color:#0F172A;border:1px solid #E2E8F0;border-radius:12px;padding:8px 12px;box-shadow:0 4px 16px rgba(15,23,42,.08);max-width:260px">${body}</div>`;
    if (n.kind === "company") return box(`<b>${esc(n.label)}</b><div style="color:#64748B">Entreprise — cœur de la sphère</div>`);
    if (n.kind === "signal" && n.signal) {
      const s = n.signal;
      return box(`<b>${esc(s.agents.map((a) => AGENT_STYLE[a].label).join(" + "))}</b> · ${esc(s.node_name)}<div style="color:#475569">${esc(s.label)}</div><div style="color:#64748B">contribution ${pct(s.contribution)} · rattachement ${s.link === "exact" ? "exact" : "élargi ×0,40"}</div>`);
    }
    const d = n.node!;
    return box(`<b>${esc(d.name)}</b><div style="color:#64748B">${esc(TYPE_LABEL[d.type])}${d.place ? ` · ${esc(d.place)}` : ""}${d.country ? `, ${esc(d.country)}` : ""}</div><div style="color:${LEVEL_STYLE[d.level].color};font-weight:600">${LEVEL_STYLE[d.level].label} · risque ${pct(d.risk)}</div><div style="color:#64748B">direct ${pct(d.direct)} · propagé ${pct(d.propagated)} · stock ${d.stock_days} j</div><div style="color:#94A3B8;margin-top:2px">Clic : simuler · double-clic : preuves</div>`);
  };

  const lastClick = useRef<{ id: string; t: number } | null>(null);
  return (
    <div ref={wrap} className="relative overflow-hidden rounded-xl bg-[#f8fafc] ring-1 ring-line" onPointerDownCapture={guard.down}>
      <ForceGraph3D<GNode, GLink>
        ref={fg}
        controlType="orbit"
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
        onBackgroundClick={(e) => {
          // Faire tourner la sphère (glisser > 4 px) ne désélectionne jamais le nœud en cours d'analyse.
          if (guard.isClick(e)) onDeselect();
        }}
        onNodeClick={(n, e) => {
          if (!guard.isClick(e)) return;
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
        <span>au cœur · coquilles : produits → usines → ports & hubs → fournisseurs & matières</span>
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
