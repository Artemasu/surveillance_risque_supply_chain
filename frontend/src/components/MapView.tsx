// Carte interactive MapLibre (gratuite, sans clé) : plan Mercator 2D ou globe 3D, nœuds colorés par niveau de
// risque, liens logistiques en arcs géodésiques, propagation aval du nœud sélectionné dans le What-If.
import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection, Point } from "geojson";
import { Globe2, Map as MapIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createClickGuard } from "../clickGuard";
import { propagationEdges } from "../graphUtils";
import { LEVEL_STYLE, TYPE_LABEL, pct } from "../theme";
import { FAMILY_STYLE } from "./viz";
import type { GraphEdge, NodeState } from "../types";
import { Segmented } from "./ui";
import { OPTIONS_MONDE, bloquerMonde } from "../carteMonde";

const POSITRON = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
// Repli hors ligne : fond uni, la carte reste utilisable (nœuds et liens), sans fond cartographique.
const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#EEF2F6" } }],
};

type Proj = "2d" | "3d";

/** Arc de grand cercle entre deux points (interpolation sphérique), longitudes déroulées pour l'antiméridien. */
function arc(a: [number, number], b: [number, number], steps = 48): [number, number][] {
  const rad = Math.PI / 180;
  const toV = ([lon, lat]: [number, number]) => [Math.cos(lat * rad) * Math.cos(lon * rad), Math.cos(lat * rad) * Math.sin(lon * rad), Math.sin(lat * rad)];
  const va = toV(a);
  const vb = toV(b);
  const dot = Math.min(1, Math.max(-1, va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2]));
  const w = Math.acos(dot);
  if (w < 1e-6) return [a, b];
  const pts: [number, number][] = [];
  let prevLon = a[0];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const k1 = Math.sin((1 - t) * w) / Math.sin(w);
    const k2 = Math.sin(t * w) / Math.sin(w);
    const x = k1 * va[0] + k2 * vb[0];
    const y = k1 * va[1] + k2 * vb[1];
    const z = k1 * va[2] + k2 * vb[2];
    let lon = Math.atan2(y, x) / rad;
    while (lon - prevLon > 180) lon -= 360;
    while (lon - prevLon < -180) lon += 360;
    prevLon = lon;
    pts.push([lon, Math.atan2(z, Math.hypot(x, y)) / rad]);
  }
  return pts;
}

function geojson(nodes: NodeState[], edges: GraphEdge[], selected: string | null) {
  const geo = nodes.filter((n) => n.lat != null && n.lon != null);
  const byId = new Map(geo.map((n) => [n.id, n]));
  const hot = propagationEdges(edges, selected);
  const reach = new Set([...hot].flatMap((k) => k.split(">")));
  const points: FeatureCollection = {
    type: "FeatureCollection",
    features: geo.map((n) => ({
      type: "Feature",
      id: n.id,
      geometry: { type: "Point", coordinates: [n.lon as number, n.lat as number] },
      properties: {
        id: n.id, name: n.name, type: TYPE_LABEL[n.type], place: [n.place, n.country].filter(Boolean).join(", "),
        risk: n.risk, level: LEVEL_STYLE[n.level].label, color: LEVEL_STYLE[n.level].color, fill: LEVEL_STYLE[n.level].bg,
        r: 5 + n.criticality * 5, selected: n.id === selected ? 1 : 0, downstream: reach.has(n.id) && n.id !== selected ? 1 : 0,
        // famille d'aléa dominante (identifiant du signal : sig:<nœud>:<famille>:<k>) -> anneau coloré
        fam: n.signal_ids.length ? n.signal_ids[0].split(":")[2] ?? "" : "",
        famColor: n.signal_ids.length ? FAMILY_STYLE[n.signal_ids[0].split(":")[2]]?.color ?? "" : "",
        famLabel: [...new Set(n.signal_ids.map((s) => FAMILY_STYLE[s.split(":")[2]]?.label ?? s.split(":")[2]))].join(", "),
      },
    })),
  };
  const lines: FeatureCollection = {
    type: "FeatureCollection",
    features: edges.flatMap((e) => {
      const a = byId.get(e.source);
      const b = byId.get(e.target);
      if (!a || !b) return [];
      const key = `${e.source}>${e.target}`;
      return [{
        type: "Feature" as const,
        geometry: { type: "LineString" as const, coordinates: arc([a.lon as number, a.lat as number], [b.lon as number, b.lat as number]) },
        properties: { backup: e.backup ? 1 : 0, hot: hot.has(key) ? 1 : 0, dep: e.dependency },
      }];
    }),
  };
  return { points, lines, geo };
}

export default function MapView({ nodes, edges, selected, onSelect, onOpen, onDeselect }: {
  nodes: NodeState[]; edges: GraphEdge[]; selected: string | null;
  onSelect: (id: string) => void; onOpen: (id: string) => void; onDeselect: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);
  const [proj, setProj] = useState<Proj>("2d");
  const handlers = useRef({ onSelect, onOpen, onDeselect });
  handlers.current = { onSelect, onOpen, onDeselect };
  const data = useMemo(() => geojson(nodes, edges, selected), [nodes, edges, selected]);

  // Création unique de la carte.
  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({
      container: box.current, style: POSITRON, center: [40, 30], zoom: 1.4, pitch: 0, bearing: 0,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false, ...OPTIONS_MONDE,
    });
    bloquerMonde(m);   // un seul exemplaire du monde, même dézoomé au maximum
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    // Clic sec vs glisser : position mémorisée à l'appui sur le conteneur (souris, stylet, doigt).
    const guard = createClickGuard();
    const container = m.getCanvasContainer();
    container.addEventListener("pointerdown", guard.down, { capture: true });
    // Clic sec dans le vide (aucun nœud sous le pointeur, pas de déplacement ni de rotation) : désélection.
    m.on("click", (e) => {
      if (!guard.isClick(e.originalEvent) || !m.getLayer("nodes")) return;
      if (m.queryRenderedFeatures(e.point, { layers: ["nodes"] }).length === 0) handlers.current.onDeselect();
    });
    let fellBack = false;
    m.on("error", (ev) => {
      // Style distant injoignable (hors ligne, pare-feu) : repli sur un fond uni.
      if (!fellBack && !m.isStyleLoaded() && /style|fetch|Failed/i.test(String(ev.error?.message ?? ""))) {
        fellBack = true;
        setOffline(true);
        m.setStyle(OFFLINE_STYLE);
      }
    });
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: "sc-popup" });

    const install = () => {
      if (m.getSource("links")) return;
      const d = geojson([], [], null);
      m.addSource("links", { type: "geojson", data: d.lines });
      m.addSource("nodes", { type: "geojson", data: d.points, promoteId: "id" });
      m.addLayer({
        id: "links", type: "line", source: "links", filter: ["==", ["get", "hot"], 0],
        layout: { "line-cap": "round" },
        paint: { "line-color": "#94A3B8", "line-opacity": 0.45, "line-width": ["interpolate", ["linear"], ["get", "dep"], 0, 0.8, 1, 2], "line-dasharray": ["case", ["==", ["get", "backup"], 1], ["literal", [2, 2]], ["literal", [1, 0]]] },
      });
      m.addLayer({
        id: "links-hot", type: "line", source: "links", filter: ["==", ["get", "hot"], 1],
        layout: { "line-cap": "round" }, paint: { "line-color": "#EA580C", "line-opacity": 0.9, "line-width": 3 },
      });
      m.addLayer({
        id: "nodes-halo", type: "circle", source: "nodes",
        paint: {
          "circle-radius": ["+", ["get", "r"], ["case", ["==", ["get", "selected"], 1], 9, ["==", ["get", "downstream"], 1], 6, 0]],
          "circle-color": ["case", ["==", ["get", "selected"], 1], "#BE123C", "#EA580C"],
          "circle-opacity": ["case", ["any", ["==", ["get", "selected"], 1], ["==", ["get", "downstream"], 1]], 0.18, 0],
        },
      });
      m.addLayer({
        id: "nodes-family", type: "circle", source: "nodes", filter: ["!=", ["get", "famColor"], ""],
        paint: { "circle-radius": ["+", ["get", "r"], 3.5], "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": ["get", "famColor"], "circle-stroke-width": 2 },
      });
      m.addLayer({
        id: "nodes", type: "circle", source: "nodes",
        paint: {
          "circle-radius": ["get", "r"], "circle-color": ["get", "color"], "circle-opacity": 0.9,
          "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], "#0F172A", "#FFFFFF"],
          "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 2.5, 1.5],
        },
      });
      m.on("mousemove", "nodes", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        m.getCanvas().style.cursor = "pointer";
        const p = f.properties as Record<string, string | number>;
        const el = document.createElement("div");
        const title = document.createElement("div");
        title.className = "font-bold text-ink";
        title.textContent = String(p.name);
        const sub = document.createElement("div");
        sub.className = "text-ink-mute";
        sub.textContent = `${p.type}${p.place ? ` · ${p.place}` : ""}`;
        const risk = document.createElement("div");
        risk.className = "tnum mt-1 font-semibold";
        risk.style.color = String(p.color);
        risk.textContent = `${p.level} · risque ${pct(Number(p.risk))}`;
        el.append(title, sub, risk);
        if (p.famLabel) {
          const fam = document.createElement("div");
          fam.className = "mt-0.5 text-[11px] font-semibold";
          fam.style.color = String(p.famColor || "#475569");
          fam.textContent = `Menace : ${p.famLabel}`;
          el.append(fam);
        }
        popup.setLngLat((f.geometry as Point).coordinates as [number, number]).setDOMContent(el).addTo(m);
      });
      m.on("mouseleave", "nodes", () => {
        m.getCanvas().style.cursor = "";
        popup.remove();
      });
      m.on("click", "nodes", (e) => {
        if (e.originalEvent.detail >= 2 || !guard.isClick(e.originalEvent)) return;   // 2e clic d'un double-clic, ou glisser
        const id = e.features?.[0]?.properties?.id;
        if (id) handlers.current.onSelect(String(id));
      });
      m.on("dblclick", "nodes", (e) => {
        e.preventDefault();
        const id = e.features?.[0]?.properties?.id;
        if (id) handlers.current.onOpen(String(id));
      });
      setReady(true);
    };
    m.on("style.load", install);
    return () => {
      container.removeEventListener("pointerdown", guard.down, { capture: true });
      popup.remove();
      m.remove();
      map.current = null;
    };
  }, []);

  // Données : nœuds, niveaux, sélection What-If et propagation aval.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    (m.getSource("nodes") as GeoJSONSource | undefined)?.setData(data.points);
    (m.getSource("links") as GeoJSONSource | undefined)?.setData(data.lines);
  }, [ready, data.points, data.lines]);

  // Cadrage initial sur les nœuds.
  const framed = useRef(false);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || framed.current || data.geo.length < 2) return;
    framed.current = true;
    const b = new maplibregl.LngLatBounds();
    for (const n of data.geo) b.extend([n.lon as number, n.lat as number]);
    m.fitBounds(b, { padding: 60, duration: 0, maxZoom: 5 });
  }, [ready, data.geo]);

  // Bascule 2D (Mercator à plat) / 3D (globe rotatif).
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (proj === "3d") {
      m.setProjection({ type: "globe" });
      m.dragRotate.enable();
      m.easeTo({ zoom: Math.min(m.getZoom(), 1.8), pitch: 0, bearing: 0, duration: 1200 });
    } else {
      m.setProjection({ type: "mercator" });
      m.dragRotate.disable();
      const b = new maplibregl.LngLatBounds();
      for (const n of data.geo) b.extend([n.lon as number, n.lat as number]);
      if (data.geo.length >= 2) m.fitBounds(b, { padding: 60, maxZoom: 5, pitch: 0, bearing: 0, duration: 1000 });
      else m.easeTo({ pitch: 0, bearing: 0, duration: 800 });
    }
  }, [proj, ready]);

  const missing = nodes.length - data.geo.length;
  return (
    <div className="relative overflow-hidden rounded-xl ring-1 ring-line">
      <div ref={box} className="h-[520px] w-full bg-[#EEF2F6]" />
      <div className="absolute right-3 top-3 z-10">
        <Segmented value={proj} onChange={setProj} options={[{ value: "2d", label: "2D", icon: MapIcon }, { value: "3d", label: "3D", icon: Globe2 }]} />
      </div>
      {offline && (
        <div className="absolute left-3 top-3 z-10 rounded-lg bg-white/90 px-2.5 py-1 text-[11px] text-ink-mute ring-1 ring-line">Fond de carte indisponible (hors ligne)</div>
      )}
      {missing > 0 && <div className="absolute bottom-2 left-3 z-10 rounded bg-white/80 px-1.5 text-[11px] text-ink-mute">{missing} nœud(s) sans coordonnées non affiché(s)</div>}
    </div>
  );
}
