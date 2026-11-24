// Page « Marchés & fournisseurs » : repérer un fournisseur qui va coûter plus cher, livrer en retard ou faire défaut.
// Cinq familles de signaux (marchés, bourse, santé des fournisseurs, règles, sanctions et propriété).
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, Building2, CircleDollarSign, Fuel, Gavel, Landmark, LineChart as LineIcon, Ship, ShieldAlert, X,
} from "lucide-react";
import { useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { dataApi } from "../api_data";
import { useStore } from "../store";
import { frDate } from "../theme";
import type { FinSignal, FinSupplier } from "../types_data";
import { Card, Empty } from "./ui";
import { AXIS, AlertPill, ChartTip, GRID, JobButton, Kpi, NotReady, RankGauge, SERIES, STATUS, num, pct0, rankText, signed, useAsync } from "./viz";

const FAMILY_ORDER = ["énergie", "fret", "change", "métaux", "prix fournisseurs", "fournisseurs"];
const fullDate = (d: string) => frDate(d, { day: "numeric", month: "long", year: "numeric" });

function SignalTile({ s, active, onClick }: { s: FinSignal; active: boolean; onClick: () => void }) {
  const ind = s.mesure === "variation_%" ? `${signed(s.indicateur)} %` : num(s.indicateur, 2);
  const seuil = s.seuil == null ? "—" : s.mesure === "variation_%" ? `${signed(s.seuil)} %` : num(s.seuil, 2);
  return (
    <button onClick={onClick} className={`rounded-xl border p-3 text-left transition ${active ? "border-sky-300 bg-sky-50/50" : s.en_alerte ? "border-orange-200 bg-orange-50/40 hover:border-orange-300" : "border-line hover:border-slate-300"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-bold">{s.nom}</div>
          <div className="tnum text-[11px] text-ink-mute">{num(s.valeur_brute, 3)} {s.unite} · {frDate(s.date_valeur)}</div>
        </div>
        <AlertPill alert={s.en_alerte} />
      </div>
      <div className="mt-2 flex items-baseline justify-between text-[12px]">
        <span className="tnum font-bold text-ink">{ind}</span>
        <span className="tnum text-ink-mute">seuil {seuil}</span>
      </div>
      <div className="mt-1.5"><RankGauge rank={s.rang} alert={s.en_alerte} threshold={s.horizon <= 4 && s.mesure === "variation_%" ? 0.95 : s.mesure === "niveau" ? 0.95 : 0.99} /></div>
      {s.nodes.length > 0 && <div className="mt-1.5 truncate text-[10.5px] text-ink-mute">↳ {s.nodes.map((n) => n.name).join(", ")}</div>}
    </button>
  );
}

function SignalDetail({ s }: { s: FinSignal }) {
  const [start, setStart] = useState("2019-01-01");
  const { data } = useAsync(() => dataApi.financeSeries(s.signal, start), [s.signal, start]);
  const rows = useMemo(() => (data?.series ?? []).map((p) => ({ ...p, alerteVal: p.alerte ? p.indicateur : null })), [data]);
  const unitInd = s.mesure === "variation_%" ? "%" : s.unite;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-bold">{s.nom}</div>
          <div className="text-[11.5px] text-ink-mute">{s.impact} · source {s.source} · {rankText(s.rang)}</div>
        </div>
        <div className="flex gap-1">
          {[["2010-01-01", "Depuis 2010"], ["2019-01-01", "Depuis 2019"], ["2024-01-01", "Depuis 2024"]].map(([d, l]) => (
            <button key={d} onClick={() => setStart(d)} className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${start === d ? "bg-slate-100 text-ink" : "text-ink-mute"}`}>{l}</button>
          ))}
        </div>
      </div>
      <div className="h-[220px]">
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 8, right: 12, left: -6, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => frDate(d, { month: "short", year: "2-digit" })} minTickGap={40} />
            <YAxis {...AXIS} width={46} />
            <Tooltip content={<ChartTip unit={unitInd} fmtLabel={fullDate} />} />
            <Area dataKey="indicateur" name={s.mesure === "variation_%" ? `Variation sur ${s.horizon} obs.` : "Niveau"} stroke="#017F8D" fill="#D6EDEF" fillOpacity={0.5} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            <Line dataKey="alerteVal" name="En alerte" stroke={STATUS.critical} strokeWidth={3} dot={false} isAnimationActive={false} />
            {s.seuil != null && <ReferenceLine y={s.seuil} stroke={STATUS.critical} strokeDasharray="6 4" label={{ value: `seuil ${num(s.seuil)} ${unitInd}`, position: "insideTopLeft", fill: STATUS.critical, fontSize: 11 }} />}
            <ReferenceLine y={0} stroke="#cbd5e1" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 h-[110px]">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 4, right: 12, left: -6, bottom: 0 }}>
            <XAxis dataKey="date" hide />
            <YAxis {...AXIS} width={46} domain={["auto", "auto"]} />
            <Tooltip content={<ChartTip unit={s.unite} fmtLabel={fullDate} />} />
            <Line dataKey="valeur" name="Valeur brute" stroke="#52514e" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {s.nodes.length > 0 && (
        <p className="mt-2 text-[11.5px] text-ink-soft">
          <b>Nœuds de la chaîne :</b> {s.nodes.map((n) => `${n.name} (${n.link})`).join(", ")}
        </p>
      )}
    </div>
  );
}

const DEFAULT_BASE = ["brent", "gaz_europe", "cuivre", "gscpi", "eur_usd"];

function Base100() {
  const { data } = useAsync(() => dataApi.base100("2019-01-01"), []);
  const [picked, setPicked] = useState<string[]>(DEFAULT_BASE);
  const all = (data?.signals ?? []).filter((s) => !s.startsWith("bourse_") && s !== "gscpi");
  const shown = picked.filter((p) => all.includes(p)).slice(0, 5);
  // Couleur attachée au signal (ordre du catalogue), jamais à sa position dans la sélection
  const colorOf = (s: string) => SERIES[all.indexOf(s) % SERIES.length];
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {all.map((s) => {
          const on = shown.includes(s);
          return (
            <button key={s} onClick={() => setPicked((p) => (on ? p.filter((x) => x !== s) : [...p, s].slice(-5)))} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${on ? "bg-white text-ink ring-slate-300" : "text-ink-mute ring-line"}`}>
              <span className="h-2 w-2 rounded-full" style={{ background: on ? colorOf(s) : "#cbd5e1" }} /> {s}
            </button>
          );
        })}
      </div>
      <div className="h-[240px]">
        <ResponsiveContainer>
          <LineChart data={data?.series ?? []} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => frDate(d, { month: "short", year: "2-digit" })} minTickGap={40} />
            <YAxis {...AXIS} width={40} />
            <Tooltip content={<ChartTip fmtLabel={fullDate} />} />
            <ReferenceLine y={100} stroke="#cbd5e1" />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />
            {shown.map((s) => <Line key={s} dataKey={s} name={s} stroke={colorOf(s)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-ink-mute">Base 100 au 1er janvier 2019, une valeur par semaine (5 signaux au plus). GSCPI exclu : c'est déjà un écart à la normale.</p>
    </div>
  );
}

function ScoreChart() {
  const { data } = useAsync(() => dataApi.financeScore("2019-01-01"), []);
  return (
    <div className="h-[150px]">
      <ResponsiveContainer>
        <AreaChart data={data ?? []} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} tickFormatter={(d) => frDate(d, { year: "numeric" })} minTickGap={60} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}`} />
          <Tooltip content={<ChartTip fmtLabel={fullDate} />} />
          <ReferenceLine y={0.99} stroke={STATUS.critical} strokeDasharray="4 4" />
          <Area dataKey="score" name="Score finance (max hebdo)" stroke="#017F8D" fill="#D6EDEF" strokeWidth={1.5} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function SupplierDrawer({ cle, onClose }: { cle: string; onClose: () => void }) {
  const { openNode, setView } = useStore();
  const { data } = useAsync(() => dataApi.supplier(cle), [cle]);
  return (
    <motion.aside initial={{ x: 420 }} animate={{ x: 0 }} exit={{ x: 420 }} transition={{ type: "spring", stiffness: 260, damping: 30 }} className="fixed right-0 top-0 z-50 h-full w-[400px] max-w-full overflow-y-auto border-l border-line bg-white p-5 shadow-2xl">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-lg font-extrabold">{data?.fournisseur ?? cle}</div>
          <div className="text-[12px] text-ink-mute">{data?.nom_legal} · {data?.pays} · {data?.produit}</div>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 hover:bg-slate-100" aria-label="Fermer"><X size={18} /></button>
      </div>
      {data && (
        <div className="mt-4 space-y-4 text-[12.5px]">
          <div className="flex flex-wrap gap-1.5">
            {(data.alertes ?? []).length ? data.alertes.map((a: string) => <span key={a} className="rounded-full bg-orange-50 px-2 py-0.5 font-semibold text-orange-700">{a}</span>) : <AlertPill alert={false} label="Aucune alerte" />}
          </div>
          {data.stock?.length > 0 && (
            <div>
              <div className="label mb-1">Cours de bourse (2 ans)</div>
              <div className="h-[120px]">
                <ResponsiveContainer>
                  <LineChart data={data.stock}>
                    <XAxis dataKey="date" hide />
                    <YAxis {...AXIS} width={40} domain={["auto", "auto"]} />
                    <Tooltip content={<ChartTip fmtLabel={fullDate} />} />
                    <Line dataKey="valeur" name="Cours" stroke="#017F8D" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {data.bourse && <div className="tnum text-ink-soft">Variation sur 20 séances : <b>{signed(data.bourse["variation_20j_%"])} %</b>{data.bourse.seuil != null ? ` (seuil ${signed(data.bourse.seuil)} %)` : ""}</div>}
            </div>
          )}
          <div>
            <div className="label mb-1">Propriété</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-lg bg-slate-100 px-2 py-1 font-semibold">{data.nom_legal}</span>
              {(data.proprietaires ?? []).map((p: any) => (
                <span key={p.nom} className="inline-flex items-center gap-1.5">→ <span className="rounded-lg bg-violet-50 px-2 py-1 font-semibold text-violet-700">{p.nom}</span><span className="text-[10.5px] text-ink-mute">{p.type}</span></span>
              ))}
              {!(data.proprietaires ?? []).length && <span className="text-ink-mute">aucune maison mère déclarée</span>}
            </div>
            {data.lei && <div className="mt-1 text-[11px] text-ink-mute">LEI {data.lei}</div>}
          </div>
          <div>
            <div className="label mb-1">Sanctions</div>
            {(data.sanctions ?? []).length ? (
              <ul className="space-y-1">{data.sanctions.map((s: any, i: number) => <li key={i} className="rounded-lg bg-rose-50 px-2 py-1 text-rose-800">{s.role} : {s.liste} — {s.nom_sur_liste} {s.date_inscription ? `(${frDate(s.date_inscription, { day: "numeric", month: "short", year: "numeric" })})` : ""}</li>)}</ul>
            ) : <div className="text-ink-mute">{data.sanctions_count ? `${data.sanctions_count} correspondance(s) (détail : python -m src.jobs ingest-finance)` : "Aucune correspondance sur les listes UE et US."}</div>}
          </div>
          <div>
            <div className="label mb-1">Procédures collectives (BODACC)</div>
            {(data.procedures_collectives ?? []).length ? data.procedures_collectives.map((p: any, i: number) => <div key={i}>{p.date} · {p.type} · {p.tribunal}</div>) : <div className="text-ink-mute">{data.siren ? "Aucune procédure publiée." : "Entreprise non française : non applicable."}</div>}
          </div>
          {data.node && (
            <div className="rounded-xl border border-line p-3">
              <div className="label mb-1">Dans la chaîne active</div>
              <button onClick={() => { openNode(data.node); setView("chain"); onClose(); }} className="font-bold text-sky-700 hover:underline">{data.node_name}</button>
              {data.products?.length > 0 && <div className="mt-1 text-ink-soft">Produits en aval : {data.products.join(", ")}</div>}
            </div>
          )}
          {(data.donnees_manquantes ?? []).length > 0 && <div className="text-[11px] text-ink-mute">Données manquantes : {data.donnees_manquantes.join(", ")}</div>}
        </div>
      )}
    </motion.aside>
  );
}

function Suppliers({ rows, onOpen }: { rows: FinSupplier[]; onOpen: (c: string) => void }) {
  return (
    <table className="w-full text-[12.5px]">
      <thead className="text-left text-[11px] text-ink-mute">
        <tr><th className="py-1">Fournisseur</th><th>Bourse 20 j</th><th>Maison mère</th><th className="text-center">Sanctions</th><th>Nœud</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.cle} onClick={() => onOpen(s.cle)} className="cursor-pointer border-t border-line hover:bg-slate-50">
            <td className="py-2"><div className="font-bold">{s.nom}</div><div className="text-[11px] text-ink-mute">{s.pays} · {s.produit}</div></td>
            <td className="tnum" style={{ color: s.bourse?.en_alerte ? STATUS.critical : undefined }}>{s.bourse ? `${signed(s.bourse["variation_20j_%"])} %` : "non coté"}</td>
            <td className="text-[11.5px]">{s.proprietaires.map((p) => p.nom).join(", ") || "—"}</td>
            <td className="tnum text-center font-semibold" style={{ color: s.sanctions ? STATUS.critical : undefined }}>{s.sanctions || "—"}</td>
            <td className="text-[11.5px] text-ink-soft">{s.node_name ?? "—"}</td>
            <td><AlertPill alert={s.en_alerte} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Rules() {
  const [zone, setZone] = useState<string | undefined>(undefined);
  const { data } = useAsync(() => dataApi.rules("2023-01-01", zone), [zone]);
  return (
    <div>
      <div className="mb-2 flex gap-1">
        {[[undefined, "Toutes"], ["US", "États-Unis"], ["UE", "Union européenne"]].map(([z, l]) => (
          <button key={l} onClick={() => setZone(z)} className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${zone === z ? "bg-slate-100 text-ink" : "text-ink-mute"}`}>{l}</button>
        ))}
      </div>
      <ul className="max-h-[300px] space-y-1.5 overflow-y-auto pr-1">
        {(data ?? []).slice(0, 60).map((r) => (
          <li key={r.id} className="rounded-xl border border-line p-2.5">
            <div className="flex items-start justify-between gap-2">
              <a href={r.url ?? undefined} target="_blank" rel="noreferrer" className="text-[12.5px] font-semibold leading-snug hover:underline">{r.titre}</a>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-bold ${r.zone === "UE" ? "bg-indigo-50 text-indigo-700" : "bg-slate-100 text-slate-700"}`}>{r.zone}</span>
            </div>
            <div className="tnum mt-1 text-[11px] text-ink-mute">
              publié le {frDate(r.publication, { day: "numeric", month: "short", year: "numeric" })}
              {r.entree_en_vigueur && ` · en vigueur le ${frDate(r.entree_en_vigueur, { day: "numeric", month: "short", year: "numeric" })}`}
              {r.delai_jours != null && ` · préavis ${num(r.delai_jours, 0)} j`}
              {r.famille && ` · ${r.famille}`}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Diesel() {
  const { data } = useAsync(() => dataApi.diesel(), []);
  const rows = (data?.countries ?? []).sort((a, b) => b.prix - a.prix);
  return (
    <div>
      <div className="h-[200px]">
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="pays" {...AXIS} />
            <YAxis {...AXIS} domain={[0, "auto"]} />
            <Tooltip content={<ChartTip unit="€/L" />} cursor={{ fill: "#f1f5f9" }} />
            <Bar dataKey="prix" name="Gazole TTC" radius={[4, 4, 0, 0]}>
              {rows.map((r) => <Cell key={r.pays} fill={r.pays === "EU" ? "#52514e" : "#017F8D"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-2 w-full text-[11.5px]">
        <thead className="text-left text-ink-mute"><tr><th>Pays</th><th className="text-right">€/L</th><th className="text-right">4 sem.</th><th className="text-right">Brent → pompe</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.pays} className="tnum border-t border-line">
              <td className="py-1 font-semibold">{r.pays}</td>
              <td className="text-right">{num(r.prix, 3)}</td>
              <td className="text-right">{signed(r.var_4s)} %</td>
              <td className="text-right text-ink-mute">{r.decalage_semaines != null ? `${num(r.decalage_semaines, 0)} sem. (r = ${num(r.correlation, 2)})` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function FinancePage() {
  const { data, error, loading, reload } = useAsync(() => dataApi.finance(), []);
  const [sel, setSel] = useState<string | null>(null);
  const [supplier, setSupplier] = useState<string | null>(null);
  const signals = data?.signals ?? [];
  const groups = useMemo(() => {
    const g = new Map<string, FinSignal[]>();
    for (const s of signals) g.set(s.famille, [...(g.get(s.famille) ?? []), s]);
    return [...g.entries()].sort((a, b) => FAMILY_ORDER.indexOf(a[0]) - FAMILY_ORDER.indexOf(b[0]));
  }, [signals]);
  const selected = signals.find((s) => s.signal === sel) ?? signals[0];

  if (loading && !data) return <div className="card p-8 text-center text-sm text-ink-mute">Chargement du volet finance…</div>;
  if (error) return <Empty>{error}</Empty>;
  if (!data?.ready) return <NotReady message={data?.message} />;
  const k = data.kpis;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold tracking-tight">Marchés & fournisseurs</h1>
          <p className="text-sm text-ink-mute">Seuils calibrés sur 2010-2020 pour chaque signal. Dernière valeur : {frDate(k.last_value, { day: "numeric", month: "long" })}.</p>
        </div>
        <JobButton label="Collecter les signaux" run={() => dataApi.job("ingest-finance")} onDone={reload} />
      </div>

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi icon={Activity} label="Signaux en alerte" value={`${k.signals_alert}/${k.signals}`} tone={k.signals_alert ? "alert" : "ok"} sub="marchés et bourse" />
        <Kpi icon={LineIcon} label="Score finance" value={pct0(k.score)} tone={(k.score ?? 0) >= 0.99 ? "alert" : (k.score ?? 0) >= 0.9 ? "watch" : "ink"} sub="0,5 = jour ordinaire (recalibré)" />
        <Kpi icon={Ship} label="Pression supply chain" value={num(k.gscpi, 2)} unit="σ" tone={k.gscpi_alert ? "alert" : "ink"} sub="GSCPI, NY Fed" />
        <Kpi icon={CircleDollarSign} label="Euro en dollars" value={num(k.eur_usd, 3)} sub={`${signed(k.eur_usd_var)} % sur 20 séances`} />
        <Kpi icon={Building2} label="Fournisseurs en alerte" value={`${k.suppliers_alert}/${k.suppliers}`} tone={k.suppliers_alert ? "alert" : "ok"} sub="bourse, sanctions, BODACC" />
        <Kpi icon={Gavel} label="Règles (90 j)" value={k.rules_90d} sub="Federal Register et UE" />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Card title="Signaux par famille" icon={Activity}>
          <div className="space-y-4">
            {groups.map(([fam, list]) => (
              <div key={fam}>
                <div className="label mb-1.5 capitalize">{fam}</div>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {list.map((s) => <SignalTile key={s.signal} s={s} active={s.signal === selected?.signal} onClick={() => setSel(s.signal)} />)}
                </div>
              </div>
            ))}
          </div>
        </Card>
        <div className="space-y-5">
          <Card title="Détail du signal" icon={LineIcon}>{selected ? <SignalDetail s={selected} /> : <Empty>Choisir un signal.</Empty>}</Card>
          <Card title="Score finance depuis 2019" icon={Activity}><ScoreChart /></Card>
        </div>
      </div>

      <Card title="Fournisseurs suivis" icon={ShieldAlert} action={<span className="text-[11px] text-ink-mute">cliquer pour la fiche complète</span>}>
        <Suppliers rows={data.suppliers} onOpen={setSupplier} />
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Marchés en base 100" icon={Landmark} className="lg:col-span-2"><Base100 /></Card>
        <Card title="Gazole à la pompe" icon={Fuel}><Diesel /></Card>
      </div>

      <Card title="Règles et taxes" icon={Gavel}><Rules /></Card>

      <AnimatePresence>{supplier && <SupplierDrawer cle={supplier} onClose={() => setSupplier(null)} />}</AnimatePresence>
    </div>
  );
}
