// Page « Vigilance météo » : quels sites vont être touchés dans les 16 prochains jours, et avec quelle avance.
// Seuils propres à chaque site (quantile 99 % sur 2010-2020), rang = place du jour dans l'historique du site.
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { CalendarClock, CloudRain, Factory, Gauge, MapPinned, ShieldCheck, Timer, Waves } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import { dataApi } from "../api_data";
import { useStore } from "../store";
import { frDate } from "../theme";
import type { WeatherOverview, WxSite } from "../types_data";
import { Card, Empty } from "./ui";
import { OPTIONS_MONDE, bloquerMonde } from "../carteMonde";
import {
  AXIS, AlertPill, ChartTip, GRID, JobButton, Kpi, NotReady, RankGauge, STATUS, num, pct0, rankColor, rankInk, rankText, useAsync,
} from "./viz";

const POSITRON = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

function siteColor(s: WxSite) {
  if (s.alert_today) return STATUS.critical;
  if (s.forecast_alerts) return STATUS.alert;
  if ((s.score ?? 0) >= 0.9) return STATUS.watch;
  return "#017F8D";
}

function SitesMap({ sites, selected, onSelect }: { sites: WxSite[]; selected: string | null; onSelect: (s: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const data = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: sites.map((s) => ({
      type: "Feature" as const,
      properties: { site: s.site, name: s.name, color: siteColor(s), r: s.forecast_alerts || s.alert_today ? 9 : 6, sel: s.site === selected ? 1 : 0 },
      geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
    })),
  }), [sites, selected]);

  useEffect(() => {
    if (!box.current || map.current) return;
    const m = new maplibregl.Map({ container: box.current, style: POSITRON, center: [30, 30], zoom: 0.9, attributionControl: { compact: true }, ...OPTIONS_MONDE });
    bloquerMonde(m);   // un seul exemplaire du monde, même dézoomé au maximum
    m.on("error", () => undefined);
    m.on("load", () => {
      if (sites.length > 1) {
        const lons = sites.map((s) => s.lon);
        const lats = sites.map((s) => s.lat);
        m.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 40, duration: 0 });
      }
      m.addSource("sites", { type: "geojson", data });
      m.addLayer({ id: "halo", type: "circle", source: "sites", paint: { "circle-radius": ["*", ["get", "r"], 2.2], "circle-color": ["get", "color"], "circle-opacity": 0.15 } });
      m.addLayer({
        id: "pts", type: "circle", source: "sites",
        paint: { "circle-radius": ["get", "r"], "circle-color": ["get", "color"], "circle-stroke-color": "#ffffff", "circle-stroke-width": ["case", ["==", ["get", "sel"], 1], 3, 1.5] },
      });
      m.addLayer({ id: "lbl", type: "symbol", source: "sites", layout: { "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.3], "text-anchor": "top" }, paint: { "text-color": "#334155", "text-halo-color": "#ffffff", "text-halo-width": 1.2 } });
      m.on("click", "pts", (e) => {
        const f = e.features?.[0];
        if (f) onSelect(String(f.properties?.site));
      });
      m.on("mouseenter", "pts", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "pts", () => (m.getCanvas().style.cursor = ""));
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const src = map.current?.getSource("sites") as GeoJSONSource | undefined;
    src?.setData(data);
  }, [data]);

  return (
    <div className="relative h-[340px] overflow-hidden rounded-xl ring-1 ring-line">
      <div ref={box} className="h-full w-full" />
      <div className="absolute bottom-2 left-2 flex flex-wrap gap-2 rounded-lg bg-white/90 px-2 py-1 text-[10.5px] text-ink-soft shadow-sm">
        {[["Alerte aujourd'hui", STATUS.critical], ["Alerte prévue (16 j)", STATUS.alert], ["Score ≥ 0,9", STATUS.watch], ["Normal", "#017F8D"]].map(([l, c]) => (
          <span key={l} className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: c }} />{l}</span>
        ))}
      </div>
    </div>
  );
}

const PERIODS = [{ d: 90, l: "3 mois" }, { d: 365, l: "1 an" }, { d: 1825, l: "5 ans" }];

function SeriesChart({ site, indicators, labels }: { site: WxSite; indicators: string[]; labels: WeatherOverview["indicators"] }) {
  const [ind, setInd] = useState(indicators[0]);
  const [days, setDays] = useState(365);
  useEffect(() => setInd(indicators[0]), [site.site, indicators]);
  const { data, loading, error } = useAsync(() => dataApi.weatherSeries(site.site, ind, days), [site.site, ind, days]);
  const rows = useMemo(() => {
    if (!data) return [];
    const hist = data.series.map((p) => ({ date: p.date, value: p.value, band: p.p10 != null && p.p90 != null ? [p.p10, p.p90] : null, p50: p.p50, alertDot: p.alert ? p.value : null }));
    const fc = data.forecast.map((p) => ({ date: p.date, forecast: p.value, alertDot: p.alert ? p.value : null }));
    return [...hist, ...fc];
  }, [data]);
  const unit = data?.unit ?? "";
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          {indicators.map((i) => (
            <button key={i} onClick={() => setInd(i)} className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 transition ${i === ind ? "bg-ink text-white ring-ink" : "bg-white text-ink-soft ring-line hover:ring-slate-300"}`}>
              {labels[i]?.label ?? i}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p.d} onClick={() => setDays(p.d)} className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${days === p.d ? "bg-slate-100 text-ink" : "text-ink-mute hover:text-ink-soft"}`}>{p.l}</button>
          ))}
        </div>
      </div>
      {error ? <Empty>{error}</Empty> : (
        <div className={`h-[260px] ${loading ? "opacity-60" : ""}`}>
          <ResponsiveContainer>
            <ComposedChart data={rows} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => frDate(d, { month: "short", year: "2-digit" })} minTickGap={40} />
              <YAxis {...AXIS} width={48} />
              <Tooltip content={<ChartTip unit={unit} fmtLabel={(d) => frDate(d, { day: "numeric", month: "long", year: "numeric" })} />} />
              <Area dataKey="band" name="Saison 2010-2020 (p10–p90)" stroke="none" fill="#D6EDEF" fillOpacity={0.55} isAnimationActive={false} />
              <Line dataKey="p50" name="Médiane saisonnière" stroke="#7FC2C9" strokeDasharray="3 3" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              <Line dataKey="value" name="Observé (ERA5)" stroke="#017F8D" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="forecast" name="Prévision 16 j" stroke="#eb6834" strokeWidth={2} strokeDasharray="5 3" dot={{ r: 2 }} isAnimationActive={false} />
              <Scatter dataKey="alertDot" name="Jour en alerte" fill={STATUS.critical} shape="circle" isAnimationActive={false} />
              {data?.threshold != null && (
                <ReferenceLine y={data.threshold} stroke={STATUS.critical} strokeDasharray="6 4" label={{ value: `seuil du site ${num(data.threshold)} ${unit}`, position: "insideTopRight", fill: STATUS.critical, fontSize: 11 }} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      {data && <p className="mt-2 text-[11.5px] text-ink-mute">{labels[ind]?.risk}. Seuil = {labels[ind]?.sens === "bas" ? "centile 1 %" : "centile 99 %"} du site sur 2010-2020 ; points rouges = jours en alerte.</p>}
    </div>
  );
}

function Seasonality({ site }: { site: string }) {
  const { data } = useAsync(() => dataApi.weatherEpisodes(site), [site]);
  const months = useMemo(() => {
    const m = Array.from({ length: 12 }, (_, i) => ({ mois: new Date(2020, i, 1).toLocaleDateString("fr-FR", { month: "short" }), jours: 0 }));
    for (const r of data ?? []) m[new Date(r.mois).getMonth()].jours += r.jours;
    return m;
  }, [data]);
  return (
    <div className="h-[150px]">
      <ResponsiveContainer>
        <BarChart data={months} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="mois" {...AXIS} />
          <YAxis {...AXIS} allowDecimals={false} />
          <Tooltip content={<ChartTip unit="jours" />} cursor={{ fill: "#f1f5f9" }} />
          <Bar dataKey="jours" name="Jours d'alerte (15 ans)" fill="#017F8D" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Heatmap({ sites, labels, onSelect }: { sites: WxSite[]; labels: WeatherOverview["indicators"]; onSelect: (s: string) => void }) {
  const inds = Object.keys(labels);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-[2px] text-[11px]">
        <thead>
          <tr>
            <th className="text-left font-semibold text-ink-mute">Site</th>
            {inds.map((i) => <th key={i} className="px-1 font-semibold text-ink-mute">{labels[i].label}</th>)}
          </tr>
        </thead>
        <tbody>
          {sites.map((s) => (
            <tr key={s.site} className="cursor-pointer" onClick={() => onSelect(s.site)}>
              <td className="whitespace-nowrap pr-2 font-semibold text-ink-soft">{s.name}</td>
              {inds.map((i) => {
                const c = s.indicators_today.find((x) => x.indicator === i);
                if (!s.indicators.includes(i) || !c) return <td key={i} className="rounded bg-slate-50 text-center text-slate-300">–</td>;
                return (
                  <td key={i} title={`${labels[i].label} : ${num(c.value)} ${labels[i].unit} — ${rankText(c.rank)}`} className="tnum rounded px-1 py-1.5 text-center font-semibold" style={{ background: rankColor(c.rank), color: rankInk(c.rank), outline: c.alert ? `2px solid ${STATUS.critical}` : undefined }}>
                    {c.rank == null ? "–" : Math.round(c.rank * 100)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-ink-mute">Rang du dernier jour connu (0–100) : 99 = parmi les 1 % de jours les plus extrêmes du site. Cadre rouge = au-delà du seuil.</p>
    </div>
  );
}

export default function WeatherPage() {
  const { openNode, setView } = useStore();
  const { data, error, loading, reload } = useAsync(() => dataApi.weather(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const sites = data?.sites ?? [];
  const site = sites.find((s) => s.site === selected) ?? sites.find((s) => s.forecast_alerts) ?? sites[0];

  if (loading && !data) return <div className="card p-8 text-center text-sm text-ink-mute">Chargement du volet météo…</div>;
  if (error) return <Empty>{error}</Empty>;
  if (!data?.ready) return <NotReady message={data?.message} />;
  const k = data.kpis;
  const forecastBySite = new Map(sites.map((s) => [s.site, s]));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold tracking-tight">Vigilance météo</h1>
          <p className="text-sm text-ink-mute">Seuils propres à chaque site (Open-Meteo, ERA5 et prévisions à 16 jours). Dernière prévision : {frDate(k.forecast_run, { day: "numeric", month: "long" })}.</p>
        </div>
        <JobButton label="Actualiser les prévisions" run={() => dataApi.job("forecast-meteo")} onDone={reload} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi icon={MapPinned} label="Sites suivis" value={k.sites} sub={`${k.hubs_calibrated} / ${k.hubs_watched} hubs de la chaîne calibrés`} />
        <Kpi icon={CloudRain} label="En alerte aujourd'hui" value={k.alerts_today} tone={k.alerts_today ? "alert" : "ok"} sub="dernier jour observé" />
        <Kpi icon={CalendarClock} label="Alertes prévues" value={k.forecast_alerts} unit="jours-indicateurs" tone={k.forecast_alerts ? "watch" : "ok"} sub={`sur ${k.forecast_sites} site(s), 16 prochains jours`} />
        <Kpi icon={Timer} label="Meilleure avance validée" value={num(k.best_lead_days, 0)} unit="jours" sub={`${k.cases_detected} / ${k.cases} cas réels détectés à l'avance`} />
        <Kpi icon={Gauge} label="Bruit" value={num(k.episodes_per_year, 0)} unit="épisodes / an" sub="tous sites confondus : coût de la vigilance" />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Card title="Carte des sites" icon={MapPinned}>
          <SitesMap sites={sites} selected={site?.site ?? null} onSelect={setSelected} />
        </Card>
        <Card title="Sites et nœuds exposés" icon={Factory}>
          <div className="max-h-[340px] space-y-1.5 overflow-y-auto pr-1">
            {sites.map((s) => (
              <button key={s.site} onClick={() => setSelected(s.site)} className={`w-full rounded-xl border p-2.5 text-left transition ${s.site === site?.site ? "border-sky-200 bg-sky-50/50" : "border-line hover:border-slate-300"}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{s.name} <span className="font-normal text-ink-mute">· {s.country}</span></div>
                    <div className="truncate text-[11px] text-ink-mute">{s.role}{s.fluvial ? " · fluvial" : ""}{s.climat ? ` · ${s.climat}` : ""}</div>
                  </div>
                  <AlertPill alert={s.alert_today || s.forecast_alerts > 0} label={s.alert_today ? "Alerte" : s.forecast_alerts ? `${s.forecast_alerts} prévue(s)` : "Normal"} />
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <span className="w-16 text-[10.5px] text-ink-mute">score {pct0(s.score)}</span>
                  <RankGauge rank={s.score} alert={s.alert_today} threshold={0.99} />
                </div>
                {s.nodes.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {s.nodes.map((n) => (
                      <span key={n.node_id} onClick={(e) => { e.stopPropagation(); openNode(n.node_id); setView("chain"); }} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-ink-soft hover:bg-slate-200">
                        ↳ {n.name}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            ))}
          </div>
        </Card>
      </div>

      {site && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <Card title={`${site.name} : indicateur, seuil et saison`} icon={Waves}>
            <SeriesChart site={site} indicators={site.indicators} labels={data.indicators} />
          </Card>
          <Card title="Saisonnalité du risque" icon={CalendarClock}>
            <Seasonality site={site.site} />
            <div className="mt-3 space-y-1 text-[12px] text-ink-soft">
              <div><b>Indicateurs suivis :</b> {site.indicators.map((i) => data.indicators[i]?.label ?? i).join(", ")}</div>
              <div><b>Épisodes d'alerte :</b> {num(site.episodes_per_year)} par an</div>
              {site.nodes.length > 0 ? (
                <div><b>Produits menacés en aval :</b> {[...new Set(site.nodes.flatMap((n) => n.products))].join(", ") || "aucun"}</div>
              ) : <div className="text-ink-mute">Ce site n'est relié à aucun nœud de la chaîne active.</div>}
            </div>
          </Card>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Alertes prévues (16 jours)" icon={CalendarClock}>
          {data.forecast.length === 0 ? <Empty>Aucune alerte prévue sur les sites suivis.</Empty> : (
            <table className="w-full text-[12.5px]">
              <thead className="text-left text-[11px] text-ink-mute">
                <tr><th className="py-1">Date</th><th>Site</th><th>Indicateur</th><th className="text-right">Valeur / seuil</th><th>Nœuds menacés</th></tr>
              </thead>
              <tbody>
                {data.forecast.map((f, i) => {
                  const s = forecastBySite.get(f.site);
                  return (
                    <tr key={i} className="border-t border-line align-top">
                      <td className="py-1.5 font-semibold">{frDate(f.date)}</td>
                      <td>{s?.name ?? f.site}</td>
                      <td title={f.risk}>{data.indicators[f.indicator]?.label ?? f.indicator}</td>
                      <td className="tnum text-right">{num(f.value)} / {num(f.threshold)} {f.unit}</td>
                      <td className="text-[11px] text-ink-soft">{s?.nodes.map((n) => n.name).join(", ") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Rang du jour par site et indicateur" icon={Gauge}>
          <Heatmap sites={sites} labels={data.indicators} onSelect={setSelected} />
        </Card>
      </div>

      <Card title="Fiabilité : crises réelles rejouées" icon={ShieldCheck}>
        <div className="grid gap-2 md:grid-cols-2">
          {data.validation.map((v, i) => (
            <div key={i} className="flex items-start justify-between gap-3 rounded-xl border border-line p-3">
              <div>
                <div className="text-sm font-bold">{v.cas}</div>
                <div className="text-[11.5px] text-ink-mute">{v.cible} · {v.indicator}</div>
              </div>
              <div className="text-right">
                <AlertPill alert={!v.detected} label={v.detected ? "Détecté avant" : "Non anticipé"} />
                {v.detected && v.lead_days != null && <div className="tnum mt-1 text-[11px] text-ink-soft">{num(v.lead_days, 0)} j d'avance</div>}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11.5px] text-ink-mute">Seuils calculés sur 2010-2020 seulement : les crises de 2021-2024 n'ont jamais servi à les fixer (pas de biais rétrospectif). « Non anticipé » : l'observation ERA5 ne dépasse le seuil qu'au moment du choc ; les prévisions archivées donnent parfois l'avance (Helene).</p>
      </Card>
    </div>
  );
}
