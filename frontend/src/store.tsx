// État global de l'application : sélection du pilotage, résultats du pipeline, Copilot, tiroir de preuves.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import type {
  Alert, ChatTurn, EventEnvelope, EventsResponse, GraphState, Health, PipelineRunResult, Scenario, ToolCall, Topology,
} from "./types";

export type Mode = "replay" | "live";
export type View = "dashboard" | "chain" | "weather" | "finance" | "history" | "database" | "onboarding";

export interface ChatMessage extends ChatTurn {
  mode?: string;
  note?: string;
  tool_calls?: ToolCall[];
  error?: boolean;
}

export type DrawerTarget = { kind: "node"; nodeId: string } | { kind: "event"; envelope: EventEnvelope } | null;

interface Store {
  health: Health | null;
  apiDown: string | null;
  scenarios: Scenario[];
  topologies: Topology[];
  mode: Mode;
  setMode: (m: Mode) => void;
  scenarioId: string;
  setScenarioId: (id: string) => void;
  day: number;
  setDay: (d: number) => void;
  topologyRef: string;
  setTopologyRef: (r: string) => void;
  refreshTopologies: () => Promise<void>;
  useLlm: boolean;
  setUseLlm: (v: boolean) => void;

  run: PipelineRunResult | null;
  state: GraphState | null;
  alerts: Alert[];
  events: EventsResponse | null;
  loading: boolean;
  error: string | null;
  launch: () => Promise<void>;
  dirty: boolean;

  chat: ChatMessage[];
  chatBusy: boolean;
  ask: (q: string) => Promise<void>;
  clearChat: () => void;

  drawer: DrawerTarget;
  openNode: (nodeId: string) => void;
  openEvent: (e: EventEnvelope) => void;
  closeDrawer: () => void;

  whatIfNode: string | null;
  setWhatIfNode: (id: string | null) => void;

  view: View;
  setView: (v: View) => void;
}

const Ctx = createContext<Store | null>(null);

export const useStore = () => {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore hors du StoreProvider");
  return s;
};

const runKey = (mode: Mode, scenario: string, topology: string) => (mode === "replay" ? `replay:${scenario}` : `live:${topology}`);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiDown, setApiDown] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [topologies, setTopologies] = useState<Topology[]>([]);
  const [mode, setMode] = useState<Mode>("replay");
  const [scenarioId, setScenarioIdRaw] = useState("");
  const [day, setDay] = useState(1);
  const [topologyRef, setTopologyRef] = useState("");
  const [useLlm, setUseLlm] = useState(false);

  const [run, setRun] = useState<PipelineRunResult | null>(null);
  const [state, setState] = useState<GraphState | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const chatContext = useRef<Record<string, unknown>>({});
  const lastRunKey = useRef<string | null>(null);

  const [drawer, setDrawer] = useState<DrawerTarget>(null);
  const [whatIfNode, setWhatIfNode] = useState<string | null>(null);
  const [view, setView] = useState<View>("dashboard");

  const setScenarioId = useCallback(
    (id: string) => {
      setScenarioIdRaw(id);
      const sc = scenarios.find((s) => s.id === id);
      if (sc?.days) setDay(sc.days);
    },
    [scenarios],
  );

  const refreshViews = useCallback(async () => {
    const [st, al, ev] = await Promise.all([api.state(), api.alerts(), api.events()]);
    setState(st);
    setAlerts(al);
    setEvents(ev);
  }, []);

  // Chargement initial : santé de l'API, scénarios, topologies, dernier run éventuel.
  useEffect(() => {
    (async () => {
      try {
        const [h, sc, tp] = await Promise.all([api.health(), api.scenarios(), api.topologies()]);
        setHealth(h);
        setScenarios(sc);
        setTopologies(tp);
        setUseLlm(h.llm_enabled);
        const last = h.last_run ?? null;
        if (last) {
          setRun(last);
          setMode(last.mode === "live" ? "live" : "replay");
          if (last.scenario) setScenarioIdRaw(last.scenario);
          else if (sc[0]) setScenarioIdRaw(sc[0].id);
          if (last.day) setDay(last.day);
          setTopologyRef(last.topology ?? "");
          lastRunKey.current = runKey(last.mode === "live" ? "live" : "replay", last.scenario ?? "", last.topology ?? "");
          await refreshViews();
        } else {
          if (sc[0]) {
            setScenarioIdRaw(sc[0].id);
            setDay(sc[0].days ?? 1);
          }
          const active = tp.find((t) => t.active) ?? tp[0];
          setTopologyRef(active?.ref ?? "");
        }
        setApiDown(null);
      } catch (e) {
        setApiDown((e as Error).message);
      }
    })();
  }, [refreshViews]);

  const clearChat = useCallback(() => {
    setChat([]);
    chatContext.current = {};
  }, []);

  const launch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const key = runKey(mode, scenarioId, topologyRef);
      const res = await api.run(
        mode === "replay"
          ? { mode, scenario: scenarioId || null, day, use_llm: useLlm }
          : { mode, topology: topologyRef || null, use_llm: useLlm },
      );
      setRun(res);
      await refreshViews();
      api.health().then(setHealth).catch(() => undefined);   // modèle LLM actif à jour dans l'info-bulle
      setTopologies(await api.topologies());
      // Nouvelle chaîne ou nouveau mode : le Copilot repart d'une conversation vide.
      if (lastRunKey.current !== key) clearChat();
      lastRunKey.current = key;
      setWhatIfNode(null);
      setApiDown(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [mode, scenarioId, day, topologyRef, useLlm, refreshViews, clearChat]);

  const ask = useCallback(
    async (q: string) => {
      const question = q.trim();
      if (!question || chatBusy) return;
      const history: ChatTurn[] = chat.filter((m) => !m.error).map(({ role, content }) => ({ role, content })).slice(-8);
      setChat((c) => [...c, { role: "user", content: question }]);
      setChatBusy(true);
      try {
        const r = await api.chat(question, history, chatContext.current);
        chatContext.current = r.context ?? {};
        setChat((c) => [...c, { role: "assistant", content: r.answer, mode: r.mode, note: r.note, tool_calls: r.tool_calls }]);
      } catch (e) {
        setChat((c) => [...c, { role: "assistant", content: (e as Error).message, error: true }]);
      } finally {
        setChatBusy(false);
      }
    },
    [chat, chatBusy],
  );

  const dirty = useMemo(() => {
    if (!run) return true;
    if (mode !== (run.mode === "live" ? "live" : "replay")) return true;
    if (mode === "replay") return run.scenario !== scenarioId || run.day !== day;
    return (run.topology ?? "") !== topologyRef;
  }, [run, mode, scenarioId, day, topologyRef]);

  // Après une inscription : la nouvelle chaîne et son scénario modèle apparaissent dans les sélecteurs.
  const refreshTopologies = useCallback(async () => {
    const [tp, sc] = await Promise.all([api.topologies(), api.scenarios()]);
    setTopologies(tp);
    setScenarios(sc);
  }, []);

  const value: Store = {
    health, apiDown, scenarios, topologies, mode, setMode, scenarioId, setScenarioId, day, setDay, topologyRef,
    setTopologyRef, refreshTopologies, useLlm, setUseLlm, run, state, alerts, events, loading, error, launch, dirty, chat, chatBusy, ask,
    clearChat, drawer,
    openNode: (nodeId) => setDrawer({ kind: "node", nodeId }),
    openEvent: (envelope) => setDrawer({ kind: "event", envelope }),
    closeDrawer: () => setDrawer(null),
    whatIfNode, setWhatIfNode, view, setView,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
