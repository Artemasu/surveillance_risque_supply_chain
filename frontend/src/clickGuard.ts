// Distinction stricte entre clic sec et glisser (déplacement de carte, rotation du globe ou de la sphère 3D) :
// la position du pointeur est mémorisée à l'appui, et un relâchement à plus de CLICK_TOLERANCE_PX n'est pas un clic.
import { useMemo } from "react";

export const CLICK_TOLERANCE_PX = 4;

interface Point {
  clientX: number;
  clientY: number;
}

export interface ClickGuard {
  /** À appeler au `pointerdown` sur le conteneur de la vue. */
  down: (e: Point) => void;
  /** Vrai si le relâchement est resté à moins de 4 px de l'appui : un clic sec, pas un glisser. */
  isClick: (e: Point) => boolean;
}

export function createClickGuard(tolerance = CLICK_TOLERANCE_PX): ClickGuard {
  let start: { x: number; y: number } | null = null;
  return {
    down: (e) => {
      start = { x: e.clientX, y: e.clientY };
    },
    isClick: (e) => !start || Math.hypot(e.clientX - start.x, e.clientY - start.y) <= tolerance,
  };
}

export function useClickGuard(tolerance = CLICK_TOLERANCE_PX): ClickGuard {
  return useMemo(() => createClickGuard(tolerance), [tolerance]);
}
