// Barre supérieure de pilotage : mode, scénario + jour (replay) ou topologie (live), LLM local, lancement.
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Cpu, History, Loader2, Play, Radio, RefreshCw } from "lucide-react";
import { useStore } from "../store";
import { AGENTS, AGENT_STYLE, frDate } from "../theme";
import { AGENT_ICON, Segmented } from "./ui";

function Select({ value, onChange, children, label }: { value: string; onChange: (v: string) => void; children: React.ReactNode; label: string }) {
  return (
    <label className="relative block min-w-0 flex-1">
      <span className="sr-only">{label}</span>
      <select className="select truncate" value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
      <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-mute" />
    </label>
  );
}

function SourceDots() {
  const { run } = useStore();
  return (
    <div className="flex items-center gap-1.5" title="État des trois sources au dernier lancement">
      {AGENTS.map((a) => {
        const s = AGENT_STYLE[a];
        const Icon = AGENT_ICON[a];
        const sum = run?.agents[a];
        const state = !sum ? "idle" : sum.status !== "success" ? "down" : sum.degraded ? "partial" : "ok";
        const title = !sum
          ? `${s.label} : pas encore lancé`
          : `${s.label} : ${state === "down" ? "indisponible" : state === "partial" ? "partiel" : "OK"} · ${sum.count} événement(s)${sum.message ? ` · ${sum.message}` : ""}`;
        return (
          <span
            key={a}
            title={title}
            className={`relative grid h-8 w-8 place-items-center rounded-full border transition ${state === "idle" ? "opacity-40" : ""}`}
            style={{ background: state === "down" ? "#F8FAFC" : s.bg, borderColor: state === "down" ? "#CBD5E1" : s.border, color: state === "down" ? "#94A3B8" : s.text }}
          >
            <Icon size={14} strokeWidth={2.2} />
            {state !== "idle" && state !== "ok" && (
              <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-white" style={{ background: state === "down" ? "#94A3B8" : "#D97706" }} />
            )}
          </span>
        );
      })}
    </div>
  );
}

export default function Header() {
  const st = useStore();
  const scenario = st.scenarios.find((s) => s.id === st.scenarioId);
  const daysTotal = scenario?.days ?? 1;
  const story = scenario?.storyline?.[String(st.day)];
  const dayDate = scenario?.start_date
    ? new Date(new Date(`${scenario.start_date}T12:00:00`).getTime() + (st.day - 1) * 86400000).toISOString().slice(0, 10)
    : null;
  const pctDay = daysTotal > 1 ? ((st.day - 1) / (daysTotal - 1)) * 100 : 100;
  // Modèle réellement actif, lu sur /health (jamais figé dans le code) : « auto / qwen2.5:3b » sans OLLAMA_MODEL.
  const active = st.health?.llm_model_active || st.health?.llm_model;
  const llmLabel = active ? `${st.health?.llm_auto ? "auto / " : ""}${active}` : "Ollama";

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1440px] flex-nowrap items-center justify-between gap-2 px-4 py-3 sm:px-6">
        <div className="flex shrink-0 items-center gap-2.5 pr-1" title="A.E.G.I.S. — Automated Early-warning & Graph Intelligence for Supply-chain">
          {/* Logo : le slime calme du Copilot, en pixel art net (classe slime-sprite = image-rendering: pixelated). */}
          <div className="grid h-9 w-9 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-sky-50 to-white ring-1 ring-line">
            <img
              src={`${import.meta.env.BASE_URL}copilot/slime_calm_idle.png`}
              alt="A.E.G.I.S."
              draggable={false}
              className="slime-sprite block select-none"
              style={{ width: 33 }}
            />
          </div>
          <div className="min-w-0 leading-tight">
            <div className="text-[15px] font-extrabold tracking-[0.06em]">A.E.G.I.S.</div>
            <div className="hidden max-w-[22rem] truncate text-[11px] font-medium text-ink-mute 2xl:block">Automated Early-warning & Graph Intelligence for Supply-chain</div>
          </div>
        </div>

        <div className="shrink-0">
          <Segmented
            value={st.mode}
            onChange={st.setMode}
            options={[
              { value: "replay", label: "Replay scénario", icon: History },
              { value: "live", label: "Live", icon: Radio },
            ]}
          />
        </div>

        <div className="flex min-w-0 max-w-[260px] flex-1 items-center gap-3 truncate">
          {st.mode === "replay" ? (
            <Select label="Scénario" value={st.scenarioId} onChange={st.setScenarioId}>
              {st.scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.fictional ? "Fictif · " : ""}
                  {s.title}
                </option>
              ))}
            </Select>
          ) : (
            <Select label="Topologie" value={st.topologyRef} onChange={st.setTopologyRef}>
              {st.topologies.map((t) => (
                <option key={t.ref ?? ""} value={t.ref ?? ""}>
                  {t.company ? `${t.company} — ` : ""}
                  {t.name} ({t.nodes} nœuds)
                </option>
              ))}
            </Select>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={() => st.setUseLlm(!st.useLlm)}
            className={`inline-flex items-center gap-2 whitespace-nowrap rounded-xl border px-3 py-2 text-xs font-semibold transition ${st.useLlm ? "border-violet-200 bg-violet-50 text-violet-700" : "border-line bg-white text-ink-mute hover:text-ink-soft"}`}
            title={`Extraction des événements médias par LLM local (${llmLabel}). Les 6 groupes d'articles les plus pertinents passent par le LLM (15 s max chacun, 30 s au total) ; le reste et toute panne basculent sur la baseline NLP.`}
            aria-pressed={st.useLlm}
          >
            <Cpu size={14} />
            LLM local
            <span className={`relative h-4 w-7 rounded-full transition ${st.useLlm ? "bg-violet-400" : "bg-slate-200"}`}>
              <motion.span layout className="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow" style={{ left: st.useLlm ? 14 : 2 }} />
            </span>
          </button>
          <SourceDots />
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={st.launch}
            disabled={st.loading || !!st.apiDown}
            className="btn relative whitespace-nowrap bg-ink text-white shadow-sm hover:bg-slate-800"
          >
            {st.loading ? <Loader2 size={16} className="animate-spin" /> : st.run && !st.dirty ? <RefreshCw size={15} /> : <Play size={15} fill="currentColor" />}
            {st.loading ? "Analyse en cours…" : st.run && !st.dirty ? "Relancer" : "Lancer l'analyse"}
            {st.dirty && st.run && !st.loading && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-amber-400" title="Sélection modifiée depuis la dernière analyse" />}
          </motion.button>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {st.mode === "replay" && scenario && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-line/70 bg-slate-50/60"
          >
            <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 sm:px-6">
              <div className="flex min-w-[240px] items-center gap-3">
                <span className="label whitespace-nowrap">Jour</span>
                <input
                  type="range"
                  className="range w-44"
                  min={1}
                  max={daysTotal}
                  value={st.day}
                  onChange={(e) => st.setDay(Number(e.target.value))}
                  style={{ ["--pct" as string]: `${pctDay}%` }}
                />
                <span className="tnum whitespace-nowrap text-sm font-bold">
                  J{st.day}
                  <span className="font-medium text-ink-mute"> / {daysTotal}</span>
                </span>
                <span className="whitespace-nowrap text-xs text-ink-mute">{frDate(dayDate, { weekday: "short", day: "numeric", month: "short" })}</span>
              </div>
              <AnimatePresence mode="wait">
                <motion.p
                  key={`${st.scenarioId}-${st.day}`}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  className="min-w-0 flex-1 text-sm text-ink-soft"
                >
                  {story ?? "Aucun résumé narratif pour ce jour."}
                </motion.p>
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
