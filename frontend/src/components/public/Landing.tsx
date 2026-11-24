// Page vitrine : ce que fait A.E.G.I.S., sans accès aux données.
// Trame : bandeau nuit avec le globe 3D, grands mots-clés, étapes, démonstration, profils,
// fonctionnalités, confidentialité, appel à l'action. Aplats de la charte. Deux polices seulement, celles du
// titre : sans-serif gras, et l'italique à empattements pour les mots forts, en bleu canard, moutarde ou olive.
// Mouvement sobre : apparitions douces, aucune animation liée au défilement de la page, rien qui clignote ;
// tout s'arrête si le système demande moins d'animations (MotionConfig reducedMotion="user" et CSS).
// Les couleurs de fond sont écrites en valeurs directes (bg-[#...]) : la page reste correcte même si la
// configuration Tailwind n'a pas encore été rechargée.
import { MotionConfig, motion } from "framer-motion";
import {
  ArrowDown, ArrowRight, ArrowUpRight, Banknote, Bell, Briefcase, CloudSun, Cpu, EyeOff, Factory, History, LayoutDashboard,
  Lock, MessageSquareText, Network, Radar, Route, ShieldCheck, type LucideIcon,
} from "lucide-react";
import { Suspense, lazy, type CSSProperties, type ReactNode } from "react";
import { AgentBadge } from "../ui";
import type { AgentName } from "../../types";
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

/** Badge circulaire qui tourne lentement. */
function Tampon() {
  return (
    <motion.svg viewBox="0 0 120 120" className="h-32 w-32 shrink-0" animate={{ rotate: 360 }} transition={{ duration: 40, repeat: Infinity, ease: "linear" }} aria-hidden>
      <defs><path id="cercle" d="M60,60 m-46,0 a46,46 0 1,1 92,0 a46,46 0 1,1 -92,0" /></defs>
      <text fontSize="10.5" fontWeight={600} letterSpacing="2.2" fill={C.encre}><textPath href="#cercle">DÉTECTER · COMPRENDRE · ANTICIPER · </textPath></text>
      <path d="M60 46 l4 10 10 4 -10 4 -4 10 -4 -10 -10 -4 10 -4z" fill={C.encre} />
    </motion.svg>
  );
}

export default function Landing() {
  return (
    <MotionConfig reducedMotion="user">
      <PublicShell sombre>
        {/* Bandeau : nuit, globe 3D, grand titre */}
        <section className="relative overflow-hidden text-white" style={{ background: C.nuit }}>
          <div className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(ellipse at 72% 50%, rgba(1,127,141,0.35), transparent 55%), radial-gradient(ellipse at 10% 100%, rgba(236,185,32,0.10), transparent 45%)" }} />
          <div className="pointer-events-none absolute -right-48 top-1/2 h-[620px] w-[620px] -translate-y-1/2 opacity-50 sm:-right-24 lg:-right-10 lg:h-[760px] lg:w-[760px] lg:opacity-100">
            <Suspense fallback={null}><Globe className="h-full w-full" /></Suspense>
          </div>
          <div className="relative mx-auto flex min-h-[min(92vh,860px)] max-w-6xl flex-col justify-center px-4 pb-20 pt-12 sm:px-6">
            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }} className="max-w-2xl">
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

        {/* Grands mots-clés */}
        <section id="mots" style={{ background: C.creme }}>
          <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
            <p className="max-w-3xl text-3xl font-medium leading-snug tracking-tight text-[#0F172A] sm:text-5xl" style={DISPLAY}>
              Une rupture ne commence jamais chez vous. Elle commence <It color={C.canard}>à l'autre bout du monde</It>, dans un article, une prévision, un cours qui décroche.
            </p>
            <div className="mt-20 grid gap-12 md:grid-cols-3">
              {MOTS.map((m, i) => (
                <motion.div key={m.mot} {...apparition} transition={{ duration: 0.5, delay: i * 0.08 }} className="border-t-2 pt-6" style={{ borderColor: m.couleur }}>
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
          <div className="mx-auto max-w-6xl px-4 py-28 sm:px-6">
            <Titre sur="Fonctionnement">De votre chaîne <It color={C.canard}>à l'alerte</It>,<br className="hidden sm:block" /> en quatre étapes.</Titre>
            <ol className="mt-16 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
              {ETAPES.map((e, i) => (
                <motion.li key={e.titre} {...apparition} transition={{ duration: 0.5, delay: i * 0.06 }}
                  className="group relative flex flex-col overflow-hidden rounded-[28px] border border-[#E2E8F0] bg-white p-7 transition duration-300 hover:-translate-y-1 hover:border-transparent hover:shadow-[0_20px_50px_rgba(1,84,93,0.12)]">
                  <span className="text-6xl font-bold leading-none" style={{ ...DISPLAY, color: i % 2 ? C.olive : C.canard }}>{String(i + 1).padStart(2, "0")}</span>
                  <span className="mt-8 grid h-11 w-11 place-items-center rounded-full text-white" style={{ background: i % 2 ? C.olive : C.canard }}><e.icon size={18} /></span>
                  <h3 className="mt-5 text-lg font-bold text-[#0F172A]">{e.titre}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-[#475569]">{e.texte}</p>
                </motion.li>
              ))}
            </ol>
          </div>
        </section>

        {/* Démonstration : aplat bleu canard */}
        <section id="demonstration" className="relative scroll-mt-20 overflow-hidden text-white" style={{ background: C.canardFonce }}>
          <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full opacity-30 blur-3xl" style={{ background: C.canard }} />
          <div className="relative mx-auto max-w-6xl px-4 py-28 sm:px-6">
            <div className="grid gap-8 lg:grid-cols-2 lg:items-end">
              <Titre sur="Démonstration" clair>Une crise <It color={C.moutarde}>en cascade</It>, jour après jour.</Titre>
              <p className="text-lg leading-relaxed text-white/75">
                Un laboratoire fabrique un antibiotique injectable à Tours. Ses principes actifs viennent d'Inde et de Chine et arrivent par Anvers. Voici ce que voient les trois agents.
              </p>
            </div>
            <ol className="relative mt-16 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {DEMO.map((d, i) => (
                <motion.li key={d.jour} {...apparition} transition={{ duration: 0.45, delay: (i % 3) * 0.06 }}
                  className="flex flex-col gap-5 rounded-[24px] bg-white/[0.06] p-6 ring-1 ring-white/10 backdrop-blur transition duration-300 hover:bg-white/[0.1]">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-4xl font-bold" style={DISPLAY}>J{d.jour}</span>
                    <span className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/70">{d.maillon}</span>
                  </div>
                  <p className="flex-1 text-[15px] leading-relaxed text-white/90">{d.texte}</p>
                  <div className="flex flex-wrap gap-1.5">{d.agents.map((a) => <AgentBadge key={a} agent={a} size="xs" />)}</div>
                </motion.li>
              ))}
            </ol>
            <p className="mt-10 max-w-3xl text-lg leading-relaxed text-white/85">
              Chaque signal est rattaché au bon maillon : le fournisseur de Hyderabad, le port d'Anvers, puis l'usine de Tours qu'ils approvisionnent. Le risque se propage dans le graphe <It color={C.moutarde}>jusqu'au produit fini</It>, avec les sources de chaque alerte.
            </p>
            <p className="mt-3 text-xs text-white/45">Scénario fictif écrit pour la démonstration : ni les articles, ni les mesures, ni les entreprises ne sont réels.</p>
          </div>
        </section>

        {/* Profils */}
        <section style={{ background: C.creme }}>
          <div className="mx-auto grid max-w-6xl gap-14 px-4 py-28 sm:px-6 lg:grid-cols-[0.9fr_1.1fr]">
            <Titre sur="Pour qui">Une lecture <It color={C.olive}>pour chaque</It> métier.</Titre>
            <div className="divide-y divide-[#0F172A]/10 border-y border-[#0F172A]/10">
              {PROFILS.map((p) => (
                <motion.div key={p.titre} {...apparition} className="group flex items-center gap-5 py-7">
                  <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-[#0F172A] text-white transition group-hover:bg-[#017F8D]"><p.icon size={19} /></span>
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
        <section id="fonctionnalites" className="scroll-mt-20 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-28 sm:px-6">
            <Titre sur="Fonctionnalités">Tout ce qu'il faut <It color={C.canard}>pour voir venir.</It></Titre>
            <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {FONCTIONS.map((f, i) => (
                <motion.div key={f.titre} {...apparition} transition={{ duration: 0.45, delay: (i % 3) * 0.06 }}
                  className="rounded-[24px] border border-[#E2E8F0] p-7 transition duration-300 hover:-translate-y-1 hover:shadow-[0_20px_50px_rgba(15,23,42,0.08)]">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl" style={{ background: `${f.couleur}22`, color: f.couleur === C.moutarde ? "#9C7700" : f.couleur }}><f.icon size={21} /></span>
                  <h3 className="mt-5 text-lg font-bold text-[#0F172A]">{f.titre}</h3>
                  <p className="mt-1.5 leading-relaxed text-[#475569]">{f.texte}</p>
                </motion.div>
              ))}
            </div>
            <div className="mt-8 flex flex-wrap gap-2"><AgentBadge agent="media" /><AgentBadge agent="weather" /><AgentBadge agent="finance" /></div>
          </div>
        </section>

        {/* Confidentialité : aplat vert olive */}
        <section id="confidentialite" className="scroll-mt-20" style={{ background: C.olive }}>
          <div className="mx-auto max-w-6xl px-4 py-28 sm:px-6">
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

        {/* Appel à l'action : aplat moutarde */}
        <section style={{ background: C.moutarde }}>
          <div className="mx-auto flex max-w-6xl flex-col items-start gap-10 px-4 py-24 sm:px-6 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-5xl font-bold leading-[0.95] tracking-tight text-[#0F172A] sm:text-7xl" style={DISPLAY}>Une chaîne <It>à surveiller ?</It></h2>
              <p className="mt-5 max-w-lg text-lg text-[#0F172A]/75">Créez votre espace en quelques minutes. Vous pourrez exporter ou supprimer vos données à tout moment.</p>
              <div className="mt-8 flex flex-wrap gap-3">
                <button className="group inline-flex items-center gap-2 rounded-full bg-[#0F172A] px-6 py-3.5 text-sm font-bold text-white transition hover:-translate-y-0.5" onClick={() => aller("#/inscription")}>
                  Créer un espace <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
                </button>
                <button className="rounded-full border border-[#0F172A]/25 px-6 py-3.5 text-sm font-semibold text-[#0F172A] transition hover:bg-[#0F172A]/5" onClick={() => aller("#/connexion")}>J'ai déjà un compte</button>
              </div>
            </div>
            <Tampon />
          </div>
        </section>
      </PublicShell>
    </MotionConfig>
  );
}
