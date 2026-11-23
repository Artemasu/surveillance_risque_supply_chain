// Tiroir « Preuves & Traçabilité » : explication en clair, preuves multi-sources, contrat JSON brut.
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Braces, ChevronDown, FileSearch, GitBranch, Link2, Link2Off, MapPin, Quote, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useStore } from "../store";
import { AGENT_STYLE, LEVEL_STYLE, TYPE_LABEL, frDate, pct } from "../theme";
import type { CorrelatedSignal, EventEnvelope, NodeState } from "../types";
import { AgentBadge, LevelBadge, SoftBar } from "./ui";
import { RankGauge, rankText, signed } from "./viz";

function LinkTag({ link }: { link: "exact" | "elargi" | null }) {
  if (!link) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-semibold text-slate-500">
        <Link2Off size={11} /> non rattaché
      </span>
    );
  }
  return link === "exact" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-700 ring-1 ring-emerald-100" title="Le nœud est cité nommément par l'événement : poids plein.">
      <Link2 size={11} /> Rattachement exact
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10.5px] font-semibold text-amber-800 ring-1 ring-amber-100" title="Rattaché par un indice large (matière, mot-clé sectoriel, pays) : contribution pondérée ×0,40.">
      <Link2 size={11} /> Rattachement élargi ×0,40
    </span>
  );
}

function Accordion({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-ink-soft hover:text-ink">
        <span className="inline-flex items-center gap-2">
          <Braces size={15} /> {title}
        </span>
        <motion.span animate={{ rotate: open ? 180 : 0 }}>
          <ChevronDown size={16} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="border-t border-line p-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  return <pre className="scroll-thin max-h-80 overflow-auto rounded-lg bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-700">{JSON.stringify(value, null, 2)}</pre>;
}

function EventCard({ env }: { env: EventEnvelope }) {
  const ev = env.event;
  const s = AGENT_STYLE[env.agent];
  return (
    <div className="rounded-xl border p-3.5" style={{ borderColor: s.border, background: `linear-gradient(180deg, ${s.bg2}88, #fff 70%)` }}>
      <div className="flex flex-wrap items-center gap-1.5">
        <AgentBadge agent={env.agent} size="xs" />
        <LinkTag link={env.link} />
        <span className="ml-auto text-[11px] text-ink-mute">{frDate(ev.date, { day: "numeric", month: "short", year: "numeric" })}</span>
      </div>
      <p className="mt-2 text-sm font-medium text-ink">{ev.event.label}</p>
      {ev.location?.name && (
        <p className="mt-1 flex items-center gap-1 text-[11px] text-ink-mute">
          <MapPin size={11} /> {ev.location.name}
        </p>
      )}
      {ev.media.length > 0 && (
        <ul className="mt-2 space-y-1">
          {ev.media.slice(0, 4).map((m) => (
            <li key={m.source_id} className="flex gap-1.5 text-xs text-ink-soft">
              <Quote size={11} className="mt-0.5 shrink-0" style={{ color: s.text }} />
              <span>
                {m.titre} <span className="text-ink-mute">· {m.source_id}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {ev.weather && (
        <div className="tnum mt-2 text-xs text-ink-soft">
          <p>
            {ev.weather.forecast ? "Prévision" : "Relevé"} {ev.weather.date} · vent {ev.weather.wind_max_kmh ?? "—"} km/h · rafales {ev.weather.gust_max_kmh ?? "—"} km/h · pluie{" "}
            {ev.weather.precip_mm ?? "—"} mm
          </p>
          {ev.weather.indicator && (
            <div className="mt-1.5 rounded-lg bg-teal-50/60 p-2 text-[11.5px] text-teal-900">
              <b>{ev.weather.indicator.replace("_", " ")}</b> : {ev.weather.value} {ev.weather.unit} pour un seuil du site de {ev.weather.threshold} {ev.weather.unit} ·{" "}
              {rankText(ev.weather.rank)} ({ev.weather.level})
              {ev.weather.risk && <div className="mt-0.5 text-teal-800/80">{ev.weather.risk}</div>}
              <div className="mt-1.5"><RankGauge rank={ev.weather.rank ?? null} alert /></div>
            </div>
          )}
        </div>
      )}
      {ev.finance && (
        <div className="tnum mt-2 text-xs text-ink-soft">
          {ev.finance.change_5d_pct != null ? (
            <p>
              {ev.finance.name} : {ev.finance.change_5d_pct > 0 ? "+" : ""}
              {ev.finance.change_5d_pct} % sur 5 séances{ev.finance.zscore != null ? ` · écart ${ev.finance.zscore} σ` : ""}
            </p>
          ) : (
            <p>{ev.finance.name}{ev.finance.detail ? ` : ${ev.finance.detail}` : ""}</p>
          )}
          {ev.finance.kind && ev.finance.kind !== "instrument" && ev.finance.indicator != null && (
            <div className="mt-1.5 rounded-lg bg-amber-50/70 p-2 text-[11.5px] text-amber-900">
              {ev.finance.measure === "niveau" ? "Niveau" : `Variation sur ${ev.finance.horizon} obs.`} : <b>{signed(ev.finance.indicator)}{ev.finance.measure === "niveau" ? "" : " %"}</b>
              {ev.finance.threshold != null && ` (seuil ${signed(ev.finance.threshold)}${ev.finance.measure === "niveau" ? "" : " %"})`} · {rankText(ev.finance.rank)}
              {ev.finance.impact && <div className="mt-0.5 text-amber-800/80">{ev.finance.impact}</div>}
              <div className="mt-1.5"><RankGauge rank={ev.finance.rank ?? null} alert /></div>
            </div>
          )}
          {(ev.finance.kind === "sanction" || ev.finance.kind === "procedure") && ev.finance.impact && (
            <div className="mt-1.5 rounded-lg bg-rose-50 p-2 text-[11.5px] text-rose-900">{ev.finance.impact}</div>
          )}
        </div>
      )}
      <p className="mt-2 text-[10.5px] text-ink-mute">
        Extracteur {ev.meta.extractor} · confiance {pct(ev.meta.confidence)}
        {ev.donnees_manquantes.length ? ` · données manquantes : ${ev.donnees_manquantes.join(", ")}` : ""}
      </p>
    </div>
  );
}

function SignalRow({ sig }: { sig: CorrelatedSignal }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        {sig.agents.map((a) => (
          <AgentBadge key={a} agent={a} size="xs" />
        ))}
        <LinkTag link={sig.link} />
        {sig.corroborated && <span className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-semibold text-sky-700 ring-1 ring-sky-100">corroboré multi-sources</span>}
      </div>
      <div className="mt-1.5 text-ink-soft">{sig.label}</div>
      <div className="tnum mt-1 text-[10.5px] text-ink-mute">
        famille {sig.family} · gravité {pct(sig.severity)} × confiance {pct(sig.confidence)} → contribution {pct(sig.contribution)}
      </div>
    </div>
  );
}

function NodeEvidence({ node }: { node: NodeState }) {
  const { alerts, events, state, setWhatIfNode, closeDrawer } = useStore();
  const alert = alerts.find((a) => a.node_id === node.id);
  const names = new Map((state?.nodes ?? []).map((n) => [n.id, n.name]));
  const sigIds = new Set([...(alert?.signal_ids ?? []), ...node.signal_ids]);
  const signals = (events?.signals ?? []).filter((s) => sigIds.has(s.id));
  const evIds = new Set(signals.flatMap((s) => s.event_ids));
  const evs = (events?.events ?? []).filter((e) => evIds.has(e.event.event.id));
  const origin = node.path.length > 1 ? names.get(node.path[0]) : null;
  const lvl = LEVEL_STYLE[node.level];

  return (
    <div className="space-y-5">
      <div className="rounded-2xl p-4" style={{ background: lvl.bg }}>
        <div className="flex items-center justify-between">
          <LevelBadge level={node.level} />
          <span className="tnum text-2xl font-extrabold" style={{ color: lvl.color }}>
            {pct(node.risk)}
          </span>
        </div>
        <div className="mt-3">
          <SoftBar value={node.risk} level={node.level} height={7} />
        </div>
        <div className="tnum mt-3 grid grid-cols-2 gap-2 text-center text-xs">
          <div className="rounded-xl bg-white/80 py-2">
            <div className="text-ink-mute">Risque direct</div>
            <div className="text-base font-bold text-ink">{pct(node.direct)}</div>
          </div>
          <div className="rounded-xl bg-white/80 py-2">
            <div className="text-ink-mute">Risque propagé</div>
            <div className="text-base font-bold text-ink">{pct(node.propagated)}</div>
          </div>
        </div>
      </div>

      <section>
        <h3 className="label mb-2">En clair</h3>
        <p className="text-sm leading-relaxed text-ink-soft">
          {node.risk < 0.01
            ? `Aucun signal ne pèse aujourd'hui sur ${node.name}.`
            : node.propagated > node.direct
              ? `${node.name} n'est pas directement touché par un événement : son risque vient surtout d'un problème en amont${origin ? `, chez ${origin}` : ""}, qui se transmet le long de la chaîne.`
              : `${node.name} est directement concerné par des signaux observés (${signals.length} signal(aux) corrélé(s)).`}
          {node.stock_days > 0 && ` Son stock de sécurité couvre environ ${node.stock_days} jour(s).`}
        </p>
        {alert && <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-ink-soft">{alert.rule}</p>}
      </section>

      {node.path.length > 1 && (
        <section>
          <h3 className="label mb-2 flex items-center gap-1.5">
            <GitBranch size={13} /> Chemin de propagation
          </h3>
          <div className="flex flex-wrap items-center gap-1.5">
            {node.path.map((id, i) => (
              <span key={id} className="inline-flex items-center gap-1.5">
                <span className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${id === node.id ? "bg-ink text-white" : "bg-slate-100 text-ink-soft"}`}>{names.get(id) ?? id}</span>
                {i < node.path.length - 1 && <ArrowRight size={13} className="text-ink-mute" />}
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <h3 className="label mb-2">Signaux corrélés ({signals.length})</h3>
        <div className="space-y-2">{signals.length ? signals.map((s) => <SignalRow key={s.id} sig={s} />) : <p className="text-xs text-ink-mute">Aucun signal sur ce nœud ni sur son chemin.</p>}</div>
      </section>

      {evs.length > 0 && (
        <section>
          <h3 className="label mb-2">Preuves multi-sources ({evs.length})</h3>
          <div className="space-y-2.5">
            {evs.map((e) => (
              <EventCard key={e.event.event.id} env={e} />
            ))}
          </div>
        </section>
      )}

      <button
        className="btn-ghost w-full justify-center"
        onClick={() => {
          setWhatIfNode(node.id);
          closeDrawer();
        }}
      >
        Simuler une panne de ce nœud
      </button>

      <Accordion title="Inspecter le contrat JSON brut">
        <div className="space-y-3">
          {alert && (
            <div>
              <div className="label mb-1">Alert</div>
              <Json value={alert} />
            </div>
          )}
          <div>
            <div className="label mb-1">NodeState</div>
            <Json value={node} />
          </div>
          {signals.length > 0 && (
            <div>
              <div className="label mb-1">CorrelatedSignal[]</div>
              <Json value={signals} />
            </div>
          )}
          {evs.length > 0 && (
            <div>
              <div className="label mb-1">NormalizedEvent[]</div>
              <Json value={evs.map((e) => e.event)} />
            </div>
          )}
        </div>
      </Accordion>
    </div>
  );
}

function EventEvidence({ env }: { env: EventEnvelope }) {
  const { openNode } = useStore();
  return (
    <div className="space-y-5">
      <EventCard env={env} />
      <section>
        <h3 className="label mb-2">Nœuds rattachés</h3>
        {env.nodes.length ? (
          <div className="flex flex-wrap gap-1.5">
            {env.nodes.map((id, i) => (
              <button key={id} onClick={() => openNode(id)} className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-ink-soft hover:bg-slate-200">
                {env.node_names[i] ?? id} <ArrowRight size={12} />
              </button>
            ))}
          </div>
        ) : (
          <p className="text-sm text-ink-mute">Événement détecté mais rattaché à aucun nœud : il reste un signal faible, sans effet sur le score.</p>
        )}
        {env.link === "elargi" && (
          <p className="mt-2 text-xs text-ink-mute">Rattachement élargi : le nœud n'est pas cité nommément, sa contribution au risque est donc pondérée ×0,40.</p>
        )}
      </section>
      <Accordion title="Inspecter le contrat JSON brut">
        <Json value={env.extraction ? { event: env.event, extraction: env.extraction } : env.event} />
      </Accordion>
    </div>
  );
}

export default function EvidenceDrawer() {
  const { drawer, closeDrawer, state } = useStore();
  const node = useMemo(() => (drawer?.kind === "node" ? state?.nodes.find((n) => n.id === drawer.nodeId) : undefined), [drawer, state]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeDrawer();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeDrawer]);

  return (
    <AnimatePresence>
      {drawer && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-slate-900/10 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={closeDrawer} />
          <motion.aside
            role="dialog"
            aria-label="Preuves et traçabilité"
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-line bg-white shadow-2xl"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            <header className="flex items-start justify-between gap-3 border-b border-line px-6 py-5">
              <div className="min-w-0">
                <div className="label flex items-center gap-1.5">
                  <FileSearch size={13} /> Preuves & traçabilité
                </div>
                <h2 className="mt-1 truncate text-lg font-bold">
                  {drawer.kind === "node" ? node?.name ?? drawer.nodeId : drawer.envelope.event.event.label}
                </h2>
                {drawer.kind === "node" && node && (
                  <p className="text-xs text-ink-mute">
                    {TYPE_LABEL[node.type]}
                    {node.place ? ` · ${node.place}` : ""}
                    {node.country ? `, ${node.country}` : ""} · criticité {pct(node.criticality)}
                  </p>
                )}
              </div>
              <button onClick={closeDrawer} className="rounded-lg p-1.5 text-ink-mute hover:bg-slate-100 hover:text-ink" aria-label="Fermer">
                <X size={18} />
              </button>
            </header>
            <div className="scroll-thin flex-1 overflow-y-auto px-6 py-5">
              {drawer.kind === "node" ? node ? <NodeEvidence node={node} /> : <p className="text-sm text-ink-mute">Nœud introuvable.</p> : <EventEvidence env={drawer.envelope} />}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
