// Intro de la page d'accueil (première visite de la session, 8,4 s au plus) :
//   0 s      écran noir ; le globe apparaît en fondu au centre, tout petit, et grandit jusqu'à sa taille normale
//   1,5 s    la chaîne s'allume vague par vague : fournisseurs, ports, usines (voir Globe)
//   2,0 s    le logo prend la scène : halo, pastille qui éclot, lettres qui se posent une à une, puis la devise
//   7,0 s    le globe glisse vers sa place dans le bandeau, le logo vers la barre du haut, le noir se dissipe
//   8,4 s    fin : la page est à vous
// Un clic, une touche, la molette ou « Passer » vont directement au glissement final.
// Jamais jouée avec « réduire les animations », ni une deuxième fois dans le même onglet.
import { useEffect, useLayoutEffect, useRef, useState, type MutableRefObject } from "react";

const CLE = "aegis-intro-vue";
export const T_SORTIE = 7.0;                 // début du glissement final
const DUREE_SORTIE = 1.4, DUREE_SORTIE_RAPIDE = 0.9;
const EASE = "cubic-bezier(0.65, 0, 0.35, 1)";
const LOGO_ECHELLE = 2.6;
const LETTRES = "A.E.G.I.S.".split("");
const DISPLAY = { fontFamily: '"Space Grotesk", "Plus Jakarta Sans", system-ui, sans-serif' };

export function introAJouer(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  try { return sessionStorage.getItem(CLE) !== "1"; } catch { return true; }
}

function logoDuHaut(): HTMLElement | null {
  return document.querySelector<HTMLElement>('header a[aria-label="Accueil A.E.G.I.S."]');
}

export default function Intro({ globe, horloge, globePret, onSortie, onFin }: {
  globe: MutableRefObject<HTMLDivElement | null>;   // conteneur du globe dans le bandeau
  horloge: MutableRefObject<number>;                  // horloge partagée avec le globe (secondes)
  globePret: boolean;
  onSortie: () => void;                               // début du glissement : la page peut animer son texte
  onFin: () => void;
}) {
  const voile = useRef<HTMLDivElement>(null);
  const logo = useRef<HTMLDivElement>(null);
  const devise = useRef<HTMLDivElement>(null);
  const icone = useRef<HTMLSpanElement>(null);
  const mot = useRef<HTMLSpanElement>(null);
  const aura = useRef<HTMLDivElement>(null);
  const [demarre, setDemarre] = useState(false);
  const etat = useRef({ sortie: false, debut: 0, place: { x: 0, y: 0, s: 1 }, opaciteFinale: "1" });

  // Mise en place : page bloquée en haut, globe tiré au centre de l'écran au-dessus du voile noir.
  useLayoutEffect(() => {
    try { sessionStorage.setItem(CLE, "1"); } catch { /* navigation privée : l'intro rejouera, sans gravité */ }
    window.scrollTo(0, 0);
    const html = document.documentElement;
    const debordement = html.style.overflow;
    html.style.overflow = "hidden";
    const haut = logoDuHaut();
    if (haut) haut.style.opacity = "0";
    const g = globe.current;
    if (g) {
      const r = g.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight;
      const s = Math.min(1, (vh * 0.64) / r.height, (vw * 0.95) / r.width);
      const place = { x: vw / 2 - (r.left + r.width / 2), y: vh * 0.37 - (r.top + r.height / 2), s };
      etat.current.place = place;
      etat.current.opaciteFinale = getComputedStyle(g).opacity;
      g.style.zIndex = "45";
      g.style.opacity = "0";
      g.style.transform = `translate(${place.x}px, calc(-50% + ${place.y}px)) scale(${s})`;
    }
    return () => {
      html.style.overflow = debordement;
      if (haut) haut.style.opacity = "";
      if (g) { g.style.zIndex = ""; g.style.opacity = ""; g.style.transform = ""; }
    };
  }, [globe]);

  // Départ quand le globe a dessiné sa première image (ou après 1,5 s s'il n'y a pas de WebGL).
  useEffect(() => {
    if (globePret) { setDemarre(true); return; }
    const id = window.setTimeout(() => setDemarre(true), 1500);
    return () => window.clearTimeout(id);
  }, [globePret]);

  useEffect(() => {
    if (!demarre) return;
    const g = globe.current;
    g?.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 1800, easing: "ease-out", fill: "forwards" });
    // le logo prend la scène : halo, pastille qui éclot, lettres posées une à une, lueur qui se calme
    const doux = "cubic-bezier(0.22, 1, 0.36, 1)";
    if (logo.current) logo.current.style.opacity = "1";
    aura.current?.animate([{ opacity: 0, transform: "translateX(-50%) scale(0.6)" }, { opacity: 1, transform: "translateX(-50%) scale(1.08)", offset: 0.55 }, { opacity: 0.55, transform: "translateX(-50%) scale(1)" }],
      { duration: 2600, delay: 1900, easing: "ease-out", fill: "both" });
    icone.current?.animate([
      { opacity: 0, transform: "scale(0.35) rotate(-14deg)", filter: "blur(6px)" },
      { opacity: 1, transform: "scale(1) rotate(0deg)", filter: "blur(0px)" },
    ], { duration: 950, delay: 2000, easing: "cubic-bezier(0.34, 1.56, 0.64, 1)", fill: "both" });
    Array.from(mot.current?.children ?? []).forEach((lettre, i) => {
      (lettre as HTMLElement).animate([
        { opacity: 0, transform: "translateY(0.55em)", filter: "blur(6px)" },
        { opacity: 1, transform: "none", filter: "blur(0px)" },
      ], { duration: 750, delay: 2450 + i * 80, easing: doux, fill: "both" });
    });
    mot.current?.animate([
      { textShadow: "0 0 0 rgba(95,196,207,0)" },
      { textShadow: "0 0 18px rgba(95,196,207,0.95)", offset: 0.35 },
      { textShadow: "0 0 7px rgba(95,196,207,0.4)" },
    ], { duration: 2200, delay: 2600, easing: "ease-out", fill: "both" });
    devise.current?.animate([{ opacity: 0, transform: "translateY(6px)", letterSpacing: "0.5em" }, { opacity: 1, transform: "none", letterSpacing: "0.32em" }],
      { duration: 1200, delay: 3700, easing: doux, fill: "both" });

    let id = 0, fini = false;
    etat.current.debut = performance.now();
    const minuterie: number[] = [];

    const sortir = (rapide: boolean) => {
      if (etat.current.sortie) return;
      etat.current.sortie = true;
      horloge.current = Math.max(horloge.current, 99);   // la chaîne finit de se tracer d'un coup si on passe
      onSortie();
      const duree = (rapide ? DUREE_SORTIE_RAPIDE : DUREE_SORTIE) * 1000;
      const { place, opaciteFinale } = etat.current;
      // globe : du centre vers sa place dans le bandeau
      if (g) {
        const a = g.animate([
          { transform: `translate(${place.x}px, calc(-50% + ${place.y}px)) scale(${place.s})`, opacity: 1 },
          { transform: "translate(0px, -50%) scale(1)", opacity: Number(opaciteFinale) },
        ], { duration: duree, easing: EASE, fill: "forwards" });
        a.onfinish = () => { g.style.transform = ""; g.style.opacity = ""; g.style.zIndex = ""; g.getAnimations().forEach((x) => x.cancel()); };
      }
      // devise : s'efface
      devise.current?.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400, fill: "forwards", easing: "ease-out" });
      // logo : du centre vers la barre du haut (même taille et même place que le vrai logo)
      const haut = logoDuHaut(), l = logo.current;
      // fin des apparitions (si l'on a passé l'intro), halo qui s'éteint, lueur du mot qui disparaît
      [icone.current, ...Array.from(mot.current?.children ?? [])].forEach((e) => e?.getAnimations().forEach((x) => x.finish()));
      aura.current?.animate([{ opacity: 0.55 }, { opacity: 0 }], { duration: 500, fill: "forwards" });
      mot.current?.getAnimations().forEach((x) => x.cancel());
      mot.current?.animate([{ textShadow: "0 0 7px rgba(95,196,207,0.4)" }, { textShadow: "0 0 0 rgba(95,196,207,0)" }], { duration: duree, fill: "forwards" });
      if (haut && l) {
        // position du logo sans agrandissement, puis glissement vers le logo de la barre (même dessin, même taille)
        l.style.transform = "none";
        const cible = haut.getBoundingClientRect(), depart = l.getBoundingClientRect();
        const dx = cible.left - depart.left, dy = cible.top - depart.top;
        l.style.opacity = "1";
        l.animate([{ transform: `translate(0px, 0px) scale(${LOGO_ECHELLE})` }, { transform: `translate(${dx}px, ${dy}px) scale(1)` }],
          { duration: duree, easing: EASE, fill: "forwards" });
      }
      // voile noir : se dissipe un peu après le départ du globe
      voile.current?.animate([{ opacity: 1 }, { opacity: 0 }], { duration: duree * 0.85, delay: duree * 0.15, easing: "ease-in-out", fill: "forwards" });
      minuterie.push(window.setTimeout(() => {
        if (haut) haut.style.opacity = "";
        fini = true;
        onFin();
      }, duree + 30));
    };

    const image = () => {
      if (fini) return;
      id = requestAnimationFrame(image);
      const t = (performance.now() - etat.current.debut) / 1000;
      if (!etat.current.sortie) horloge.current = t;
      if (t >= T_SORTIE) sortir(false);
    };
    id = requestAnimationFrame(image);

    const passer = () => sortir(true);
    window.addEventListener("keydown", passer);
    window.addEventListener("wheel", passer, { passive: true });
    window.addEventListener("touchmove", passer, { passive: true });
    return () => {
      cancelAnimationFrame(id);
      minuterie.forEach((x) => window.clearTimeout(x));
      window.removeEventListener("keydown", passer);
      window.removeEventListener("wheel", passer);
      window.removeEventListener("touchmove", passer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demarre]);

  return (
    <>
      {/* voile noir, sous le globe (z 45) ; un clic n'importe où passe l'intro */}
      <div ref={voile} className="fixed inset-0 z-40 bg-[#030A0C]" onClick={() => window.dispatchEvent(new KeyboardEvent("keydown"))}>
        <div className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(ellipse at 50% 42%, rgba(1,127,141,0.22), transparent 60%)" }} />
        <button type="button" className="absolute bottom-6 right-6 rounded-full border border-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white/50 transition hover:border-white/40 hover:text-white"
          onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new KeyboardEvent("keydown")); }}>
          Passer
        </button>
      </div>
      {/* logo et devise, au-dessus de tout, sous le globe ; même dessin que le logo de la barre du haut */}
      <div className="pointer-events-none fixed inset-x-0 top-[73vh] z-50 flex flex-col items-center">
        <div ref={aura} className="absolute left-1/2 top-[-60px] h-[200px] w-[620px] -translate-x-1/2 rounded-full opacity-0 blur-2xl"
          style={{ background: "radial-gradient(ellipse at center, rgba(1,127,141,0.55), rgba(236,185,32,0.12) 55%, transparent 72%)" }} />
        <div ref={logo} className="relative opacity-0" style={{ transform: `scale(${LOGO_ECHELLE})`, transformOrigin: "center" }}>
          <div className="flex items-center gap-2.5">
            <span ref={icone} className="grid h-9 w-9 place-items-center overflow-hidden rounded-xl bg-white/10 ring-1 ring-white/15">
              <img src={`${import.meta.env.BASE_URL}copilot/slime_calm_idle.png`} alt="" draggable={false} className="slime-sprite block select-none" style={{ width: 33 }} />
            </span>
            <span ref={mot} className="text-[15px] font-bold tracking-[0.08em] text-white" style={DISPLAY}>
              {LETTRES.map((c, i) => <span key={i} className="inline-block">{c}</span>)}
            </span>
          </div>
        </div>
        <div ref={devise} className="relative mt-16 text-center text-[11px] font-semibold uppercase tracking-[0.32em] text-white/60 opacity-0" style={DISPLAY}>
          Automated Early-warning &amp; Graph Intelligence for Supply-chain
        </div>
      </div>
    </>
  );
}
