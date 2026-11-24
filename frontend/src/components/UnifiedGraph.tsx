// Graphe unifié : nœuds de la chaîne (mêmes formes et mêmes couches que le graphe d'ontologie) et, en satellites,
// les événements Médias / Météo / Finance de la dernière exécution qui les touchent. Zoom, déplacement, recherche,
// inspection des attributs au clic.
import { Crosshair, Minus, Plus, Search } from "lucide-react";
import { useMemo, useRef, useState, type PointerEvent as RPointerEvent, type WheelEvent as RWheelEvent } from "react";
import type { UGEvent, UGNode, UnifiedGraph as UG } from "../api_data";
import { AGENTS, AGENT_STYLE, LEVEL_STYLE, TYPE_LABEL, frDate, pct } from "../theme";
import type { AgentName, NodeType } from "../types";
import { NodeShape, ShapeLegend } from "./OntologyGraph";
import { FAMILY_STYLE, FamilyChip, num } from "./viz";

const COLUMN: Record<NodeType, number> = { matiere_premiere: 0, fournisseur: 1, port: 2, hub: 2, usine: 3, produit_fini: 4 };
const COL_TITLES = ["Matières", "Fournisseurs", "Ports & hubs", "Usines", "Produits finis"];
const W = 1200;
const ROW = 92;
const TOP = 56;

type Selection = { kind: "node"; id: string } | { kind: "event"; id: string } | null;

function layout(nodes: UGNode[], edges: UG["edges"]) {
  const cols: UGNode[][] = [[], [], [], [], []];
  for (const n of nodes) cols[COLUMN[n.type]].push(n);
  const preds = new Map<string, string[]>();
  for (const e of edges) if (!e.backup) preds.set(e.target, [...(preds.get(e.target) ?? []), e.source]);
  const rows = Math.max(...cols.map((c) => c.length), 1);
  const height = TOP + rows * ROW + 20;
  const pos = new Map<string, { x: number; y: number }>();
  cols.forEach((col, ci) => {
    if (ci > 0) {
      const bary = (n: UGNode) => {
        const ys = (preds.get(n.id) ?? []).map((p) => pos.get(p)?.y).filter((y): y is number => y !== undefined);
        return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : height / 2;
      };
      col.sort((a, b) => bary(a) - bary(b));
    } else col.sort((a, b) => b.criticality - a.criticality);
    const x = 90 + (ci * (W - 180)) / 4;
    const y0 = TOP + (rows * ROW - col.length * ROW) / 2 + ROW / 2;
    col.forEach((n, i) => pos.set(n.id, { x, y: y0 + i * ROW }));
  });
  return { pos, height };
}

export default function UnifiedGraph({ data }: { data: UG }) {
  const [agents, setAgents] = useState<Set<AgentName>>(new Set(AGENTS));
  const [sel, setSel] = useState<Selection>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const { pos, height } = useMemo(() => layout(data.nodes, data.edges), [data]);
  const byId = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data]);
  const events = useMemo(() => data.events.filter((e) => agents.has(e.agent) && e.links.some((l) => pos.has(l.node_id))), [data, agents, pos]);

  // Satellites : chaque événement gravite autour de son premier nœud rattaché (exact d'abord)
  const satellites = useMemo(() => {
    const groups = new Map<string, UGEvent[]>();
    for (const e of events) {
      const anchor = [...e.links].sort((a, b) => b.weight - a.weight)[0].node_id;
      groups.set(anchor, [...(groups.get(anchor) ?? []), e]);
    }
    const out = new Map<string, { x: number; y: number; anchor: string }>();
    for (const [anchor, list] of groups) {
      const p = pos.get(anchor)!;
      list.forEach((e, i) => {
        const ring = 34 + Math.floor(i / 10) * 14;
        const a = -Math.PI / 2 + (i % 10) * ((2 * Math.PI) / Math.min(10, list.length));
        out.set(e.id, { x: p.x + ring * Math.cos(a), y: p.y + ring * Math.sin(a), anchor });
      });
    }
    return out;
  }, [events, pos]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return new Set<string>();
    return new Set(data.nodes.filter((n) => `${n.name} ${n.id} ${n.place ?? ""} ${n.country ?? ""}`.toLowerCase().includes(q)).map((n) => n.id));
  }, [query, data]);

  const focusId = hover ?? (sel ? sel.id : null);
  const related = useMemo(() => {
    const s = new Set<string>();
    if (!focusId) return s;
    const ev = events.find((e) => e.id === focusId);
    if (ev) {
      s.add(ev.id);
      ev.links.forEach((l) => s.add(l.node_id));
    } else {
      s.add(focusId);
      events.filter((e) => e.links.some((l) => l.node_id === focusId)).forEach((e) => s.add(e.id));
      data.edges.filter((e) => !e.backup && (e.source === focusId || e.target === focusId)).forEach((e) => (s.add(e.source), s.add(e.target)));
    }
    return s;
  }, [focusId, events, data.edges]);

  const centerOn = (id: string) => {
    const p = pos.get(id);
    if (!p) return;
    const k = 1.8;
    setView({ k, x: W / 2 - p.x * k, y: height / 2 - p.y * k });
    setSel({ kind: "node", id });
  };

  const zoom = (factor: number, cx = W / 2, cy = height / 2) =>
    setView((v) => {
      const k = Math.min(4, Math.max(0.5, v.k * factor));
      return { k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k };
    });

  const toSvg = (clientX: number, clientY: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: ((clientX - r.left) / r.width) * W, y: ((clientY - r.top) / r.height) * height };
  };
  const onWheel = (e: RWheelEvent) => {
    const p = toSvg(e.clientX, e.clientY);
    zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y);
  };
  const onDown = (e: RPointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
  };
  const onMove = (e: RPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const r = svgRef.current!.getBoundingClientRect();
    const dx = ((e.clientX - d.x) / r.width) * W;
    const dy = ((e.clientY - d.y) / r.height) * height;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.moved) setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
  };
  const onUp = () => {
    const moved = drag.current?.moved;
    drag.current = null;
    return moved;
  };

  const selNode = sel?.kind === "node" ? byId.get(sel.id) : null;
  const selEvent = sel?.kind === "event" ? events.find((e) => e.id === sel.id) ?? data.events.find((e) => e.id === sel.id) : null;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label className="relative">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-mute" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && matches.size && centerOn([...matches][0])}
              placeholder="Rechercher un nœud…" className="w-56 rounded-xl border border-line bg-white py-1.5 pl-8 pr-3 text-xs focus:border-sky-300 focus:outline-none" />
          </label>
          {matches.size > 0 && (
            <div className="flex flex-wrap gap-1">
              {[...matches].slice(0, 5).map((id) => (
                <button key={id} onClick={() => centerOn(id)} className="rounded-md bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-800 hover:bg-sky-100">{byId.get(id)?.name}</button>
              ))}
            </div>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {AGENTS.map((a) => {
              const on = agents.has(a);
              const n = data.events.filter((e) => e.agent === a).length;
              return (
                <button key={a} onClick={() => setAgents((s) => { const x = new Set(s); on ? x.delete(a) : x.add(a); return x; })}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${on ? "" : "opacity-40"}`}
                  style={{ background: AGENT_STYLE[a].bg, borderColor: AGENT_STYLE[a].border, color: AGENT_STYLE[a].text }}>
                  <span className="h-2 w-2 rounded-full" style={{ background: AGENT_STYLE[a].dot }} /> {AGENT_STYLE[a].label} {n}
                </button>
              );
            })}
            <div className="ml-1 flex overflow-hidden rounded-lg border border-line">
              <button className="px-1.5 py-1 hover:bg-slate-50" onClick={() => zoom(1.25)} aria-label="Zoom avant"><Plus size={14} /></button>
              <button className="px-1.5 py-1 hover:bg-slate-50" onClick={() => zoom(0.8)} aria-label="Zoom arrière"><Minus size={14} /></button>
              <button className="px-1.5 py-1 hover:bg-slate-50" onClick={() => setView({ x: 0, y: 0, k: 1 })} aria-label="Recentrer"><Crosshair size={14} /></button>
            </div>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl bg-slate-50/50 ring-1 ring-line">
          <svg ref={svgRef} viewBox={`0 0 ${W} ${height}`} className="h-auto w-full cursor-grab touch-none select-none active:cursor-grabbing"
            onWheel={onWheel} onPointerDown={onDown} onPointerMove={onMove} onPointerLeave={() => (drag.current = null)}
            onPointerUp={() => { if (!onUp()) setSel(null); }}>
            <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
              {COL_TITLES.map((t, i) => (
                <text key={t} x={90 + (i * (W - 180)) / 4} y={24} textAnchor="middle" className="fill-slate-400 text-[12px] font-semibold uppercase tracking-wider">{t}</text>
              ))}
              {data.edges.map((e) => {
                const a = pos.get(e.source);
                const b = pos.get(e.target);
                if (!a || !b) return null;
                const lit = focusId ? related.has(e.source) && related.has(e.target) : false;
                const mx = (a.x + b.x) / 2;
                return <path key={`${e.source}>${e.target}`} d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`} fill="none"
                  stroke={lit ? "#64748b" : "#cbd5e1"} strokeWidth={lit ? 1.8 : 1.1} strokeDasharray={e.backup ? "4 4" : undefined} opacity={focusId && !lit ? 0.35 : 1} />;
              })}
              {/* liens événement -> nœuds */}
              {events.flatMap((e) => {
                const s = satellites.get(e.id);
                if (!s) return [];
                return e.links.filter((l) => pos.has(l.node_id)).map((l) => {
                  const p = pos.get(l.node_id)!;
                  const lit = focusId ? related.has(e.id) && related.has(l.node_id) : false;
                  return <line key={`${e.id}-${l.node_id}`} x1={s.x} y1={s.y} x2={p.x} y2={p.y} stroke={AGENT_STYLE[e.agent].dot}
                    strokeWidth={lit ? 1.6 : 0.8} strokeDasharray={l.weight < 1 ? "3 3" : undefined} opacity={focusId ? (lit ? 0.9 : 0.12) : 0.45} />;
                });
              })}
              {data.nodes.map((n) => {
                const p = pos.get(n.id)!;
                const lv = LEVEL_STYLE[n.level];
                const dim = focusId && !related.has(n.id);
                const hit = matches.has(n.id);
                const isSel = sel?.kind === "node" && sel.id === n.id;
                return (
                  <g key={n.id} transform={`translate(${p.x} ${p.y})`} opacity={dim ? 0.35 : 1} className="cursor-pointer"
                    onPointerUp={(ev) => { ev.stopPropagation(); if (!onUp()) setSel({ kind: "node", id: n.id }); }}
                    onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
                    {(hit || isSel) && <circle r={22} fill="none" stroke={isSel ? "#0f172a" : "#017F8D"} strokeWidth={2} strokeDasharray={hit && !isSel ? "3 3" : undefined} />}
                    {n.families[0] && <circle r={17} fill="none" stroke={FAMILY_STYLE[n.families[0]]?.color ?? "#94a3b8"} strokeWidth={2} />}
                    <NodeShape type={n.type} r={12} fill={lv.bg} stroke={lv.color} />
                    <text y={30} textAnchor="middle" className="fill-slate-700 text-[10.5px] font-semibold">{n.name.length > 22 ? `${n.name.slice(0, 21)}…` : n.name}</text>
                  </g>
                );
              })}
              {events.map((e) => {
                const s = satellites.get(e.id);
                if (!s) return null;
                const dim = focusId && !related.has(e.id);
                const r = 4 + 5 * (e.intensity ?? 0.3);
                const isSel = sel?.kind === "event" && sel.id === e.id;
                return (
                  <circle key={e.id} cx={s.x} cy={s.y} r={r} fill={AGENT_STYLE[e.agent].dot} stroke={isSel ? "#0f172a" : "#ffffff"} strokeWidth={isSel ? 2 : 1.2}
                    opacity={dim ? 0.25 : 0.95} className="cursor-pointer"
                    onPointerUp={(ev) => { ev.stopPropagation(); if (!onUp()) setSel({ kind: "event", id: e.id }); }}
                    onMouseEnter={() => setHover(e.id)} onMouseLeave={() => setHover(null)}>
                    <title>{`${AGENT_STYLE[e.agent].label} · ${e.label}`}</title>
                  </circle>
                );
              })}
            </g>
          </svg>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          <ShapeLegend />
          <span className="text-[11px] text-ink-mute">· remplissage = niveau de risque · anneau = famille d'aléa · satellites = événements (taille = intensité, pointillés = lien élargi)</span>
        </div>
      </div>

      <aside className="rounded-xl border border-line p-4 text-[12.5px]">
        {!sel ? (
          <div className="text-ink-mute">
            <div className="mb-1 font-semibold text-ink">Inspection</div>
            Cliquez sur un nœud ou un événement pour voir ses attributs. Molette : zoom ; glisser : déplacer.
            <div className="mt-3 space-y-1">
              <div><b>{data.nodes.length}</b> nœuds · <b>{data.edges.length}</b> liens</div>
              <div><b>{data.events.length}</b> événements de la dernière exécution{data.run ? ` (${frDate(data.run.as_of, { day: "numeric", month: "short", year: "numeric" })})` : ""}</div>
              {!data.run && <div className="text-amber-700">Aucune exécution enregistrée pour cette chaîne : lancez une analyse.</div>}
            </div>
          </div>
        ) : selNode ? (
          <div className="space-y-2">
            <div>
              <div className="text-[15px] font-bold">{selNode.name}</div>
              <div className="text-ink-mute">{TYPE_LABEL[selNode.type]} · {[selNode.place, selNode.country].filter(Boolean).join(", ")}</div>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
              <dt className="text-ink-mute">Identifiant</dt><dd className="truncate font-mono text-[11px]">{selNode.id}</dd>
              <dt className="text-ink-mute">Risque total</dt><dd className="font-bold" style={{ color: LEVEL_STYLE[selNode.level].color }}>{pct(selNode.risk)}</dd>
              <dt className="text-ink-mute">Direct / propagé</dt><dd>{pct(selNode.direct)} / {pct(selNode.propagated)}</dd>
              <dt className="text-ink-mute">Criticité</dt><dd>{num(selNode.criticality, 2)}</dd>
              <dt className="text-ink-mute">Rang / stock</dt><dd>{selNode.tier} · {num(selNode.stock_days, 0)} j</dd>
            </dl>
            <div className="flex flex-wrap gap-1">{selNode.families.map((f) => <FamilyChip key={f} family={f} />)}</div>
            <div className="label mt-2">Événements rattachés</div>
            <ul className="space-y-1">
              {data.events.filter((e) => e.links.some((l) => l.node_id === selNode.id)).map((e) => (
                <li key={e.id}><button onClick={() => setSel({ kind: "event", id: e.id })} className="flex w-full items-start gap-1.5 text-left hover:underline">
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: AGENT_STYLE[e.agent].dot }} />{e.label}</button></li>
              ))}
              {!data.events.some((e) => e.links.some((l) => l.node_id === selNode.id)) && <li className="text-ink-mute">Aucun.</li>}
            </ul>
          </div>
        ) : selEvent ? (
          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: AGENT_STYLE[selEvent.agent].bg, color: AGENT_STYLE[selEvent.agent].text }}>{AGENT_STYLE[selEvent.agent].label}</span>
              {selEvent.family && <FamilyChip family={selEvent.family} />}
            </div>
            <div className="font-semibold leading-snug">{selEvent.label}</div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
              <dt className="text-ink-mute">Identifiant</dt><dd className="truncate font-mono text-[11px]">{selEvent.id}</dd>
              <dt className="text-ink-mute">Type</dt><dd>{selEvent.type}</dd>
              <dt className="text-ink-mute">Date</dt><dd>{frDate(selEvent.date, { day: "numeric", month: "short", year: "numeric" })}</dd>
              <dt className="text-ink-mute">Gravité</dt><dd>{selEvent.intensity == null ? "—" : pct(selEvent.intensity)}</dd>
              <dt className="text-ink-mute">Confiance</dt><dd>{pct(selEvent.confidence)}</dd>
            </dl>
            <div className="label mt-2">Nœuds touchés</div>
            <ul className="space-y-1">
              {selEvent.links.map((l) => (
                <li key={l.node_id}><button onClick={() => centerOn(l.node_id)} className="hover:underline">{byId.get(l.node_id)?.name ?? l.node_id}</button>
                  <span className="text-ink-mute"> · {l.link}{l.weight < 1 ? ` (poids ${num(l.weight, 2)})` : ""}</span></li>
              ))}
            </ul>
            <div className="label mt-2">Sources</div>
            <ul className="space-y-0.5 font-mono text-[10.5px] text-ink-soft">{selEvent.sources.slice(0, 6).map((s) => <li key={s} className="truncate">{s}</li>)}</ul>
          </div>
        ) : null}
      </aside>
    </div>
  );
}
