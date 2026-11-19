// Courbe épurée de l'indice de risque global par jour (SVG, sans dépendance).
import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { LEVEL_STYLE, fmt1, frDate, indexLevel } from "../theme";
import type { TimelinePoint } from "../types";
import { Empty } from "./ui";

const W = 640;
const H = 220;
const P = { l: 36, r: 16, t: 16, b: 28 };

export default function RiskChart({ points }: { points: TimelinePoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const geo = useMemo(() => {
    const max = Math.max(20, ...points.map((p) => p.global_risk_index)) * 1.15;
    const yMax = Math.ceil(max / 10) * 10;
    const n = points.length;
    const x = (i: number) => P.l + (n <= 1 ? (W - P.l - P.r) / 2 : (i * (W - P.l - P.r)) / (n - 1));
    const y = (v: number) => P.t + (1 - v / yMax) * (H - P.t - P.b);
    const pts = points.map((p, i) => [x(i), y(p.global_risk_index)] as const);
    // Courbe lissée (Catmull-Rom -> Bézier), sans dépassement visible sur peu de points.
    let d = "";
    pts.forEach(([px, py], i) => {
      if (i === 0) d = `M${px},${py}`;
      else {
        const [x0, y0] = pts[i - 1];
        const [xm, ym] = pts[i - 2] ?? pts[i - 1];
        const [x2, y2] = pts[i + 1] ?? [px, py];
        const t = 0.18;
        d += ` C${x0 + (px - xm) * t},${y0 + (py - ym) * t} ${px - (x2 - x0) * t},${py - (y2 - y0) * t} ${px},${py}`;
      }
    });
    const area = pts.length ? `${d} L${pts[pts.length - 1][0]},${H - P.b} L${pts[0][0]},${H - P.b} Z` : "";
    const ticks = [0, yMax / 2, yMax];
    return { x, y, pts, d, area, ticks, yMax };
  }, [points]);

  if (!points.length) return <Empty>La courbe apparaîtra après le premier lancement.</Empty>;

  const last = points[points.length - 1];
  const lvl = LEVEL_STYLE[indexLevel(last.global_risk_index)];
  const h = hover !== null ? points[hover] : null;
  const step = Math.max(1, Math.ceil(points.length / 8));

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="riskFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={lvl.color} stopOpacity="0.16" />
            <stop offset="100%" stopColor={lvl.color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[15, 35, 60].filter((t) => t < geo.yMax).map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={geo.y(t)} y2={geo.y(t)} stroke={LEVEL_STYLE[indexLevel(t)].color} strokeOpacity="0.22" strokeDasharray="3 5" />
          </g>
        ))}
        {geo.ticks.map((t) => (
          <text key={t} x={P.l - 8} y={geo.y(t) + 4} textAnchor="end" className="tnum fill-slate-400 text-[10px]">
            {Math.round(t)}
          </text>
        ))}
        <line x1={P.l} x2={W - P.r} y1={H - P.b} y2={H - P.b} stroke="#E2E8F0" />
        <motion.path d={geo.area} fill="url(#riskFill)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6 }} />
        <motion.path
          d={geo.d}
          fill="none"
          stroke={lvl.color}
          strokeWidth="2.25"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray="1 1"
          initial={{ strokeDashoffset: 1 }}
          animate={{ strokeDashoffset: 0 }}
          transition={{ duration: 0.9, ease: "easeOut" }}
        />
        {points.map((p, i) => (
          <g key={p.date}>
            {(i % step === 0 || i === points.length - 1) && (
              <text x={geo.x(i)} y={H - 8} textAnchor="middle" className="fill-slate-400 text-[10px]">
                {frDate(p.date)}
              </text>
            )}
            <rect
              x={geo.x(i) - (W - P.l - P.r) / Math.max(1, points.length) / 2}
              y={P.t}
              width={(W - P.l - P.r) / Math.max(1, points.length)}
              height={H - P.t - P.b}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
            <circle
              cx={geo.pts[i][0]}
              cy={geo.pts[i][1]}
              r={hover === i ? 5.5 : i === points.length - 1 ? 4.5 : 3}
              fill="#fff"
              stroke={LEVEL_STYLE[indexLevel(p.global_risk_index)].color}
              strokeWidth="2"
              pointerEvents="none"
            />
          </g>
        ))}
        {hover !== null && <line x1={geo.x(hover)} x2={geo.x(hover)} y1={P.t} y2={H - P.b} stroke="#CBD5E1" strokeDasharray="2 3" pointerEvents="none" />}
      </svg>
      {h && hover !== null && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 rounded-xl border border-line bg-white px-3 py-2 text-xs shadow-soft"
          style={{ left: `${(geo.x(hover) / W) * 100}%`, top: 0 }}
        >
          <div className="font-semibold text-ink">{frDate(h.date, { weekday: "short", day: "numeric", month: "long" })}</div>
          <div className="tnum text-ink-soft">
            Indice <b style={{ color: LEVEL_STYLE[indexLevel(h.global_risk_index)].color }}>{fmt1(h.global_risk_index)}</b> / 100 · {h.n_events} événement(s)
          </div>
        </div>
      )}
    </div>
  );
}
