// Fil d'approvisionnement de la page vitrine, dans l'esprit du globe du bandeau : un fil fin descend du globe,
// relie les trois mots-clés (comme des fournisseurs branchés sur la chaîne), passe derrière les cartes des
// étapes et file vers la démonstration. Il se colore au fil du défilement, et de petites boules lumineuses
// à traînée (les mêmes couleurs que les signaux du globe) y circulent en continu jusqu'au point atteint.
// Le tracé est calculé sur la position réelle des éléments repérés par des attributs data-fil, donc il suit
// la mise en page à toutes les largeurs. Les cartes ne sont pas modifiées : le fil passe derrière elles.
// « Réduire les animations » : fil entièrement coloré, sans boules en mouvement.
import { motion, useMotionValue, useMotionValueEvent, useReducedMotion, useScroll, useSpring } from "framer-motion";
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

const CANARD = "#017F8D";
const SIGNAUX = ["#ECB920", "#A2B153", "#017F8D"];   // moutarde, olive, canard (comme les signaux du globe)
const TRAINEE = 6;                                  // points de traînée derrière chaque boule (effet comète)
const NB_BOULES = 10;
const VITESSE = 110;                                // pixels par seconde le long du fil
const RAYON = 36;                                   // arrondi des virages

type Pt = [number, number];

/** Chemin à angles droits aux virages arrondis. */
function chemin(points: Pt[], r = RAYON): string {
  if (points.length < 2) return "";
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [x0, y0] = points[i - 1], [x1, y1] = points[i], [x2, y2] = points[i + 1];
    const l1 = Math.hypot(x1 - x0, y1 - y0), l2 = Math.hypot(x2 - x1, y2 - y1);
    const k = Math.min(r, l1 / 2, l2 / 2);
    const a: Pt = [x1 - ((x1 - x0) / l1) * k, y1 - ((y1 - y0) / l1) * k];
    const b: Pt = [x1 + ((x2 - x1) / l2) * k, y1 + ((y2 - y1) / l2) * k];
    d += ` L${a[0]},${a[1]} Q${x1},${y1} ${b[0]},${b[1]}`;
  }
  const [xn, yn] = points[points.length - 1];
  return `${d} L${xn},${yn}`;
}

interface Noeud { d: string; x: number; y: number; jx: number; jy: number; couleur: string; sansNoeud?: boolean }   // (jx, jy) : jonction sur le fil

interface Trace {
  l: number; h: number;
  principal: string;
  branches: Noeud[];
  cache?: { x: number; y: number; l: number; h: number };   // zone où la section figée dessine elle-même le fil
}

/** « haut » : des mots-clés aux étapes ; « bas » : des profils jusqu'à l'appel à l'action (arrivée). */
export default function FilSupplyChain({ children, parcours = "haut" }: { children: ReactNode; parcours?: "haut" | "bas" }) {
  const zone = useRef<HTMLDivElement>(null);
  const fil = useRef<SVGPathElement>(null);
  const boules = useRef<SVGGElement>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const reduit = useReducedMotion();
  const uid = useId().replace(/:/g, "");      // identifiants SVG propres à chaque fil (il y en a deux sur la page)

  // Remplissage calé sur l'écran : la tête du fil coloré suit une ligne placée aux deux tiers de la hauteur
  // de l'écran. Table « longueur parcourue → hauteur » du tracé, puis plus grande longueur dont la hauteur
  // est au-dessus de cette ligne. Les passages horizontaux se remplissent d'un trait quand la ligne les
  // franchit ; un ressort court lisse ces sauts sans retard visible.
  const LIGNE = 0.66;
  const table = useRef<{ total: number; y: number[]; pas: number } | null>(null);
  const brut = useMotionValue(reduit ? 1 : 0);
  const avance = useSpring(brut, { stiffness: 260, damping: 34, restDelta: 0.0005 });
  const { scrollY } = useScroll();
  const caler = () => {
    const t = table.current, racine = zone.current;
    if (reduit) { brut.set(1); return; }
    if (!t || !racine) return;
    const cible = window.innerHeight * LIGNE - racine.getBoundingClientRect().top;
    let i = 0;
    while (i + 1 < t.y.length && t.y[i + 1] <= cible) i++;
    const enBas = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;   // bas de page : fil complet
    brut.set(enBas && cible > 0 ? 1 : t.y[0] > cible ? 0 : Math.min(1, (i * t.pas) / t.total));
  };
  useMotionValueEvent(scrollY, "change", caler);
  const [atteint, setAtteint] = useState(reduit ? 1 : 0);
  useMotionValueEvent(avance, "change", (v) => setAtteint((a) => (Math.abs(a - v) > 0.005 || v >= 0.999 || v <= 0.001 ? v : a)));
  const [parts, setParts] = useState<number[]>([]);

  // table du tracé et position des jonctions, refaites à chaque nouveau tracé
  useEffect(() => {
    const p = fil.current;
    if (!trace || !p) return;
    const total = p.getTotalLength(), pas = 6, y: number[] = [], pts: { x: number; y: number }[] = [];
    for (let l = 0; l <= total; l += pas) { const q = p.getPointAtLength(l); y.push(q.y); pts.push(q); }
    for (let i = 1; i < y.length; i++) y[i] = Math.max(y[i], y[i - 1]);   // tracé toujours descendant
    table.current = { total, y, pas };
    setParts(trace.branches.map((b) => {
      let k = 0, d = Infinity;
      pts.forEach((q, i) => { const e = Math.hypot(q.x - b.jx, q.y - b.jy); if (e < d) { d = e; k = i; } });
      return Math.min(0.995, (k * pas) / total);
    }));
    caler();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trace]);

  // ---- tracé, recalculé quand la mise en page change
  useLayoutEffect(() => {
    const racine = zone.current;
    if (!racine) return;
    const pos = (el: HTMLElement) => {          // position dans la zone, sans les transformations d'apparition
      let x = 0, y = 0, n: HTMLElement | null = el;
      while (n && n !== racine) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent as HTMLElement | null; }
      return { x, y, l: el.offsetWidth, h: el.offsetHeight };
    };
    const mesurer = () => {
      const L = racine.offsetWidth, H = racine.offsetHeight;
      const q = (s: string) => racine.querySelector<HTMLElement>(`[data-fil="${s}"]`);
      if (L === 0) return;
      if (L < 768) {                           // mobile : un fil vertical dans la marge gauche
        setTrace({ l: L, h: H, principal: chemin([[8, 0], [8, H]]), branches: [] });
        return;
      }
      if (parcours === "bas") {
        const profils = q("profils"), fonctions = q("fonctions"), arrivee = q("arrivee");
        const station = racine.querySelector<HTMLElement>("[data-fil-station]");
        if (!profils || !fonctions || !arrivee || !station) return;
        const pr = pos(profils), f = pos(fonctions), st = pos(station), a = pos(arrivee);
        const gauche = Math.max(10, f.x - Math.min(48, f.x / 2));
        const droite = Math.min(L - 10, f.x + f.l + Math.min(48, (L - f.x - f.l) / 2));
        const xStation = st.x + st.l / 2;      // le fil passe derrière les pastilles des profils, comme des stations
        const yHaut = pr.y - 40, yBas = pr.y + pr.h + 48;
        // entre deux rangées de cartes de fonctionnalités
        const cartes = (Array.from(fonctions.children) as HTMLElement[]).map(pos);
        const rangees = [...new Set(cartes.map((c) => c.y))].sort((u, v) => u - v);
        const r1 = cartes.find((c) => c.y === rangees[0]);
        let yRangee = rangees.length > 1 && r1 ? (r1.y + r1.h + rangees[1]) / 2 : f.y + f.h + 32;
        // arrivée : à droite de l'élément, ou à une fraction de sa largeur (data-fil-arrivee-x, ex. le bord du globe)
        const fraction = Number(arrivee.dataset.filArriveeX);
        const yArrivee = a.y + a.h / 2, xArrivee = fraction ? a.x + a.l * fraction : a.x + a.l + 14;
        const branches: Noeud[] = [{ d: "", x: xArrivee, y: yArrivee, jx: xArrivee, jy: yArrivee, couleur: fraction ? "#ECB920" : "#0F172A" }];   // arrivée : le produit livré
        // Section des fonctionnalités figée : pendant le blocage, la ligne entre les rangées est dessinée par la
        // section elle-même (elle reste à l'écran, avec ses virages et des bouts verticaux qui recouvrent le fil).
        // Ici, le fil longe la marge gauche sur toute la hauteur du blocage et traverse là où la section se libère.
        let cache: Trace["cache"];
        const figee = q("fonctions-figee"), colle = figee?.firstElementChild as HTMLElement | null;
        if (figee && colle) {
          const debut = figee.offsetTop + (yRangee - pos(colle).y);         // ligne au début du blocage
          const marge = parseFloat(getComputedStyle(figee).paddingBottom) || 0;   // espace sous la section, hors blocage
          const course = figee.offsetHeight - marge - colle.offsetHeight;   // longueur du blocage
          yRangee = debut + course;                                         // ligne à la fin du blocage
          // la section dessine elle-même la traversée et le virage de droite : on masque ici cette portion du fil
          // pour qu'elle n'apparaisse pas en double sous les cartes avant que la section se libère
          // (marge gauche comprise : sous le virage, le fil ne doit pas continuer tout droit pendant le blocage)
          cache = { x: gauche - 4, y: debut - RAYON, l: droite - gauche + 10, h: course + 2 * RAYON + 2 };
        }
        const pts: Pt[] = [[droite, 0], [droite, yHaut], [xStation, yHaut], [xStation, yBas], [gauche, yBas], [gauche, yRangee],
          [droite, yRangee], [droite, yArrivee], [xArrivee, yArrivee]];
        setTrace({ l: L, h: H, principal: chemin(pts), branches, cache });
        return;
      }
      const phrase = q("phrase"), mots = q("mots"), etapes = q("etapes");
      const icone = racine.querySelector<HTMLElement>("[data-fil-icone]");
      if (!phrase || !mots || !etapes || !icone) return;
      const p = pos(phrase), m = pos(mots), e = pos(etapes), ic = pos(icone);
      const gauche = Math.max(10, e.x - Math.min(48, e.x / 2));
      const droite = Math.min(L - 10, e.x + e.l + Math.min(48, (L - e.x - e.l) / 2));
      const yMots = (p.y + p.h + m.y) / 2;     // entre la phrase et les trois mots
      const yIcones = ic.y + ic.h / 2;         // à hauteur des icônes rondes des cartes
      const xDepart = Math.min(droite, p.x + p.l + (L - p.x - p.l) * 0.45);
      const principal: Pt[] = [[xDepart, 0], [xDepart, yMots], [gauche, yMots], [gauche, yIcones], [droite, yIcones], [droite, H]];
      const branches = Array.from(racine.querySelectorAll<HTMLElement>("[data-fil-mot]")).map((el, i) => {
        const b = pos(el);
        const x = b.x + 1, y = b.y;           // le fil rejoint le liseré coloré au-dessus de chaque mot
        return { d: `M${x},${yMots} L${x},${y}`, x, y, jx: x, jy: yMots, couleur: SIGNAUX[i % 3] };
      });
      setTrace({ l: L, h: H, principal: chemin(principal), branches });
    };
    mesurer();
    const obs = new ResizeObserver(mesurer);
    obs.observe(racine);
    window.addEventListener("resize", mesurer);
    document.fonts?.ready.then(mesurer).catch(() => undefined);
    return () => { obs.disconnect(); window.removeEventListener("resize", mesurer); };
  }, [parcours]);

  // ---- boules lumineuses : avancent en boucle du début du fil jusqu'au point coloré
  useEffect(() => {
    const chemin = fil.current, groupe = boules.current;
    if (!trace || !chemin || !groupe || reduit) return;
    const total = chemin.getTotalLength();
    const cercles = Array.from(groupe.querySelectorAll("circle"));
    // les boules restent régulièrement espacées sur la partie colorée et avancent ensemble ;
    // arrivée au bout, une boule repart du haut du fil
    let visible = true, id = 0, avant = performance.now(), base = 0;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; });
    if (zone.current) io.observe(zone.current);
    const image = (now: number) => {
      id = requestAnimationFrame(image);
      const dt = Math.min(0.05, Math.max(0, (now - avant) / 1000));
      avant = now;
      if (!visible || document.hidden) return;
      const fin = avance.get() * total;
      base += dt * VITESSE;
      const ecart = Math.max(fin, 1) / NB_BOULES;
      base %= Math.max(ecart, 1);
      for (let b = 0; b < NB_BOULES; b++) {
        const tete = fin < 40 ? -1 : base + b * ecart;
        for (let k = 0; k < TRAINEE; k++) {
          const c = cercles[b * TRAINEE + k];
          const s = tete - k * 3.5;
          if (tete < 0 || s < 0) { c.setAttribute("opacity", "0"); continue; }
          const pt = chemin.getPointAtLength(s);
          // fondu à l'approche de la tête du fil, pour ne pas « buter » contre le bout coloré
          const fondu = Math.min(1, (fin - s) / 60, s / 30);
          c.setAttribute("cx", String(pt.x));
          c.setAttribute("cy", String(pt.y));
          c.setAttribute("opacity", String(Math.max(0, fondu) * (1 - k / TRAINEE)));
        }
      }
    };
    id = requestAnimationFrame(image);
    return () => { cancelAnimationFrame(id); io.disconnect(); };
  }, [trace, reduit, avance]);

  return (
    <div ref={zone} className="relative">
      {trace && (
        <svg aria-hidden className="pointer-events-none absolute inset-0" width={trace.l} height={trace.h} viewBox={`0 0 ${trace.l} ${trace.h}`}>
          <defs>
            <linearGradient id={`fil-degrade-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5FC4CF" />
              <stop offset="100%" stopColor={CANARD} />
            </linearGradient>
            <filter id={`fil-halo-${uid}`} x="-200%" y="-200%" width="500%" height="500%">
              <feGaussianBlur stdDeviation="2.2" result="flou" />
              <feMerge><feMergeNode in="flou" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            {trace.cache && (
              <mask id={`fil-cache-${uid}`} maskUnits="userSpaceOnUse" x={0} y={0} width={trace.l} height={trace.h}>
                <rect x={0} y={0} width={trace.l} height={trace.h} fill="white" />
                <rect x={trace.cache.x} y={trace.cache.y} width={trace.cache.l} height={trace.cache.h} fill="black" />
              </mask>
            )}
          </defs>
          {/* rail discret, puis fil coloré qui avance avec le défilement */}
          <g mask={trace.cache ? `url(#fil-cache-${uid})` : undefined}>
          <path d={trace.principal} fill="none" stroke={CANARD} strokeOpacity={0.14} strokeWidth={1.5} />
          {trace.branches.map((b, i) => b.d && (
            <path key={`r${i}`} d={b.d} fill="none" stroke={CANARD} strokeOpacity={atteint >= (parts[i] ?? 2) ? 0.55 : 0.14} strokeWidth={1.5} style={{ transition: "stroke-opacity .6s" }} />
          ))}
          <motion.path ref={fil} d={trace.principal} fill="none" stroke={`url(#fil-degrade-${uid})`} strokeWidth={2} strokeLinecap="round" style={{ pathLength: avance }} />
          </g>
          {/* nœuds : jonctions des fournisseurs, comme les points des sites sur le globe */}
          {trace.branches.map((b, i) => {
            const actif = atteint >= (parts[i] ?? 2);
            if (b.sansNoeud) return null;
            return (
              <g key={`n${i}`} style={{ transition: "opacity .6s", opacity: actif ? 1 : 0.35 }}>
                <circle cx={b.x} cy={b.y} r={7} fill={b.couleur} opacity={0.18}>
                  {actif && !reduit && <animate attributeName="r" values="4;11;4" dur="2.6s" repeatCount="indefinite" />}
                </circle>
                <circle cx={b.x} cy={b.y} r={b.d ? 3.2 : 5} fill={b.couleur} filter={`url(#fil-halo-${uid})`} />
              </g>
            );
          })}
          <g mask={trace.cache ? `url(#fil-cache-${uid})` : undefined}>
          <g ref={boules} filter={`url(#fil-halo-${uid})`}>
            {Array.from({ length: NB_BOULES * TRAINEE }, (_, j) => (
              <circle key={j} r={3.2 - (j % TRAINEE) * 0.4} fill={SIGNAUX[Math.floor(j / TRAINEE) % 3]} opacity={0} />
            ))}
          </g>
          </g>
        </svg>
      )}
      {children}
    </div>
  );
}
