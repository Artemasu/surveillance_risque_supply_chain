// Démonstration « au défilement » (inspirée de truus.co) : la section reste fixée à l'écran pendant que l'on fait
// défiler la page vers le bas ; les fiches des six jours glissent alors de droite à gauche, une par une, et les
// mots de chaque fiche se posent en tombant légèrement quand elle arrive au centre.
// Réservée aux grands écrans sans « réduire les animations » : ailleurs, Landing affiche la frise verticale.
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import type { AgentName } from "../../types";
import { AgentBadge } from "../ui";

export interface JourDemo {
  jour: number;
  texte: string;
  agents: AgentName[];
  maillon: string;
}

const DISPLAY: CSSProperties = { fontFamily: '"Space Grotesk", "Plus Jakarta Sans", system-ui, sans-serif' };
const ITALIQUE: CSSProperties = { fontFamily: '"Instrument Serif", Georgia, "Times New Roman", serif', fontStyle: "italic", fontWeight: 400 };
// Fond de chaque fiche, à tour de rôle ; texte noir sur moutarde et olive, noir sur crème.
const FONDS = ["#ECB920", "#A2B153", "#F4F1EA"];
const ANGLES = [-14, 9, -6, 12, -10, 7, -4, 11];   // inclinaison de départ des mots, fixe (pas d'aléatoire)

/** Un mot qui tombe et se redresse quand la fiche approche du centre. */
function Mot({ texte, k, arrivee }: { texte: string; k: number; arrivee: MotionValue<number> }) {
  const rotate = useTransform(arrivee, [0, 1], [ANGLES[k % ANGLES.length], 0]);
  const y = useTransform(arrivee, [0, 1], [26 + (k % 3) * 10, 0]);
  const opacity = useTransform(arrivee, [0, 0.6], [0, 1]);
  return <motion.span className="inline-block whitespace-pre" style={{ rotate, y, opacity }}>{texte} </motion.span>;
}

function Fiche({ d, i, n, progression }: { d: JourDemo; i: number; n: number; progression: MotionValue<number> }) {
  // la fiche i passe au centre vers la fraction (i + 1) / (n + 1) du défilement de la section
  const centre = (i + 1) / (n + 1);
  const arrivee = useTransform(progression, [centre - 0.14, centre - 0.03], [0, 1], { clamp: true });
  const echelle = useTransform(progression, [centre - 0.16, centre, centre + 0.16], [0.92, 1, 0.92]);
  const fond = FONDS[i % FONDS.length];
  return (
    <motion.article style={{ scale: echelle, background: fond }}
      className="flex h-[min(62vh,520px)] w-[min(560px,70vw)] shrink-0 flex-col justify-between rounded-[32px] p-9 text-[#0F172A] shadow-[0_30px_80px_rgba(0,0,0,0.25)]">
      <div className="flex items-start justify-between gap-4">
        <span className="text-[7rem] font-bold leading-[0.8] tracking-tight" style={DISPLAY}>
          J{d.jour}
        </span>
        <span className="rounded-full bg-[#0F172A] px-3 py-1.5 text-xs font-semibold text-white">{d.maillon}</span>
      </div>
      <p className="text-2xl font-medium leading-snug xl:text-[1.7rem]" style={DISPLAY}>
        {d.texte.split(" ").map((m, k) => <Mot key={k} texte={m} k={k + i} arrivee={arrivee} />)}
      </p>
      <div className="flex flex-wrap gap-2">{d.agents.map((a) => <AgentBadge key={a} agent={a} />)}</div>
    </motion.article>
  );
}

export default function DemoDefilante({ jours, fond }: { jours: JourDemo[]; fond: string }) {
  const section = useRef<HTMLElement>(null);
  const piste = useRef<HTMLDivElement>(null);
  const [distance, setDistance] = useState(0);
  const { scrollYProgress } = useScroll({ target: section, offset: ["start start", "end end"] });
  const x = useTransform(scrollYProgress, [0, 1], [0, -distance]);
  const barre = useTransform(scrollYProgress, [0, 1], ["0%", "100%"]);

  useLayoutEffect(() => {
    // la piste prend la largeur de son contenu (w-max) : on la fait glisser de (largeur - écran)
    const el = piste.current;
    if (!el) return;
    const mesurer = () => setDistance(Math.max(0, el.offsetWidth - document.documentElement.clientWidth));
    mesurer();
    const obs = new ResizeObserver(mesurer);
    obs.observe(el);
    window.addEventListener("resize", mesurer);
    return () => { obs.disconnect(); window.removeEventListener("resize", mesurer); };
  }, []);

  return (
    // hauteur = longueur du défilement : environ un écran par fiche
    <section id="demonstration" ref={section} className="relative scroll-mt-20" style={{ height: `${(jours.length + 1) * 85}vh`, background: fond }}>
      <div className="sticky top-0 flex h-screen flex-col justify-center overflow-hidden">
        <motion.div ref={piste} style={{ x }} className="flex w-max items-center gap-8 pl-[max(1.5rem,calc((100vw-72rem)/2+1.5rem))]">
          {/* introduction, à gauche de la piste */}
          <div className="w-[min(460px,38vw)] shrink-0 text-white">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-white/60">Démonstration</p>
            <h2 className="mt-4 text-5xl font-bold leading-[1.02] tracking-tight xl:text-6xl" style={DISPLAY}>
              Une crise <span style={{ ...ITALIQUE, color: "#ECB920" }}>en cascade</span>, jour après jour.
            </h2>
            <p className="mt-6 text-lg leading-relaxed text-white/75">
              Un laboratoire fabrique un antibiotique injectable à Tours. Ses principes actifs viennent d'Inde et de Chine et arrivent par Anvers. Faites défiler : voici ce que voient les trois agents.
            </p>
          </div>
          {jours.map((d, i) => <Fiche key={d.jour} d={d} i={i} n={jours.length} progression={scrollYProgress} />)}
          {/* conclusion, au bout de la piste */}
          <div className="w-[min(460px,38vw)] shrink-0 text-white">
            <p className="text-2xl leading-relaxed text-white/90" style={DISPLAY}>
              Chaque signal est rattaché au bon maillon, et le risque se propage dans le graphe <span style={{ ...ITALIQUE, color: "#ECB920" }}>jusqu'au produit fini</span>, avec les sources de chaque alerte.
            </p>
            <p className="mt-4 text-xs text-white/45">Scénario fictif écrit pour la démonstration : ni les articles, ni les mesures, ni les entreprises ne sont réels.</p>
          </div>
          {/* marge de fin : la conclusion s'arrête avant le bord droit */}
          <div aria-hidden className="w-[12vw] shrink-0" />
        </motion.div>
        {/* avancement */}
        <div className="absolute bottom-10 left-1/2 h-1 w-48 -translate-x-1/2 overflow-hidden rounded-full bg-white/15">
          <motion.div className="h-full rounded-full bg-[#ECB920]" style={{ width: barre }} />
        </div>
      </div>
    </section>
  );
}
