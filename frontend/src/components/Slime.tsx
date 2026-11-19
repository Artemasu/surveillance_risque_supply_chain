// Compagnon Slime en pixel art : 15 sprites (3 couleurs de risque x 5 poses) de public/copilot/,
// produits par scripts/prepare_copilot_sprites.py. Affichage statique : aucun mouvement lié au scroll.
import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { indexLevel } from "../theme";
import type { RiskLevel } from "../types";

export type SlimeRisk = "calm" | "warning" | "critical";
export type SlimePose = "idle" | "announce" | "thinking" | "happy" | "sleepy";
export interface SlimeState {
  risk: SlimeRisk;
  pose: SlimePose;
}

const RISKS: SlimeRisk[] = ["calm", "warning", "critical"];
const POSES: SlimePose[] = ["idle", "announce", "thinking", "happy", "sleepy"];
const MIN_THINKING_MS = 700;      // une réponse déterministe arrive en ~100 ms : l'ampoule doit rester lisible
const HAPPY_MS = 4000;
// 2 minutes ; `?slimeSleep=10` dans l'URL raccourcit le délai (en secondes) pour une démonstration.
const sleepParam = typeof window !== "undefined" ? Number(new URLSearchParams(window.location.search).get("slimeSleep")) : 0;
const SLEEP_AFTER_MS = sleepParam > 0 ? sleepParam * 1000 : 120_000;

export const slimeSrc = ({ risk, pose }: SlimeState) => `${import.meta.env.BASE_URL}copilot/slime_${risk}_${pose}.png`;

// Préchargement des 15 sprites : un changement d'état ne fait jamais clignoter une image vide.
if (typeof window !== "undefined") for (const risk of RISKS) for (const pose of POSES) new Image().src = slimeSrc({ risk, pose });

const RISK_LABEL: Record<SlimeRisk, string> = { calm: "risque faible", warning: "risque modéré", critical: "risque élevé" };
const POSE_LABEL: Record<SlimePose, string> = {
  idle: "au repos", announce: "avec une annonce", thinking: "réfléchit", happy: "réponse prête", sleepy: "en veille",
};

/** Couleur du Slime : normal = calm (faible), à surveiller = warning (modéré), alerte ou critique = critical (élevé). */
export function slimeRiskFor(level: RiskLevel): SlimeRisk {
  return level === "ok" ? "calm" : level === "info" ? "warning" : "critical";
}

/** Couleur du scénario actif (Replay comme Live), d'après l'indice de risque global. */
export function useSlimeRisk(): SlimeRisk {
  const { state } = useStore();
  return state ? slimeRiskFor(indexLevel(state.global_risk_index)) : "calm";
}

/**
 * Sprite pixel art, net grâce à `image-rendering: pixelated`. `scale` agrandit la résolution native (corps de 58 px).
 * La boîte a une hauteur fixe et aligne le sprite en bas : la pancarte ou l'ampoule ne déplacent pas le corps.
 * Seule animation : une respiration très lente quand le Slime dort (CSS, sans déplacement).
 */
export default function Slime({ state, scale = 1, box, className = "" }: { state: SlimeState; scale?: number; box?: number; className?: string }) {
  return (
    // Corps ancré en bas à gauche, place réservée à droite pour la pancarte (sprite le plus large, 87 px) :
    // le corps ne bouge pas d'un pixel d'une pose à l'autre et rien ne sort de l'écran.
    <span className={`inline-flex shrink-0 items-end justify-start ${className}`} style={{ height: box ?? Math.round(72 * scale), width: Math.round(88 * scale) }}>
      <img
        src={slimeSrc(state)}
        alt={`Slime ${POSE_LABEL[state.pose]}, ${RISK_LABEL[state.risk]}`}
        title={`Slime ${POSE_LABEL[state.pose]} · ${RISK_LABEL[state.risk]}`}
        draggable={false}
        className={`slime-sprite block select-none ${state.pose === "sleepy" ? "slime-breathe" : ""}`}
        style={{ zoom: scale }}
      />
    </span>
  );
}

/**
 * État du Slime du Copilot en temps réel : couleur du risque actif x pose d'activité.
 * Priorité des poses : thinking (appel en cours) > happy (4 s après une réponse) > sleepy (2 min sans interaction)
 * > announce (ouverture / message d'accueil, ou conseil affiché dans la bulle) > idle.
 */
export function useCopilotSlime(open: boolean, advising: boolean): SlimeState {
  const { chat, chatBusy, loading } = useStore();
  const risk = useSlimeRisk();
  const [happy, setHappy] = useState(false);
  const [sleepy, setSleepy] = useState(false);
  const [greeting, setGreeting] = useState(false);
  const [pondering, setPondering] = useState(false);
  const lastLen = useRef(chat.length);
  const lastActivity = useRef(Date.now());
  const thinkingUntil = useRef(0);
  const ponderTimer = useRef<number>();

  const busy = chatBusy || loading;
  useEffect(() => {
    if (!busy) return;                       // pas de nettoyage au passage busy -> false : le minimum doit courir
    thinkingUntil.current = Date.now() + MIN_THINKING_MS;
    setPondering(true);
    window.clearTimeout(ponderTimer.current);
    ponderTimer.current = window.setTimeout(() => setPondering(false), MIN_THINKING_MS);
  }, [busy]);
  useEffect(() => () => window.clearTimeout(ponderTimer.current), []);

  // Réponse générée avec succès : joie pendant 4 s, une fois l'ampoule éteinte, puis retour au repos.
  useEffect(() => {
    const grew = chat.length > lastLen.current;
    lastLen.current = chat.length;
    const last = chat[chat.length - 1];
    if (!grew || !last || last.role !== "assistant" || last.error) return;
    const wait = Math.max(0, thinkingUntil.current - Date.now());
    const start = window.setTimeout(() => setHappy(true), wait);
    const stop = window.setTimeout(() => setHappy(false), wait + HAPPY_MS);
    return () => {
      window.clearTimeout(start);
      window.clearTimeout(stop);
    };
  }, [chat]);

  // Ouverture du Copilot : pancarte tant que le message d'accueil est seul, au plus 6 s.
  useEffect(() => {
    if (!open) {
      setGreeting(false);
      return;
    }
    lastActivity.current = Date.now();       // ouvrir le Copilot le réveille, quel que soit le moyen (souris, clavier)
    setSleepy(false);
    setGreeting(true);
    const t = window.setTimeout(() => setGreeting(false), 6000);
    return () => window.clearTimeout(t);
  }, [open]);

  // Veille : plus de 2 min sans interaction (souris, clavier, molette, toucher) ; toute interaction le réveille.
  useEffect(() => {
    const wake = () => {
      lastActivity.current = Date.now();
      setSleepy((s) => (s ? false : s));
    };
    const events = ["pointermove", "pointerdown", "keydown", "wheel", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, wake, { passive: true }));
    const timer = window.setInterval(() => {
      if (Date.now() - lastActivity.current >= SLEEP_AFTER_MS) setSleepy(true);
    }, 5000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, wake));
      window.clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    lastActivity.current = Date.now();       // envoyer un message ou lancer une analyse compte comme interaction
    setSleepy(false);
  }, [chat.length, loading]);

  const pose: SlimePose = busy || pondering ? "thinking"
    : happy ? "happy"
      : sleepy ? "sleepy"
        : (greeting && chat.length === 0) || advising ? "announce"
          : "idle";
  return { risk, pose };
}
