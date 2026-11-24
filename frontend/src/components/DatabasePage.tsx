// Page « Base & Graphe » : volumétrie de data/aegis.duckdb, graphe unifié (chaîne + événements) et explorateur
// paginé des tables Médias, Météo, Finance et de la base unifiée (lecture seule, export CSV).
import { ChevronLeft, ChevronRight, CloudSun, Database, Download, Link2, Network, Newspaper, Search, ShieldAlert, Table2, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { telecharger } from "../api";
import { dataApi, type DbQuery, type DbTableInfo } from "../api_data";
import { useStore } from "../store";
import { AGENT_STYLE, frDate } from "../theme";
import type { AgentName } from "../types";
import { Card, Empty, Segmented } from "./ui";
import UnifiedGraph from "./UnifiedGraph";
import { AlertPill, Kpi, num, rankColor, rankInk, useAsync } from "./viz";

const fmtInt = (n?: number) => (n == null ? "—" : n.toLocaleString("fr-FR"));
const DOMAIN_LABEL: Record<string, string> = { media: "Médias", weather: "Météo", finance: "Finance", unified: "Base unifiée" };
const FILTER_LABEL: Record<string, string> = { site: "Site / nœud", symbol: "Symbole", indicator: "Indicateur", family: "Famille", agent: "Domaine", zone: "Zone", type: "Type", topology: "Topologie" };
const RANK_COLS = new Set(["rang", "score_risque", "intensite", "confiance", "score_site"]);

function Summary() {
  const { data } = useAsync(() => dataApi.dbSummary(), []);
  const d = data?.domains;
  if (data && !data.ready) return <Empty>Base absente : lancez <code>python -m src.jobs import-notebooks</code>.</Empty>;
  return (
    <div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi icon={Newspaper} label="Médias" value={fmtInt(d?.media?.evenements)} unit="événements" sub={`${fmtInt(d?.media?.articles)} article(s) fusionné(s)`} />
        <Kpi icon={CloudSun} label="Météo" value={fmtInt(d?.weather?.indicateurs)} unit="indicateurs" sub={`${fmtInt(d?.weather?.sites)} sites · ${fmtInt(d?.weather?.previsions)} prévisions · ${fmtInt(d?.weather?.jours_en_alerte)} jours en alerte`} />
        <Kpi icon={TrendingUp} label="Finance" value={fmtInt(d?.finance?.valeurs)} unit="valeurs" sub={`${fmtInt(d?.finance?.signaux)} signaux · ${fmtInt(d?.finance?.regles)} règles`} />
        <Kpi icon={ShieldAlert} label="Fournisseurs & sanctions" value={fmtInt(d?.finance?.fournisseurs)} unit="fiches" sub={`${fmtInt(d?.finance?.sanctions)} entités sanctionnées (UE, US)`} />
        <Kpi icon={Link2} label="Base unifiée" value={fmtInt(d?.unified?.liens)} unit="liens événement → nœud" sub={`${fmtInt(d?.unified?.evenements)} événements · ${fmtInt(d?.unified?.executions)} exécutions · ${fmtInt(d?.unified?.liaisons_referentiel)} liaisons du référentiel`} />
      </div>
      {data?.ready && (
        <p className="mt-2 text-[11.5px] text-ink-mute">
          <Database size={12} className="mr-1 inline" />
          {data.db} · {num(data.size_mb)} Mo · {data.tables} tables · {fmtInt(data.rows_total)} lignes au total · lecture seule
        </p>
      )}
    </div>
  );
}

function Cell({ col, v }: { col: string; v: any }) {
  if (v == null) return <span className="text-slate-300">—</span>;
  if (typeof v === "boolean") return col === "alerte" || col === "alert" ? <AlertPill alert={v} label={v ? "Oui" : "Non"} /> : <span>{v ? "oui" : "non"}</span>;
  if (col === "domaine" && AGENT_STYLE[v as AgentName]) {
    const s = AGENT_STYLE[v as AgentName];
    return <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: s.bg, color: s.text }}>{s.label}</span>;
  }
  if (typeof v === "number") {
    if (RANK_COLS.has(col) && v >= 0 && v <= 1) {
      return <span className="tnum rounded px-1.5 py-0.5 font-semibold" style={{ background: rankColor(v), color: rankInk(v) }}>{num(v * 100, 1)}</span>;
    }
    return <span className="tnum">{num(v, Math.abs(v) < 10 ? 3 : 1)}</span>;
  }
  if (col === "url" && typeof v === "string") return <a className="text-sky-700 underline" href={v} target="_blank" rel="noreferrer">lien</a>;
  const s = String(v);
  return <span title={s.length > 60 ? s : undefined}>{s.length > 90 ? `${s.slice(0, 89)}…` : s}</span>;
}

function FilterSelect({ table, column, value, onChange }: { table: string; column: string; value: string; onChange: (v: string) => void }) {
  const { data } = useAsync(() => dataApi.dbValues(table, column), [table, column]);
  return (
    <select className="select !w-40 !py-1 text-xs" value={value} onChange={(e) => onChange(e.target.value)} aria-label={FILTER_LABEL[column] ?? column}>
      <option value="">{FILTER_LABEL[column] ?? column} : tous</option>
      {(data ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
    </select>
  );
}

function TableExplorer() {
  const { data: tables } = useAsync(() => dataApi.dbTables(), []);
  const [name, setName] = useState("unified");
  const [qInput, setQInput] = useState("");
  const [p, setP] = useState<DbQuery>({ limit: 50, offset: 0 });
  const spec: DbTableInfo | undefined = tables?.find((t) => t.name === name);

  useEffect(() => {
    const t = setTimeout(() => setP((x) => ({ ...x, q: qInput || undefined, offset: 0 })), 300);
    return () => clearTimeout(t);
  }, [qInput]);
  const pick = (n: string) => {
    setName(n);
    setQInput("");
    setP({ limit: p.limit, offset: 0 });
  };
  const set = (k: keyof DbQuery, v: string | number | undefined) => setP((x) => ({ ...x, [k]: v === "" ? undefined : v, offset: 0 }));
  const page = useAsync(() => dataApi.dbTable(name, p), [name, JSON.stringify(p)]);
  const d = page.data;
  const groups = useMemo(() => {
    const g = new Map<string, DbTableInfo[]>();
    for (const t of tables ?? []) g.set(t.domain, [...(g.get(t.domain) ?? []), t]);
    return [...g.entries()];
  }, [tables]);
  const from = d ? Math.min(d.total, d.offset + 1) : 0;
  const to = d ? Math.min(d.total, d.offset + d.rows.length) : 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        {groups.map(([dom, list]) => (
          <div key={dom} className="flex flex-wrap items-center gap-1">
            <span className="label mr-1">{DOMAIN_LABEL[dom] ?? dom}</span>
            {list.map((t) => (
              <button key={t.name} disabled={!t.available} onClick={() => pick(t.name)} title={t.description}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold ring-1 transition disabled:opacity-40 ${t.name === name ? "bg-ink text-white ring-ink" : "bg-white text-ink-soft ring-line hover:ring-slate-300"}`}>
                {t.label.split(" : ")[1] ?? t.label}
              </button>
            ))}
          </div>
        ))}
      </div>
      {spec && <p className="text-[11.5px] text-ink-mute">{spec.description}</p>}

      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-slate-50 p-2">
        <label className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-mute" />
          <input value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="Recherche texte…" className="w-52 rounded-lg border border-line bg-white py-1 pl-7 pr-2 text-xs focus:border-sky-300 focus:outline-none" />
        </label>
        {spec?.has_date && (
          <>
            <input type="date" className="rounded-lg border border-line bg-white px-2 py-0.5 text-xs" value={p.date_from ?? ""} onChange={(e) => set("date_from", e.target.value)} aria-label="Depuis" />
            <span className="text-xs text-ink-mute">→</span>
            <input type="date" className="rounded-lg border border-line bg-white px-2 py-0.5 text-xs" value={p.date_to ?? ""} onChange={(e) => set("date_to", e.target.value)} aria-label="Jusqu'au" />
          </>
        )}
        {spec?.filters.map((f) => <FilterSelect key={`${name}-${f}`} table={name} column={f} value={(p[f as keyof DbQuery] as string) ?? ""} onChange={(v) => set(f as keyof DbQuery, v)} />)}
        {spec?.alert && (
          <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-soft">
            <input type="checkbox" checked={p.alert === "true"} onChange={(e) => set("alert", e.target.checked ? "true" : "")} /> En alerte seulement
          </label>
        )}
        {spec?.rank && (
          <label className="inline-flex items-center gap-1.5 text-xs text-ink-soft">
            {spec.rank} ≥
            <select className="select !w-20 !py-0.5 text-xs" value={p.min_rank ?? ""} onChange={(e) => set("min_rank", e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">—</option>
              {[0.5, 0.9, 0.95, 0.99].map((v) => <option key={v} value={v}>{v * 100}</option>)}
            </select>
          </label>
        )}
        <button onClick={() => telecharger(dataApi.dbCsvUrl(name, p), `${name}.csv`)} className="btn-ghost ml-auto !py-1 text-xs">
          <Download size={13} /> Export CSV
        </button>
      </div>

      {page.error ? <Empty>{page.error}</Empty> : (
        <div className={`overflow-x-auto rounded-xl ring-1 ring-line ${page.loading ? "opacity-60" : ""}`}>
          <table className="w-full text-[12px]">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-ink-mute">
              <tr>{(d?.columns ?? []).map((c) => <th key={c} className="whitespace-nowrap px-2.5 py-2 font-semibold">{c.replace(/_/g, " ")}</th>)}</tr>
            </thead>
            <tbody>
              {(d?.rows ?? []).map((r, i) => (
                <tr key={i} className="border-t border-line hover:bg-slate-50/70">
                  {d!.columns.map((c) => <td key={c} className="max-w-[360px] whitespace-nowrap px-2.5 py-1.5 align-top">{c === "date" && typeof r[c] === "string" ? frDate(r[c], { day: "numeric", month: "short", year: "numeric" }) : <Cell col={c} v={r[c]} />}</td>)}
                </tr>
              ))}
              {d && d.rows.length === 0 && <tr><td className="px-3 py-6 text-center text-ink-mute" colSpan={d.columns.length || 1}>Aucune ligne avec ces filtres.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-ink-soft">
        <span className="tnum">{d ? `${fmtInt(from)}–${fmtInt(to)} sur ${fmtInt(d.total)} lignes` : "…"}</span>
        <div className="flex items-center gap-2">
          <select className="select !w-24 !py-0.5 text-xs" value={p.limit} onChange={(e) => setP((x) => ({ ...x, limit: Number(e.target.value), offset: 0 }))} aria-label="Lignes par page">
            {[25, 50, 100, 250, 500].map((n) => <option key={n} value={n}>{n} / page</option>)}
          </select>
          <button className="btn-ghost !px-2 !py-1" disabled={!d || d.offset === 0} onClick={() => setP((x) => ({ ...x, offset: Math.max(0, (x.offset ?? 0) - (x.limit ?? 50)) }))} aria-label="Page précédente"><ChevronLeft size={14} /></button>
          <span className="tnum">page {d ? fmtInt(Math.floor(d.offset / d.limit) + 1) : "—"} / {d ? fmtInt(Math.max(1, Math.ceil(d.total / d.limit))) : "—"}</span>
          <button className="btn-ghost !px-2 !py-1" disabled={!d || d.offset + d.limit >= d.total} onClick={() => setP((x) => ({ ...x, offset: (x.offset ?? 0) + (x.limit ?? 50) }))} aria-label="Page suivante"><ChevronRight size={14} /></button>
        </div>
      </div>
    </div>
  );
}

export default function DatabasePage() {
  const { run } = useStore();
  const [tab, setTab] = useState<"graph" | "tables">("graph");
  const graph = useAsync(() => dataApi.unifiedGraph(), [run?.as_of, run?.topology, run?.global_risk_index]);
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-extrabold tracking-tight">Base de données & graphe</h1>
        <p className="text-sm text-ink-mute">Tout le contenu de la base unifiée DuckDB (Médias, Météo, Finance) et du graphe qui les relie, en lecture seule.</p>
      </div>
      <Summary />
      <Segmented value={tab} onChange={setTab} options={[{ value: "graph", label: "Graphe unifié", icon: Network }, { value: "tables", label: "Explorateur des tables", icon: Table2 }]} />
      {tab === "graph" ? (
        <Card title={`Graphe unifié${graph.data?.topology_name ? ` · ${graph.data.topology_name}` : ""}`} icon={Network}>
          {graph.error ? <Empty>{graph.error}</Empty> : !graph.data ? <div className="p-8 text-center text-sm text-ink-mute">Chargement du graphe…</div> : <UnifiedGraph data={graph.data} />}
        </Card>
      ) : (
        <Card title="Explorateur des tables" icon={Table2}><TableExplorer /></Card>
      )}
    </div>
  );
}
