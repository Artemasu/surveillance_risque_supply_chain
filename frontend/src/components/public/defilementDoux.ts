// Défilement adouci de la page vitrine (Lenis) : la molette n'avance plus par à-coups, la page glisse et
// ralentit en douceur, ce qui lisse les passages d'une animation à l'autre (fil, sections figées, fiches).
// Les animations liées au défilement (framer-motion) suivent toujours la vraie position de la page.
// Coupé avec « réduire les animations », sur écran tactile (défilement natif) et pendant l'intro.
import Lenis from "lenis";
import "lenis/dist/lenis.css";
import { useEffect, useRef } from "react";

export function useDefilementDoux(actif: boolean, enPause: boolean) {
  const lenis = useRef<Lenis | null>(null);

  useEffect(() => {
    if (!actif) return;
    const l = new Lenis({
      autoRaf: true,
      lerp: 0.085,             // part de la distance restante parcourue à chaque image : plus bas = plus doux
      wheelMultiplier: 0.9,
      smoothWheel: true,
    });
    lenis.current = l;
    return () => { l.destroy(); lenis.current = null; };
  }, [actif]);

  useEffect(() => {
    if (enPause) lenis.current?.stop();
    else lenis.current?.start();
  }, [enPause, actif]);
}
