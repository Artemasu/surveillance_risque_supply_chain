// Page vitrine : ce que fait A.E.G.I.S., sans accès aux données.
// Trame : bandeau nuit avec le globe 3D, grands mots-clés, étapes, démonstration, profils,
// fonctionnalités, confidentialité, appel à l'action. Aplats de la charte. Deux polices seulement, celles du
// titre : sans-serif gras, et l'italique à empattements pour les mots forts, en bleu canard, moutarde ou olive.
// Mouvement sobre : apparitions douces, un fil d'approvisionnement qui se colore au défilement (FilSupplyChain) ;
// tout s'arrête si le système demande moins d'animations (MotionConfig reducedMotion="user" et CSS).
// Les couleurs de fond sont écrites en valeurs directes (bg-[#...]) : la page reste correcte même si la
// configuration Tailwind n'a pas encore été rechargée.
import { MotionConfig, motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "framer-motion";
import {
  ArrowDown, ArrowRight, ArrowUpRight, Banknote, Bell, Briefcase, CloudSun, Cpu, EyeOff, Factory, History, LayoutDashboard,
  Lock, MessageSquareText, Network, Radar, Route, ShieldCheck, type LucideIcon,
} from "lucide-react";
import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { AgentBadge } from "../ui";
import type { AgentName } from "../../types";
import DemoDefilante from "./DemoDefilante";
import FilSupplyChain from "./FilSupplyChain";
import Intro, { introAJouer } from "./Intro";
import PublicShell, { aller } from "./PublicShell";

const Globe = lazy(() => import("./Globe"));       // three.js chargé à part : le texte s'affiche tout de suite

const C = { nuit: "#061417", creme: "#F4F1EA", canard: "#017F8D", canardFonce: "#01545D", olive: "#A2B153", moutarde: "#ECB920", encre: "#0F172A" };
const DISPLAY: CSSProperties = { fontFamily: '"Space Grotesk", "Plus Jakarta Sans", system-ui, sans-serif' };
const ITALIQUE: CSSProperties = { fontFamily: '"Instrument Serif", Georgia, "Times New Roman", serif', fontStyle: "italic", fontWeight: 400, letterSpacing: "-0.01em" };

/** Mot en italique à empattements, pour casser le rythme des titres. */
const It = ({ children, color }: { children: ReactNode; color?: string }) => <span style={{ ...ITALIQUE, color }}>{children}</span>;

const apparition = { initial: { opacity: 0, y: 14 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: "-60px" }, transition: { duration: 0.5, ease: "easeOut" } };

const MOTS: { mot: string; texte: string; couleur: string }[] = [
  { mot: "Détecter", texte: "Presse, météo et marchés, surveillés autour de chaque maillon de votre chaîne.", couleur: C.moutarde },
  { mot: "Comprendre", texte: "Le graphe relie l'incident lointain aux usines et aux produits qu'il menace.", couleur: C.olive },
  { mot: "Anticiper", texte: "Alertes expliquées, sources citées et simulation avant la rupture.", couleur: C.canard },
];

const ETAPES: { titre: string; texte: string; icon: LucideIcon }[] = [
  { titre: "Décrivez votre chaîne", texte: "Sites, fournisseurs clés, ports et produits finis. Une dizaine de minutes, sans intégration informatique.", icon: Factory },
  { titre: "Trois agents surveillent", texte: "Presse internationale, météo et crues, cours des matières et du fret, autour de chaque maillon.", icon: Radar },
  { titre: "Le risque se propage", texte: "Un incident chez un fournisseur de rang 2 remonte jusqu'aux usines et aux produits qui en dépendent.", icon: Network },
  { titre: "Vous agissez à temps", texte: "Alertes priorisées, sources citées, simulation de pannes et solutions de repli.", icon: Bell },
];

// Scénario de démonstration FICTIF (data/replay_scenarios/crisis_pharma_api.json).
const DEMO: { jour: number; texte: string; agents: AgentName[]; maillon: string }[] = [
  { jour: 1, texte: "La Chine soumet à licence l'exportation d'intermédiaires d'antibiotiques ; forte pluie prévue à Hyderabad.", agents: ["media", "weather"], maillon: "Fournisseurs de principe actif" },
  { jour: 2, texte: "La presse annonce un risque d'inondation à Hyderabad ; la prévision s'aggrave.", agents: ["media", "weather"], maillon: "Fournisseur indien" },
  { jour: 3, texte: "Inondations : le fournisseur indien de principe actif arrête sa production.", agents: ["media", "weather"], maillon: "Fournisseur indien" },
  { jour: 4, texte: "Cyberattaque au port d'Anvers : la route d'arrivée du principe actif est bloquée à son tour.", agents: ["media"], maillon: "Port d'Anvers" },
  { jour: 5, texte: "Le prix des principes actifs et le fret Inde-Europe s'envolent.", agents: ["finance"], maillon: "Marchés" },
  { jour: 6, texte: "L'usine de Tours réduit sa production d'antibiotique injectable.", agents: ["media"], maillon: "Usine de Tours" },
];

const PROFILS: { titre: string; texte: string; icon: LucideIcon }[] = [
  { titre: "Supply chain et logistique", texte: "Les sites, ports et routes menacés, avec le stock restant avant rupture.", icon: Route },
  { titre: "Achats", texte: "Les fournisseurs exposés, leurs signaux financiers et les sources de repli.", icon: Briefcase },
  { titre: "Direction et gestion des risques", texte: "Un indice global, son historique et les produits finis en jeu.", icon: LayoutDashboard },
];

const FONCTIONS: { titre: string; texte: string; icon: LucideIcon; couleur: string }[] = [
  { titre: "Tour de contrôle", texte: "Indice de risque global, alertes priorisées et carte des sites.", icon: LayoutDashboard, couleur: C.canard },
  { titre: "Chaîne et simulation", texte: "Graphe de la chaîne et simulation de pannes : que se passe-t-il si ce port ferme ?", icon: Network, couleur: C.olive },
  { titre: "Météo", texte: "Seuils propres à chaque site, crues, tempêtes, prévisions à 16 jours.", icon: CloudSun, couleur: C.moutarde },
  { titre: "Marchés et fournisseurs", texte: "Matières premières, fret, énergie, santé financière des fournisseurs.", icon: Banknote, couleur: C.canard },
  { titre: "Historique et replay", texte: "Chaque analyse est conservée : on retrouve ce que l'on savait à chaque date.", icon: History, couleur: C.olive },
  { titre: "Copilote", texte: "Posez vos questions en français ; chaque réponse cite ses sources.", icon: MessageSquareText, couleur: C.moutarde },
];

const CONFIANCE: { titre: string; texte: string; icon: LucideIcon }[] = [
  { titre: "Chaque client chez soi", texte: "Un compte ne voit que sa propre chaîne d'approvisionnement.", icon: Lock },
  { titre: "Fournisseurs pseudonymisés", texte: "Par défaut, leurs noms ne sont pas conservés.", icon: EyeOff },
  { titre: "Intelligence artificielle locale", texte: "Les analyses tournent sur nos serveurs, sans service tiers.", icon: Cpu },
  { titre: "Conforme au RGPD", texte: "Données minimales, export et suppression à tout moment.", icon: ShieldCheck },
];

function Titre({ sur, children, clair = false }: { sur: string; children: ReactNode; clair?: boolean }) {
  return (
    <div>
      <p className={`text-xs font-semibold uppercase tracking-[0.22em] ${clair ? "text-white/60" : "text-[#0F172A]/50"}`}>
        {sur}
      </p>
      <h2 className={`mt-4 text-4xl font-bold leading-[1.02] tracking-tight sm:text-6xl ${clair ? "text-white" : "text-[#0F172A]"}`} style={DISPLAY}>{children}</h2>
    </div>
  );
}

/** Vrai sur un grand écran (≥ 1024 px) : la démonstration défilante y remplace la frise verticale. */
function useGrandEcran(requete = "(min-width: 1024px)") {
  const [grand, setGrand] = useState(() => typeof window !== "undefined" && window.matchMedia(requete).matches);
  useEffect(() => {
    const mq = window.matchMedia(requete);
    const maj = () => setGrand(mq.matches);
    mq.addEventListener("change", maj);
    return () => mq.removeEventListener("change", maj);
  }, [requete]);
  return grand;
}

const CLASSE_FONCTION = "rounded-[24px] border border-[#E2E8F0] bg-white p-7";

function ContenuFonction({ f }: { f: (typeof FONCTIONS)[number] }) {
  return (
    <>
      <span className="grid h-12 w-12 place-items-center rounded-2xl" style={{ background: `${f.couleur}22`, color: f.couleur === C.moutarde ? "#9C7700" : f.couleur }}><f.icon size={21} /></span>
      <h3 className="mt-5 text-lg font-bold text-[#0F172A]">{f.titre}</h3>
      <p className="mt-1.5 leading-relaxed text-[#475569]">{f.texte}</p>
    </>
  );
}

/** Carte de fonctionnalité qui sort du fil d'approvisionnement (grand écran) : la rangée du haut glisse
 *  de la ligne vers le haut, celle du bas de la ligne vers le bas. Les cartes vont par paires (même colonne)
 *  et les trois paires sortent l'une après l'autre au fil du défilement. */
function CarteSortante({ f, i, progression }: { f: (typeof FONCTIONS)[number]; i: number; progression: MotionValue<number> }) {
  const paire = i % 3, enHaut = i < 3;
  // fenêtres de défilement : 0-0,3 · 0,27-0,57 · 0,54-0,84, puis tout reste affiché jusqu'à la fin du blocage
  const debut = paire * 0.27;
  const reste = useTransform(progression, [debut, debut + 0.3], [1, 0], { clamp: true });   // 1 = encore dans la ligne
  // la carte part de la ligne (décalée de toute sa hauteur) et la partie encore « dans » la ligne est masquée
  const y = useTransform(reste, (r) => `${(enHaut ? r : -r) * 100}%`);
  const clipPath = useTransform(reste, (r) => (enHaut ? `inset(0 0 ${r * 100}% 0 round 24px)` : `inset(${r * 100}% 0 0 0 round 24px)`));
  return (
    <motion.div style={{ y, clipPath }} className={CLASSE_FONCTION}>
      <ContenuFonction f={f} />
    </motion.div>
  );
}

/** Ligne du fil qui reste à l'écran avec les cartes pendant que la section est figée. Elle reprend exactement
 *  le tracé de FilSupplyChain à cet endroit (mêmes bords gauche / droite, mêmes virages arrondis) : elle
 *  descend de la marge gauche, traverse entre les deux rangées et repart vers le bas à droite. Ses bouts
 *  verticaux vont jusqu'aux bords de la zone figée et recouvrent le fil, donc rien ne dépasse ni ne se
 *  dédouble au moment où la section se libère. */
const RAYON_FIL = 36;
function LigneFigee({ grille }: { grille: RefObject<HTMLDivElement> }) {
  const [geo, setGeo] = useState<{ x: number; haut: number; l: number; h: number; y: number } | null>(null);
  useLayoutEffect(() => {
    const g = grille.current, boite = g?.parentElement, zone = boite?.parentElement, section = boite?.closest("section");
    if (!g || !boite || !zone || !section) return;
    const mesurer = () => {
      const rb = boite.getBoundingClientRect(), rs = section.getBoundingClientRect(), rz = zone.getBoundingClientRect();
      const cartes = Array.from(g.children) as HTMLElement[];
      if (cartes.length < 4) return;
      const L = rs.width, dx = rb.left - rs.left, gx = g.offsetLeft + dx;
      const gauche = Math.max(10, gx - Math.min(48, gx / 2));
      const droite = Math.min(L - 10, gx + g.offsetWidth + Math.min(48, (L - gx - g.offsetWidth) / 2));
      // les cartes ont pour parent de positionnement le conteneur (comme la ligne) : entre les deux rangées
      const c0 = cartes[0], c3 = cartes[3];
      const y = (c0.offsetTop + c0.offsetHeight + c3.offsetTop) / 2;
      const haut = rz.top - rb.top;                                  // haut de la zone figée, relatif au conteneur
      setGeo({ x: gauche - dx, haut, l: droite - gauche, h: rz.height, y: y - haut });
    };
    mesurer();
    const obs = new ResizeObserver(mesurer);
    obs.observe(section);
    return () => obs.disconnect();
  }, [grille]);
  if (!geo) return null;
  const { l, h, y } = geo, r = RAYON_FIL;
  const d = `M0,0 L0,${y - r} Q0,${y} ${r},${y} L${l - r},${y} Q${l},${y} ${l},${y + r} L${l},${h}`;
  return (
    <svg aria-hidden className="pointer-events-none absolute overflow-visible" style={{ left: geo.x, top: geo.haut, width: l, height: h }}>
      <defs>
        <filter id="ligne-figee-halo" x="-50%" y="-200%" width="200%" height="500%">
          <feGaussianBlur stdDeviation="2.2" result="flou" />
          <feMerge><feMergeNode in="flou" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <path d={d} fill="none" stroke={C.canard} strokeWidth={2} />
      <g filter="url(#ligne-figee-halo)">
        {[C.moutarde, C.olive, C.canard].map((c, k) => (
          <motion.circle key={k} cy={y} r={3.2} fill={c}
            initial={{ cx: r }} animate={{ cx: l - r }}
            transition={{ duration: (l - 2 * r) / 110, ease: "linear", repeat: Infinity, delay: (k * (l - 2 * r)) / 110 / 3 }} />
        ))}
      </g>
    </svg>
  );
}

export default function Landing() {
  const reduit = useReducedMotion();
  const defilante = useGrandEcran() && !reduit;
  // Fonctionnalités figées (comme la démonstration) : la section reste à l'écran et le défilement sert à faire
  // sortir les cartes du fil ; la page reprend quand les six sont affichées. Écran assez haut seulement.
  const figee = useGrandEcran("(min-width: 1024px) and (min-height: 760px)") && !reduit;
  const sectionFonctions = useRef<HTMLElement>(null);
  const grilleFonctions = useRef<HTMLDivElement>(null);
  const { scrollYProgress: sortieFonctions } = useScroll({ target: sectionFonctions, offset: ["start 64px", "end end"] });
  // Intro (première visite de l'onglet) : écran noir, globe et chaîne qui s'allument, logo, puis glissement en place
  const [intro, setIntro] = useState(introAJouer);
  const [introSortie, setIntroSortie] = useState(false);
  const [globePret, setGlobePret] = useState(false);
  const horlogeIntro = useRef(0);
  const introJouee = useRef(intro);
  const boiteGlobe = useRef<HTMLDivElement>(null);
  const texteVisible = !intro || introSortie;
  return (
    <MotionConfig reducedMotion="user">
      <PublicShell sombre>
        {intro && <Intro globe={boiteGlobe} horloge={horlogeIntro} globePret={globePret} onSortie={() => setIntroSortie(true)} onFin={() => setIntro(false)} />}
        {/* Bandeau : nuit, globe 3D, grand titre */}
        <section className="relative overflow-hidden text-white" style={{ background: C.nuit }}>
          <div className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(ellipse at 72% 50%, rgba(1,127,141,0.35), transparent 55%), radial-gradient(ellipse at 10% 100%, rgba(236,185,32,0.10), transparent 45%)" }} />
          <div ref={boiteGlobe} className="pointer-events-none absolute -right-48 top-1/2 h-[620px] w-[620px] -translate-y-1/2 opacity-50 sm:-right-24 lg:-right-10 lg:h-[760px] lg:w-[760px] lg:opacity-100">
            <Suspense fallback={null}>
              <Globe className="h-full w-full" intro={introJouee.current ? horlogeIntro : undefined} onPret={() => setGlobePret(true)} />
            </Suspense>
          </div>
          <div className="relative mx-auto flex min-h-[min(92vh,860px)] max-w-6xl flex-col justify-center px-4 pb-20 pt-12 sm:px-6">
            <motion.div initial={{ opacity: 0, y: 16 }} animate={texteVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
              transition={{ duration: 0.9, delay: intro ? 0.5 : 0, ease: [0.22, 1, 0.36, 1] }} className="max-w-2xl">
              <p className="inline-flex items-center gap-3 rounded-full border border-white/15 bg-white/5 px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.22em] text-white/75 backdrop-blur">
                <span className="flex gap-1.5">{[C.moutarde, C.olive, "#5FC4CF"].map((c) => <span key={c} className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />)}</span>
                Médias · Météo · Marchés
              </p>
              <h1 className="mt-7 text-[3.25rem] font-bold leading-[0.95] tracking-[-0.03em] sm:text-7xl lg:text-[4.6rem]" style={DISPLAY}>
                Vos fournisseurs sont <It color={C.moutarde}>ailleurs.</It>
                <span className="mt-2 block text-white/45">Leurs risques,</span>
                <span className="block"><It color="#FFFFFF">sous vos yeux.</It></span>
              </h1>
              <p className="mt-7 max-w-lg text-base leading-relaxed text-white/70 sm:text-lg">
                A.E.G.I.S. surveille l'actualité, la météo et les marchés autour de chaque maillon de votre chaîne d'approvisionnement, et vous alerte avant que la rupture n'atteigne vos produits.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-3">
                <button className="group inline-flex items-center gap-2 rounded-full px-6 py-3.5 text-sm font-bold text-[#0F172A] shadow-[0_8px_30px_rgba(236,185,32,0.35)] transition hover:-translate-y-0.5" style={{ background: C.moutarde }} onClick={() => aller("#/inscription")}>
                  Créer un espace <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
                </button>
                <a href="#demonstration" className="inline-flex items-center gap-2 rounded-full border border-white/20 px-6 py-3.5 text-sm font-semibold text-white transition hover:bg-white/10">
                  Voir un exemple <ArrowUpRight size={16} />
                </a>
              </div>
              <div className="mt-12 flex flex-wrap gap-x-6 gap-y-2 text-xs text-white/55">
                <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-white" /> Sites et usines</span>
                <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-[#FB923C] shadow-[0_0_10px_#FB923C]" /> Fournisseur touché</span>
                <span className="flex items-center gap-2">
                  {[C.moutarde, C.olive, "#5FC4CF"].map((c) => <span key={c} className="h-2 w-2 rounded-full" style={{ background: c, boxShadow: `0 0 8px ${c}` }} />)}
                  Signaux en route
                </span>
              </div>
            </motion.div>
          </div>
          <a href="#mots" className="absolute bottom-7 left-1/2 hidden -translate-x-1/2 flex-col items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.25em] text-white/40 hover:text-white/80 sm:flex" aria-label="Descendre">
            Découvrir <ArrowDown size={16} />
          </a>
        </section>

        {/* Mots-clés et étapes, reliés par le fil d'approvisionnement */}
        <FilSupplyChain>
        {/* Grands mots-clés */}
        <section id="mots" style={{ background: C.creme }}>
          <div className="relative mx-auto max-w-6xl px-4 py-24 sm:px-6">
            <p data-fil="phrase" className="max-w-3xl text-3xl font-medium leading-snug tracking-tight text-[#0F172A] sm:text-5xl" style={DISPLAY}>
              Une rupture ne commence jamais chez vous. Elle commence <It color={C.canard}>à l'autre bout du monde</It>, dans un article, une prévision, un cours qui décroche.
            </p>
            <div data-fil="mots" className="mt-20 grid gap-12 md:grid-cols-3">
              {MOTS.map((m, i) => (
                <motion.div key={m.mot} data-fil-mot {...apparition} transition={{ duration: 0.5, delay: i * 0.08 }} className="border-t-2 pt-6" style={{ borderColor: m.couleur }}>
                  <span className="text-sm font-bold text-[#0F172A]/40">0{i + 1}</span>
                  <h3 className="mt-2 text-4xl font-bold tracking-tight text-[#0F172A] lg:text-5xl" style={DISPLAY}>{m.mot}</h3>
                  <p className="mt-3 max-w-xs leading-relaxed text-[#475569]">{m.texte}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* Étapes */}
        <section id="fonctionnement" className="scroll-mt-20 bg-white">
          <div className="relative mx-auto max-w-6xl px-4 py-28 sm:px-6">
            <Titre sur="Fonctionnement">De votre chaîne <It color={C.canard}>à l'alerte</It>,<br className="hidden sm:block" /> en quatre étapes.</Titre>
            <ol data-fil="etapes" className="mt-16 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
              {ETAPES.map((e, i) => (
                <motion.li key={e.titre} {...apparition} transition={{ duration: 0.5, delay: i * 0.06 }}
                  className="group relative flex flex-col overflow-hidden rounded-[28px] border border-[#E2E8F0] bg-white p-7 transition duration-300 hover:-translate-y-1 hover:border-transparent hover:shadow-[0_20px_50px_rgba(1,84,93,0.12)]">
                  <span className="text-6xl font-bold leading-none" style={{ ...DISPLAY, color: i % 2 ? C.olive : C.canard }}>{String(i + 1).padStart(2, "0")}</span>
                  <span data-fil-icone className="mt-8 grid h-11 w-11 place-items-center rounded-full text-white" style={{ background: i % 2 ? C.olive : C.canard }}><e.icon size={18} /></span>
                  <h3 className="mt-5 text-lg font-bold text-[#0F172A]">{e.titre}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-[#475569]">{e.texte}</p>
                </motion.li>
              ))}
            </ol>
          </div>
        </section>

        </FilSupplyChain>

        {/* Démonstration : fiches défilantes sur grand écran, frise verticale sinon */}
        {defilante ? <DemoDefilante jours={DEMO} fond={C.canardFonce} /> : (
        <section id="demonstration" className="relative scroll-mt-20 overflow-hidden text-white" style={{ background: C.canardFonce }}>
          <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full opacity-30 blur-3xl" style={{ background: C.canard }} />
          <div className="relative mx-auto max-w-6xl px-4 py-28 sm:px-6">
            <div className="grid gap-8 lg:grid-cols-2 lg:items-end">
              <Titre sur="Démonstration" clair>Une crise <It color={C.moutarde}>en cascade</It>, jour après jour.</Titre>
              <p className="text-lg leading-relaxed text-white/75">
                Un laboratoire fabrique un antibiotique injectable à Tours. Ses principes actifs viennent d'Inde et de Chine et arrivent par Anvers. Voici ce que voient les trois agents.
              </p>
            </div>
            {/* Frise : une ligne par jour, lecture de haut en bas, sans cartes */}
            <ol className="relative mt-16 border-b border-white/15">
              {DEMO.map((d, i) => (
                <motion.li key={d.jour} {...apparition} transition={{ duration: 0.45, delay: Math.min(i, 3) * 0.05 }}
                  className="group grid gap-4 border-t border-white/15 py-7 transition-colors duration-300 hover:bg-white/[0.04] sm:grid-cols-[120px_1fr] lg:grid-cols-[140px_1fr_260px] lg:items-center">
                  <div className="flex items-center gap-4">
                    <span className="text-5xl font-bold leading-none" style={{ ...DISPLAY, color: { media: C.moutarde, weather: C.olive, finance: "#5FC4CF" }[d.agents[0]] }}>J{d.jour}</span>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/55">{d.maillon}</p>
                    <p className="mt-2 text-lg leading-relaxed text-white">{d.texte}</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5 lg:justify-end">{d.agents.map((a) => <AgentBadge key={a} agent={a} />)}</div>
                </motion.li>
              ))}
            </ol>
            <p className="mt-10 max-w-3xl text-lg leading-relaxed text-white/85">
              Chaque signal est rattaché au bon maillon : le fournisseur de Hyderabad, le port d'Anvers, puis l'usine de Tours qu'ils approvisionnent. Le risque se propage dans le graphe <It color={C.moutarde}>jusqu'au produit fini</It>, avec les sources de chaque alerte.
            </p>
            <p className="mt-3 text-xs text-white/45">Scénario fictif écrit pour la démonstration : ni les articles, ni les mesures, ni les entreprises ne sont réels.</p>
          </div>
        </section>
        )}

        {/* Profils, fonctionnalités, confidentialité et appel à l'action, reliés par la suite du fil */}
        <FilSupplyChain parcours="bas">
        {/* Profils */}
        <section style={{ background: C.creme }}>
          <div className="relative mx-auto grid max-w-6xl gap-14 px-4 py-28 sm:px-6 lg:grid-cols-[0.9fr_1.1fr]">
            <Titre sur="Pour qui">Une lecture <It color={C.olive}>pour chaque</It> métier.</Titre>
            {/* séparateurs raccourcis : ils commencent après les pastilles, pour ne pas croiser le fil qui les relie */}
            <div data-fil="profils">
              {PROFILS.map((p, i) => (
                <motion.div key={p.titre} {...apparition} className="group relative flex items-center gap-5 py-7">
                  {i === 0 && <span aria-hidden className="absolute left-[68px] right-0 top-0 h-px bg-[#0F172A]/10" />}
                  <span aria-hidden className="absolute bottom-0 left-[68px] right-0 h-px bg-[#0F172A]/10" />
                  <span data-fil-station className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-[#0F172A] text-white transition group-hover:bg-[#017F8D]"><p.icon size={19} /></span>
                  <div>
                    <h3 className="text-xl font-bold text-[#0F172A]" style={DISPLAY}>{p.titre}</h3>
                    <p className="text-[#475569]">{p.texte}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* Fonctionnalités */}
        {/* Grand écran : section figée le temps que les cartes sortent du fil par paires (haut / bas), sur environ
            1,6 écran de défilement ; ailleurs, simple apparition */}
        <section id="fonctionnalites" ref={sectionFonctions} data-fil={figee ? "fonctions-figee" : undefined}
          className={`scroll-mt-20 bg-white ${figee ? "h-[calc(260vh-4rem)]" : ""}`}>
          <div className={figee ? "sticky top-16 flex h-[calc(100vh-4rem)] items-center" : ""}>
          <div className={`relative mx-auto w-full max-w-6xl px-4 sm:px-6 ${figee ? "py-6" : "py-28"}`}>
            <Titre sur="Fonctionnalités">Tout ce qu'il faut <It color={C.canard}>pour voir venir.</It></Titre>
            {figee && <LigneFigee grille={grilleFonctions} />}
            <div ref={grilleFonctions} data-fil="fonctions" className={`${figee ? "mt-10" : "mt-14"} grid gap-5 sm:grid-cols-2 lg:grid-cols-3`}>
              {FONCTIONS.map((f, i) => figee ? (
                <CarteSortante key={f.titre} f={f} i={i} progression={sortieFonctions} />
              ) : (
                <motion.div key={f.titre} {...apparition} transition={{ duration: 0.45, delay: (i % 3) * 0.06 }}
                  className={`${CLASSE_FONCTION} transition duration-300 hover:-translate-y-1 hover:shadow-[0_20px_50px_rgba(15,23,42,0.08)]`}>
                  <ContenuFonction f={f} />
                </motion.div>
              ))}
            </div>
            <div className={`${figee ? "mt-6" : "mt-8"} flex flex-wrap gap-2`}><AgentBadge agent="media" /><AgentBadge agent="weather" /><AgentBadge agent="finance" /></div>
          </div>
          </div>
        </section>

        {/* Confidentialité : aplat vert olive */}
        <section id="confidentialite" className="scroll-mt-20" style={{ background: C.olive }}>
          <div className="relative mx-auto max-w-6xl px-4 py-28 sm:px-6">
            <Titre sur="Confidentialité">Votre chaîne reste <It>la vôtre.</It></Titre>
            <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {CONFIANCE.map((c) => (
                <motion.div key={c.titre} {...apparition} className="rounded-[24px] bg-[#F4F1EA]/60 p-6 ring-1 ring-[#0F172A]/5 backdrop-blur">
                  <c.icon size={20} className="text-[#0F172A]" />
                  <h3 className="mt-4 font-bold text-[#0F172A]">{c.titre}</h3>
                  <p className="mt-1 text-sm text-[#0F172A]/75">{c.texte}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* Appel à l'action : retour dans la nuit du globe ; le fil d'approvisionnement vient s'y brancher */}
        {/* section non positionnée (fond en dégradés CSS) : le fil, dessiné dessous, reste visible par-dessus son fond */}
        <section className="text-white" style={{ background: `radial-gradient(ellipse at 75% 50%, rgba(1,127,141,0.32), transparent 55%), radial-gradient(ellipse at 0% 0%, rgba(162,177,83,0.10), transparent 40%), ${C.nuit}` }}>
          <div className="relative mx-auto grid max-w-6xl items-center gap-6 px-4 py-24 sm:px-6 lg:grid-cols-[1.1fr_1fr] lg:py-28">
            <motion.div {...apparition}>
              <h2 className="text-5xl font-bold leading-[0.95] tracking-tight sm:text-7xl" style={DISPLAY}>
                Une chaîne <span className="block"><It color={C.moutarde}>à surveiller ?</It></span>
              </h2>
              <p className="mt-6 max-w-lg text-lg leading-relaxed text-white/70">
                Créez votre espace en quelques minutes. Vous pourrez exporter ou supprimer vos données à tout moment.
              </p>
              <div className="mt-9 flex flex-wrap gap-3">
                <button className="group inline-flex items-center gap-2 rounded-full px-6 py-3.5 text-sm font-bold text-[#0F172A] shadow-[0_8px_30px_rgba(236,185,32,0.35)] transition hover:-translate-y-0.5" style={{ background: C.moutarde }} onClick={() => aller("#/inscription")}>
                  Créer un espace <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
                </button>
                <button className="rounded-full border border-white/20 px-6 py-3.5 text-sm font-semibold text-white transition hover:bg-white/10" onClick={() => aller("#/connexion")}>J'ai déjà un compte</button>
              </div>
            </motion.div>
            {/* le globe revient : le fil s'y branche (data-fil="arrivee", sur le bord droit de la Terre) */}
            <motion.div initial={{ opacity: 0, scale: 0.85 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
              data-fil="arrivee" data-fil-arrivee-x="0.86" className="pointer-events-none relative mx-auto aspect-square w-full max-w-[520px]">
              <Suspense fallback={null}><Globe className="h-full w-full" /></Suspense>
            </motion.div>
          </div>
        </section>
        </FilSupplyChain>
      </PublicShell>
    </MotionConfig>
  );
}
