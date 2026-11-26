// Carte du monde sans doublon à l'écran : on peut glisser à l'infini vers la gauche ou la droite (le monde se
// prolonge), mais le zoom minimal est calculé pour que la largeur visible ne dépasse jamais un tour de planète.
// Même dézoomé au maximum, un continent n'apparaît donc qu'une fois sur l'écran.
import type maplibregl from "maplibre-gl";

export const OPTIONS_MONDE = { renderWorldCopies: true };

/** Applique le zoom minimal adapté à la largeur de la carte et le tient à jour. */
export function bloquerMonde(m: maplibregl.Map): void {
  const ajuster = () => {
    const largeur = m.getContainer().clientWidth || 512;
    // à un zoom z, le monde mesure 512 × 2^z pixels de large ; petite marge pour ne pas voir le même bord deux fois
    m.setMinZoom(Math.max(0, Math.log2(largeur / 512) + 0.02));
  };
  ajuster();
  m.on("resize", ajuster);
}
