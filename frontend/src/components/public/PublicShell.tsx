// Habillage des pages publiques (vitrine, connexion, inscription) : barre supérieure et pied de page.
// Variante « sombre » pour la page vitrine (fond nuit), claire pour les formulaires.
import { LogIn } from "lucide-react";
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
      <span className="leading-tight">
        <span className={`block text-[15px] font-bold tracking-[0.08em] ${clair ? "text-white" : "text-ink"}`} style={{ fontFamily: '"Space Grotesk", "Plus Jakarta Sans", sans-serif' }}>A.E.G.I.S.</span>
        <span className={`hidden text-[10px] font-semibold uppercase tracking-[0.16em] sm:block ${clair ? "text-white/50" : "text-ink-mute"}`}>Détecter · Comprendre · Anticiper</span>
      </span>
    </a>
  );
}

export default function PublicShell({ children, nav = true, sombre = false }: { children: ReactNode; nav?: boolean; sombre?: boolean }) {
  const lien = sombre ? "text-white/70 hover:text-white" : "text-ink-soft hover:text-ink";
  return (
    <div className={`min-h-screen ${sombre ? "bg-[#061417]" : "bg-canvas"}`}>
      <header className={`sticky top-0 z-30 backdrop-blur-md ${sombre ? "border-b border-white/10 bg-[#061417]/95" : "border-b border-line/70 bg-white/85"}`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Logo clair={sombre} />
          {nav && (
            <nav className={`hidden items-center gap-7 text-sm font-medium md:flex ${lien}`}>
              <a href="#fonctionnement" className={lien}>Fonctionnement</a>
              <a href="#demonstration" className={lien}>Démonstration</a>
              <a href="#fonctionnalites" className={lien}>Fonctionnalités</a>
              <a href="#confidentialite" className={lien}>Confidentialité</a>
            </nav>
          )}
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
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 text-sm sm:grid-cols-3 sm:px-6">
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
        <p className="border-t border-white/10 py-4 text-center text-[11px] text-white/40">© 2026 A.E.G.I.S. · Projet de l'école d'ingénieurs ESME Sudria</p>
      </footer>
    </div>
  );
}
