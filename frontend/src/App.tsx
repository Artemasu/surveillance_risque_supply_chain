import { AnimatePresence, motion } from "framer-motion";
import { LayoutDashboard, Loader2, Network, Play, PlugZap } from "lucide-react";
import { API_URL } from "./api";
import ChainView from "./components/ChainView";
import Companion from "./components/Companion";
import Dashboard from "./components/Dashboard";
import EvidenceDrawer from "./components/EvidenceDrawer";
import Header from "./components/Header";
import { AgentBadge, Segmented } from "./components/ui";
import { useStore } from "./store";

function Welcome() {
  const { launch, loading, apiDown, mode, scenarios, scenarioId } = useStore();
  const sc = scenarios.find((s) => s.id === scenarioId);
  if (apiDown) {
    return (
      <div className="card mx-auto mt-10 max-w-xl p-8 text-center">
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-slate-50 text-ink-mute ring-1 ring-line">
          <PlugZap size={22} />
        </div>
        <h2 className="mt-4 text-lg font-bold">L'API ne répond pas</h2>
        <p className="mt-2 text-sm text-ink-soft">
          Le front-end attend le backend FastAPI sur <code className="rounded bg-slate-100 px-1.5">{API_URL}</code>.
        </p>
        <pre className="mt-4 rounded-xl bg-slate-50 p-3 text-left text-xs text-ink-soft">uvicorn src.api.main:app --port 8000</pre>
        <button className="btn-ghost mx-auto mt-4" onClick={() => window.location.reload()}>
          Réessayer
        </button>
      </div>
    );
  }
  return (
    <div className="card mx-auto mt-10 max-w-2xl overflow-hidden">
      <div className="bg-gradient-to-br from-emerald-50 via-white to-sky-50 p-8 text-center">
        <h2 className="text-2xl font-extrabold tracking-tight">Bienvenue dans la tour de contrôle</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-ink-soft">
          Trois agents surveillent votre chaîne d'approvisionnement. Le moteur de graphe corrèle leurs signaux et propage le risque jusqu'à vos produits finis.
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <AgentBadge agent="media" />
          <AgentBadge agent="finance" />
          <AgentBadge agent="weather" />
        </div>
        <button onClick={launch} disabled={loading} className="btn mx-auto mt-6 bg-ink px-5 py-2.5 text-white hover:bg-slate-800">
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={15} fill="currentColor" />}
          {loading ? "Analyse en cours…" : mode === "replay" ? "Lancer le replay" : "Lancer l'analyse live"}
        </button>
        {mode === "replay" && sc && <p className="mt-3 text-xs text-ink-mute">{sc.title}</p>}
      </div>
    </div>
  );
}

export default function App() {
  const { run, state, error, view, setView } = useStore();

  return (
    <div className="min-h-screen pb-24">
      <Header />
      <main className="mx-auto max-w-[1440px] px-4 pr-[104px] pt-6 sm:px-6 sm:pr-[120px]">
        <AnimatePresence>
          {error && (
            <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mb-4 rounded-xl border border-orange-100 bg-orange-50/70 px-4 py-2.5 text-sm text-orange-900">
              {error}
            </motion.div>
          )}
        </AnimatePresence>
        {!run || !state ? (
          <Welcome />
        ) : (
          <>
            <div className="mb-5 flex items-center justify-between">
              <Segmented
                value={view}
                onChange={setView}
                options={[
                  { value: "dashboard", label: "Tour de contrôle", icon: LayoutDashboard },
                  { value: "chain", label: "Chaîne & simulation", icon: Network },
                ]}
              />
            </div>
            <AnimatePresence mode="wait">
              <motion.div key={view} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.22 }}>
                {view === "dashboard" ? <Dashboard /> : <ChainView />}
              </motion.div>
            </AnimatePresence>
          </>
        )}
        <footer className="mt-10 text-center text-[11px] text-ink-mute">
          Alerte Précoce Supply Chain · API {API_URL} · <a className="underline decoration-dotted" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">documentation OpenAPI</a>
        </footer>
      </main>
      <EvidenceDrawer />
      <Companion />
    </div>
  );
}
