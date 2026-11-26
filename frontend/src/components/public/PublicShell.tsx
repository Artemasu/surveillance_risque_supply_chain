// Habillage des pages publiques (vitrine, connexion, inscription) : barre supérieure et pied de page.
// Variante « sombre » pour la page vitrine (fond nuit), claire pour les formulaires.
import { motion } from "framer-motion";
import { ArrowUp, LogIn } from "lucide-react";
import type { ReactNode } from "react";

export const aller = (route: string) => {
  window.location.hash = route;
  window.scrollTo({ top: 0 });
};

export function Logo({ clair = false }: { clair?: boolean }) {
  return (
    <a href="#/" className="flex items-center gap-2.5" aria-label="Accueil A.E.G.I.S.">
      <span className={`grid h-9 w-9 place-items-center overflow-hidden rounded-xl ${clair ? "bg-white/10 ring-1 ring-white/15" : "bg-gradient-to-br from-sky-50 to-white ring-1 ring-line"}`}>
        <img src={`${import.meta.env.BASE_URL}copilot/slime_calm_idle.png`} alt="" draggable={false} className="slime-sprite block select-none" style={{ width: 33 }} />
      </span>
      <span className={`text-[15px] font-bold tracking-[0.08em] ${clair ? "text-white" : "text-ink"}`} style={{ fontFamily: '"Space Grotesk", "Plus Jakarta Sans", sans-serif' }}>A.E.G.I.S.</span>
    </a>
  );
}

// `nav` est conservé pour compatibilité (Login, inscription) : la barre n'affiche plus de liens de navigation.
export default function PublicShell({ children, sombre = false }: { children: ReactNode; nav?: boolean; sombre?: boolean }) {
  return (
    <div className={`min-h-screen ${sombre ? "bg-[#061417]" : "bg-canvas"}`}>
      <header className={`sticky top-0 z-30 backdrop-blur-md ${sombre ? "border-b border-white/10 bg-[#061417]/95" : "border-b border-line/70 bg-white/85"}`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Logo clair={sombre} />
          <div className="flex items-center gap-2">
            <button className={`btn hidden rounded-full sm:inline-flex ${sombre ? "border border-white/20 text-white hover:bg-white/10" : "btn-ghost"}`} onClick={() => aller("#/inscription")}>
              Créer un espace
            </button>
            <button className={`btn rounded-full shadow-sm ${sombre ? "bg-white text-ink hover:bg-slate-100" : "bg-ink text-white hover:bg-slate-800"}`} onClick={() => aller("#/connexion")}>
              <LogIn size={15} /> Connexion
            </button>
          </div>
        </div>
      </header>
      <main>{children}</main>
      <footer className="bg-[#061417] text-white/70">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 pb-12 pt-4 text-sm sm:grid-cols-3 sm:px-6">
          <div>
            <Logo clair />
            <p className="mt-3 max-w-xs text-xs text-white/50">Surveillance des risques de chaîne d'approvisionnement par l'actualité, la météo, les marchés et les graphes.</p>
          </div>
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/40">Service</p>
            <a href="#/inscription" className="block hover:text-white">Créer un espace</a>
            <a href="#/connexion" className="block hover:text-white">Connexion</a>
          </div>
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/40">Utilisation</p>
            <a href="#/donnees" className="block hover:text-white">Protection des données</a>
            <span className="block text-white/40">Aucun cookie publicitaire ni de mesure d'audience</span>
          </div>
        </div>
        {/* signature géante : les lettres montent une à une à chaque arrivée en bas de page (et redescendent en repartant) */}
        <div aria-hidden className="relative overflow-hidden px-2">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2" style={{ background: "radial-gradient(ellipse at 50% 100%, rgba(1,127,141,0.35), transparent 70%)" }} />
          <div className="relative flex select-none justify-center leading-[0.8]" style={{ fontFamily: '"Space Grotesk", "Plus Jakarta Sans", sans-serif' }}>
            {"A.E.G.I.S.".split("").map((c, i) => (
              <motion.span key={i} initial={{ y: "70%", opacity: 0 }} whileInView={{ y: "0%", opacity: 1 }} viewport={{ once: false, margin: "-40px" }}
                transition={{ duration: 0.9, delay: i * 0.06, ease: [0.22, 1, 0.36, 1] }}
                className="inline-block text-[clamp(4.5rem,19vw,17rem)] font-bold tracking-[-0.04em]"
                style={{ backgroundImage: "linear-gradient(180deg, rgba(127,208,214,0.9) 0%, rgba(1,127,141,0.55) 55%, rgba(6,20,23,0) 100%)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>
                {c}
              </motion.span>
            ))}
          </div>
        </div>
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 border-t border-white/10 px-4 py-4 text-[11px] text-white/40 sm:px-6">
          <p>© 2026 A.E.G.I.S. · Projet de l'école d'ingénieurs ESME Sudria</p>
          <button type="button" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })} className="inline-flex items-center gap-1.5 hover:text-white">
            Haut de page <ArrowUp size={12} />
          </button>
        </div>
      </footer>
    </div>
  );
}
