// Compagnon Slime (pixel art), ancré à droite et immobile : bulle de statut contextuelle, chat Copilot intégré.
import { AnimatePresence, motion } from "framer-motion";
import { Eraser, Loader2, SendHorizontal, Sparkles, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useStore, type ChatMessage } from "../store";
import Slime, { useCopilotSlime, useSlimeRisk, type SlimePose, type SlimeState } from "./Slime";

// ------------------------------------------------------------------ rendu Markdown minimal (gras, listes, code)
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") ? (
      <strong key={i} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : part.startsWith("`") ? (
      <code key={i} className="rounded bg-slate-100 px-1 text-[0.92em]">
        {part.slice(1, -1)}
      </code>
    ) : (
      part
    ),
  );
}

function Markdown({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={`l${blocks.length}`} className="my-1 list-disc space-y-0.5 pl-4">
          {list.map((l, i) => (
            <li key={i}>{inline(l)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  text.split("\n").forEach((line) => {
    const m = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (m) list.push(m[1]);
    else {
      flush();
      if (line.trim()) blocks.push(<p key={`p${blocks.length}`}>{inline(line.replace(/^#+\s*/, ""))}</p>);
    }
  });
  flush();
  return <div className="space-y-1.5">{blocks}</div>;
}

// ------------------------------------------------------------------ bulle de chat Copilot
function Avatar({ state }: { state: SlimeState }) {
  // Avatar des réponses : le Slime entier, réduit de moitié (pixels toujours nets).
  return (
    <span className="mb-0.5 flex h-9 w-9 shrink-0 items-end justify-start overflow-hidden rounded-xl pl-1 bg-white ring-1 ring-line">
      <Slime state={state} scale={0.5} box={34} />
    </span>
  );
}

function ChatBubble({ onClose, slime }: { onClose: () => void; slime: SlimeState }) {
  const { chat, chatBusy, ask, clearChat, state, run } = useStore();
  const risk = useSlimeRisk();
  const as = (pose: SlimePose): SlimeState => ({ risk, pose });
  const lastAssistant = chat.map((m) => m.role).lastIndexOf("assistant");
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Questions rapides adaptées à la topologie active (les deux ports les plus critiques servent d'exemples).
  const quick = useMemo(() => {
    const ports = (state?.nodes ?? []).filter((n) => n.type === "port").sort((a, b) => b.criticality - a.criticality);
    const q: { label: string; question: string }[] = [{ label: "Produits menacés", question: "Quels produits finis sont menacés aujourd'hui ?" }];
    if (ports[0]) q.push({ label: `${ports[0].place ?? ports[0].name} bloqué à 80 %`, question: `Que se passe-t-il si ${ports[0].name} est bloqué à 80 % ?` });
    if (ports[1]) q.push({ label: `Fermeture de ${ports[1].place ?? ports[1].name}`, question: `Simule une fermeture de ${ports[1].name}` });
    q.push({ label: "Plan de contournement", question: "Propose un plan de contournement" });
    q.push({ label: "Expliquer les alertes", question: "Explique les alertes actives" });
    return q;
  }, [state]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [chat, chatBusy]);
  useEffect(() => inputRef.current?.focus(), []);

  const send = (q: string) => {
    if (!q.trim()) return;
    ask(q);
    setDraft("");
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92, x: 16 }}
      animate={{ opacity: 1, scale: 1, x: 0 }}
      exit={{ opacity: 0, scale: 0.92, x: 16 }}
      transition={{ type: "spring", stiffness: 340, damping: 28 }}
      style={{ originX: 1, originY: 0.6 }}
      className="fixed bottom-6 right-[136px] z-50 flex h-[min(580px,calc(100vh-48px))] w-[min(390px,calc(100vw-152px))] sm:right-[144px] flex-col overflow-hidden rounded-3xl border border-line bg-white shadow-2xl"
    >
      <header className="flex items-center justify-between border-b border-line bg-gradient-to-r from-sky-50/70 via-white to-emerald-50/60 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-11 w-11 shrink-0 items-end justify-start overflow-hidden rounded-2xl pl-1 bg-white ring-1 ring-line">
            <Slime state={slime} scale={0.625} box={42} />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-sm font-bold">
              <Sparkles size={15} className="text-sky-600" /> Slime · Copilot
            </div>
            <div className="truncate text-[11px] text-ink-mute">{run ? run.topology_name || "chaîne par défaut" : "aucune analyse lancée"}</div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={clearChat} disabled={!chat.length} title="Effacer la conversation" className="rounded-lg p-1.5 text-ink-mute hover:bg-slate-100 hover:text-ink disabled:opacity-40">
            <Eraser size={16} />
          </button>
          <button onClick={onClose} title="Fermer" className="rounded-lg p-1.5 text-ink-mute hover:bg-slate-100 hover:text-ink">
            <X size={16} />
          </button>
        </div>
      </header>

      <div ref={listRef} className="scroll-thin flex-1 space-y-3 overflow-y-auto px-4 py-4 text-sm">
        {!chat.length && (
          <div className="flex items-end gap-2">
            <Avatar state={as("announce")} />
            <div className="rounded-2xl rounded-bl-md bg-slate-50 p-3.5 text-[13px] text-ink-soft">
              Bonjour ! Je surveille la chaîne avec vous. Posez-moi une question en langage naturel, ou choisissez une question rapide ci-dessous. La
              conversation repart de zéro à chaque nouvelle chaîne ou nouveau mode.
            </div>
          </div>
        )}
        {chat.map((m: ChatMessage, i) => (
          <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={`flex items-end gap-2 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            {m.role === "assistant" && <Avatar state={!m.error && i === lastAssistant ? slime : as("idle")} />}
            <div
              className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
                m.role === "user" ? "rounded-br-md bg-ink text-white" : m.error ? "rounded-bl-md bg-slate-100 text-ink-soft" : "rounded-bl-md border border-line bg-white text-ink-soft"
              }`}
            >
              {m.role === "user" ? m.content : <Markdown text={m.content} />}
              {m.role === "assistant" && !m.error && (
                <div className="mt-2 border-t border-line/70 pt-1.5 text-[10.5px] text-ink-mute">
                  {m.mode === "llm" ? "LLM local avec outils" : "Réponse déterministe (règles + graphe)"}
                  {m.note ? ` · ${m.note}` : ""}
                  {!!m.tool_calls?.length && (
                    <details className="mt-1">
                      <summary className="inline-flex cursor-pointer items-center gap-1 font-semibold">
                        <Wrench size={10} /> {m.tool_calls.length} outil(s) appelé(s)
                      </summary>
                      <pre className="scroll-thin mt-1 max-h-40 overflow-auto rounded-lg bg-slate-50 p-2 text-[10px]">
                        {JSON.stringify(m.tool_calls.map((t) => ({ outil: t.name, arguments: t.arguments })), null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        ))}
        {chatBusy && (
          <div className="flex items-end gap-2 text-xs text-ink-mute">
            <Avatar state={as("thinking")} />
            <span className="mb-2 inline-flex items-center gap-1.5">
              <Loader2 size={13} className="animate-spin" /> Slime consulte le graphe…
            </span>
          </div>
        )}
      </div>

      <div className="border-t border-line px-3 pb-3 pt-2.5">
        <div className="scroll-thin mb-2 flex gap-1.5 overflow-x-auto pb-1">
          {quick.map((q) => (
            <button
              key={q.label}
              onClick={() => send(q.question)}
              disabled={chatBusy}
              title={q.question}
              className="shrink-0 rounded-full border border-line bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-ink-soft transition hover:border-sky-200 hover:bg-sky-50 hover:text-sky-800 disabled:opacity-50"
            >
              {q.label}
            </button>
          ))}
        </div>
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <textarea
            ref={inputRef}
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            placeholder="Posez une question sur la chaîne…"
            className="max-h-28 min-h-[40px] flex-1 resize-none rounded-xl border border-line bg-white px-3 py-2.5 text-[13px] focus:border-sky-300 focus:outline-none focus:ring-2 focus:ring-sky-100"
          />
          <button type="submit" disabled={!draft.trim() || chatBusy} className="grid h-10 w-10 place-items-center rounded-xl bg-ink text-white transition hover:bg-slate-800 disabled:opacity-40" aria-label="Envoyer">
            <SendHorizontal size={16} />
          </button>
        </form>
      </div>
    </motion.div>
  );
}

// ------------------------------------------------------------------ compagnon
export default function Companion() {
  const { run, alerts, loading, whatIfNode, state, apiDown } = useStore();
  const [open, setOpen] = useState(false);
  const [showStatus, setShowStatus] = useState(true);

  // Statut contextuel. Un conseil (tension, simulation, panne) affiché dans la bulle fait lever la pancarte.
  const top = alerts.slice().sort((a, b) => b.priority - a.priority)[0];
  const serious = alerts.filter((a) => a.level === "warning" || a.level === "critical");
  const whatIfName = whatIfNode ? state?.nodes.find((n) => n.id === whatIfNode)?.name : null;
  let status: string;
  let advice = true;
  if (apiDown) status = "Je ne joins pas l'API : lancez uvicorn sur le port 8000.";
  else if (loading) [status, advice] = ["J'observe les sources… Médias, Finance, Météo.", false];
  else if (!run) status = "Prêt quand vous l'êtes : lancez une analyse.";
  else if (whatIfName) status = `Mode simulation actif : panne de ${whatIfName}.`;
  else if (serious.length && top) status = `Attention : tension détectée sur ${top.node_name}.`;
  else if (alerts.length && top) status = `À surveiller : ${top.node_name}.`;
  else [status, advice] = ["Chaîne fluide aujourd'hui.", false];
  if (run?.mode === "replay" && !whatIfName && !loading && !apiDown) status = `Replay J${run.day} · ${status}`;

  const slime = useCopilotSlime(open, !open && showStatus && advice);
  if (slime.pose === "sleepy" && !open) status = "zZ… je veille en silence. Bougez la souris pour me réveiller.";

  useEffect(() => {
    setShowStatus(true);
    const t = window.setTimeout(() => setShowStatus(false), 7000);
    return () => window.clearTimeout(t);
  }, [status]);

  // Ancrage fixe : aucune translation, inclinaison ni suivi du défilement.
  return (
    <>
      <AnimatePresence>{open && <ChatBubble onClose={() => setOpen(false)} slime={slime} />}</AnimatePresence>
      <div className="fixed bottom-6 right-2 z-40 sm:right-4">
        <div className="relative">
          <AnimatePresence>
            {!open && showStatus && (
              <motion.div
                key={status}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="pointer-events-none absolute bottom-14 right-[118px] w-max max-w-[240px] rounded-2xl rounded-br-md border border-line bg-white px-3 py-2 text-xs font-medium text-ink-soft shadow-soft"
              >
                {status}
              </motion.div>
            )}
          </AnimatePresence>

          <button
            onClick={() => setOpen((o) => !o)}
            onMouseEnter={() => setShowStatus(true)}
            aria-label="Ouvrir le Copilot (Slime)"
            title="Discuter avec Slime"
            className="relative block rounded-3xl p-1 transition-shadow hover:ring-2 hover:ring-sky-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            <Slime state={slime} scale={1.25} box={90} />
            {!open && (
              <span className="absolute -left-1 top-3 grid h-5 w-5 place-items-center rounded-full bg-white text-sky-600 shadow ring-1 ring-line">
                <Sparkles size={11} />
              </span>
            )}
          </button>
        </div>
      </div>
    </>
  );
}
