"""Découpe les planches du compagnon Slime en 15 sprites PNG transparents pour le front-end React.

    python scripts/prepare_copilot_sprites.py
    python scripts/prepare_copilot_sprites.py --hd          # sans rééchantillonnage

Planches attendues (extension .png, .jpg ou .jpeg ; cherchées à la racine du dépôt, dans assets/ puis dans
frontend/sprites_src/) :
  etats_slime              3 slimes au repos : bleu (calm), jaune (warning), rouge (critical)       -> *_idle
  slime_situation_bleu     4 poses : pancarte, ampoule, joie, sommeil                             -> slime_calm_*
  slime_situation_jaune    idem                                                                    -> slime_warning_*
  slime_situation_rouge    idem                                                                    -> slime_critical_*
Sortie : frontend/public/copilot/slime_{calm,warning,critical}_{idle,announce,thinking,happy,sleepy}.png
         frontend/public/favicon-{32,64}.png (logo A.E.G.I.S. : slime calme, `--favicon-only` pour les seuls favicons)

Étapes, pour chaque planche :
  1. fond blanc détecté par flood-fill depuis les bords (connexité 4) : seul le blanc relié au bord devient
     transparent, le blanc enfermé dans un contour (yeux, reflets, ampoule, zZ) est conservé ;
  2. parasites JPEG isolés (petites taches non blanches dans le fond) supprimés ; une poche blanche fermée mais
     grande (entre le bras, la pancarte et le corps) est aussi du fond : plus de 3 % de la surface d'un corps, alors
     qu'un œil en fait moins de 2 % ;
  3. personnages séparés par composantes connexes (le nombre de personnages est connu) : un accessoire détaché
     (ampoule, étincelles, zZ) rejoint le slime le plus proche ;
  4. recadrage au plus près ;
  5. rééchantillonnage sur la grille du pixel art (taille d'un « pixel » estimée automatiquement, 7 à 10 px selon
     la planche) : le sprite retrouve sa résolution native et s'affiche net avec `image-rendering: pixelated` ;
  6. mise à l'échelle commune : les planches n'ont pas la même finesse de grille, donc chaque sprite est ramené à un
     corps de BODY_WIDTH px de large, pour qu'un changement d'état ne change pas la taille du slime.
     `--hd` saute les étapes 5 et 6 et garde la pleine résolution des planches ;
  7. export dans frontend/public/copilot/.

Dépendances : Pillow, numpy, scipy (déjà installés avec scikit-learn).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = [ROOT, ROOT / "assets", ROOT / "frontend" / "sprites_src"]
EXTENSIONS = (".png", ".jpg", ".jpeg")
OUT = ROOT / "frontend" / "public" / "copilot"

RISKS = ["calm", "warning", "critical"]
POSES = ["announce", "thinking", "happy", "sleepy"]
# planche -> noms des personnages, de gauche à droite
SHEETS: dict[str, list[str]] = {
    "etats_slime": [f"slime_{r}_idle" for r in RISKS],
    "slime_situation_bleu": [f"slime_calm_{p}" for p in POSES],
    "slime_situation_jaune": [f"slime_warning_{p}" for p in POSES],
    "slime_situation_rouge": [f"slime_critical_{p}" for p in POSES],
}

WHITE_MIN = 205        # canal minimal d'un pixel « blanc » (tolère le bruit JPEG autour des contours)
WHITE_SPREAD = 40      # écart max entre canaux : un blanc est peu saturé
SPECK_MAX_AREA = 40    # tache isolée plus petite que ça : bruit, supprimée
PAD = 1                # marge transparente autour du sprite recadré (en pixels exportés)
POCKET_MIN_FRAC = 0.03 # poche blanche fermée plus grande que 3 % d'un corps : fond, pas un œil ni un reflet
BODY_WIDTH = 58        # largeur commune du corps (px exportés), celle de la planche la plus fine


def background_mask(rgb: np.ndarray) -> np.ndarray:
    """Blanc relié au bord de l'image (flood-fill depuis les quatre bords)."""
    white = (rgb.min(axis=2) >= WHITE_MIN) & ((rgb.max(axis=2).astype(int) - rgb.min(axis=2)) <= WHITE_SPREAD)
    labels, _ = ndimage.label(white)                        # connexité 4 : un contour d'un pixel suffit à fermer
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    border = border[border > 0]
    return np.isin(labels, border)


def remove_pockets(rgb: np.ndarray, fg: np.ndarray, count: int) -> np.ndarray:
    """Poches blanches fermées trop grandes pour être un œil, un reflet ou un détail : rendues transparentes."""
    labels, n = ndimage.label(fg, structure=np.ones((3, 3)))
    if n < count:
        return fg
    body_area = float(np.median(np.sort(ndimage.sum(fg, labels, index=np.arange(1, n + 1)))[::-1][:count]))
    white = (rgb.min(axis=2) >= WHITE_MIN) & ((rgb.max(axis=2).astype(int) - rgb.min(axis=2)) <= WHITE_SPREAD) & fg
    wl, wn = ndimage.label(white)
    if not wn:
        return fg
    sizes = ndimage.sum(white, wl, index=np.arange(1, wn + 1))
    pockets = np.flatnonzero(sizes > POCKET_MIN_FRAC * body_area) + 1
    return fg & ~np.isin(wl, pockets)


def body_width(alpha: np.ndarray) -> int:
    """Largeur du corps : ligne la plus large dans le bas du sprite (sous la pancarte, l'ampoule, les zZ)."""
    rows = np.flatnonzero(alpha.any(axis=1))
    bottom = alpha[rows[-1] - max(2, (rows[-1] - rows[0]) // 7): rows[-1] + 1]
    return int(max(np.count_nonzero(r) for r in bottom))


def clean_foreground(fg: np.ndarray) -> np.ndarray:
    labels, n = ndimage.label(fg, structure=np.ones((3, 3)))
    if not n:
        return fg
    sizes = ndimage.sum(fg, labels, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes > SPECK_MAX_AREA
    return keep[labels]


def split_characters(fg: np.ndarray, count: int) -> list[np.ndarray]:
    """Un masque par personnage, de gauche à droite.

    Les `count` plus grandes composantes connexes sont les corps (la pancarte, tenue par le bras, fait partie du
    corps). Chaque petite pièce détachée (ampoule, étincelles, zZ) rejoint le corps le plus proche : d'abord par
    l'écart horizontal entre boîtes englobantes, puis par la distance entre centres. Les colonnes ne suffisent pas :
    la pancarte chevauche horizontalement le slime voisin."""
    labels, n = ndimage.label(fg, structure=np.ones((3, 3)))
    if n < count:
        raise SystemExit(f"{count} personnages attendus, seulement {n} forme(s) détectée(s)")
    sizes = ndimage.sum(fg, labels, index=np.arange(1, n + 1))
    boxes = ndimage.find_objects(labels)
    bodies = sorted(np.argsort(sizes)[::-1][:count], key=lambda i: boxes[i][1].start)
    masks = [labels == i + 1 for i in bodies]

    def span(i: int) -> tuple[int, int]:
        return boxes[i][1].start, boxes[i][1].stop

    for i in range(n):
        if i in bodies:
            continue
        a0, a1 = span(i)
        def score(b: int) -> tuple[int, float]:
            b0, b1 = span(b)
            return max(0, b0 - a1, a0 - b1), abs((a0 + a1) / 2 - (b0 + b1) / 2)
        target = min(range(count), key=lambda k: score(bodies[k]))
        masks[target] |= labels == i + 1
    return masks


def estimate_cell(rgb: np.ndarray, fg: np.ndarray) -> float:
    """Taille d'un pixel du pixel art, en pixels de la planche : écarts entre changements de couleur francs le long
    des lignes et des colonnes, puis période fondamentale qui explique le mieux ces écarts (multiples compris)."""
    gaps: list[int] = []
    for arr, m in ((rgb, fg), (rgb.transpose(1, 0, 2), fg.T)):
        for line, ml in zip(arr[::5].astype(int), m[::5]):
            if ml.sum() < 50:
                continue
            idx = np.flatnonzero(np.abs(np.diff(line, axis=0)).sum(axis=1) > 60)
            gaps.extend(int(g) for g in np.diff(idx) if 3 < g < 60)
    g = np.array(gaps, float)
    best, best_score = 1.0, -1.0
    for c in np.arange(4.0, 24.0, 0.1):
        k = np.maximum(1, np.round(g / c))
        score = float(np.sum(np.abs(g - k * c) <= 1.0) / np.mean(k))   # pénalise les sous-multiples
        if score > best_score:
            best, best_score = c, score
    return best


def extract(sheet: Path, names: list[str], hd: bool = False) -> list[Path]:
    rgb = np.asarray(Image.open(sheet).convert("RGB"))
    fg = clean_foreground(remove_pockets(rgb, clean_foreground(~background_mask(rgb)), len(names)))
    cell = 1.0 if hd else estimate_cell(rgb, fg)
    out = []
    for name, mask in zip(names, split_characters(fg, len(names))):
        ys, xs = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
        y0, y1, x0, x1 = ys[0], ys[-1] + 1, xs[0], xs[-1] + 1
        crop = Image.fromarray(np.dstack([rgb[y0:y1, x0:x1], np.where(mask[y0:y1, x0:x1], 255, 0).astype(np.uint8)]), "RGBA")
        if cell > 1:      # NEAREST échantillonne le centre de chaque cellule : aucune couleur inventée
            crop = crop.resize((max(1, round(crop.width / cell)), max(1, round(crop.height / cell))), Image.NEAREST)
            k = BODY_WIDTH / body_width(np.asarray(crop)[..., 3] > 0)
            if abs(k - 1) > 0.02:
                crop = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))), Image.NEAREST)
        img = Image.new("RGBA", (crop.width + 2 * PAD, crop.height + 2 * PAD), (0, 0, 0, 0))
        img.paste(crop, (PAD, PAD))
        path = OUT / f"{name}.png"
        img.save(path, optimize=True)
        out.append(path)
        print(f"{path.relative_to(ROOT).as_posix()} : {img.width}x{img.height} (pixel art {cell:.1f} px)")
    return out


def export_favicons(sizes: tuple[int, ...] = (32, 64)) -> None:
    """Favicons A.E.G.I.S. : le slime calme au repos, centré sur un carré transparent puis rééchantillonné au plus
    proche voisin à la taille exacte (un navigateur lisse toujours un favicon redimensionné, le CSS n'y peut rien)."""
    sprite = Image.open(OUT / "slime_calm_idle.png").convert("RGBA")
    side = max(sprite.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(sprite, ((side - sprite.width) // 2, side - sprite.height - (side - sprite.height) // 2))
    for size in sizes:
        path = OUT.parent / f"favicon-{size}.png"
        square.resize((size, size), Image.NEAREST).save(path, optimize=True)
        print(f"{path.relative_to(ROOT).as_posix()} : {size}x{size}")


def find_sheet(stem: str) -> Path:
    for d in SEARCH_DIRS:
        for ext in EXTENSIONS:
            for path in (d / f"{stem}{ext}", d / f"{stem}{ext.upper()}"):
                if path.exists():
                    return path
    raise SystemExit(f"planche introuvable : {stem}.(png|jpg|jpeg) dans " + ", ".join(str(d.relative_to(ROOT)) or "." for d in SEARCH_DIRS))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hd", action="store_true", help="garder la pleine résolution des planches (pas de rééchantillonnage)")
    ap.add_argument("--favicon-only", action="store_true", help="régénérer seulement les favicons depuis slime_calm_idle.png")
    args = ap.parse_args()
    if args.favicon_only:
        export_favicons()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    expected = {f"{n}.png" for names in SHEETS.values() for n in names}
    for stale in OUT.glob("slime_*.png"):          # sprites d'une ancienne version du compagnon
        if stale.name not in expected:
            stale.unlink()
    for stem, names in SHEETS.items():
        sheet = find_sheet(stem)
        print(f"{sheet.relative_to(ROOT).as_posix()}")
        extract(sheet, names, args.hd)
    export_favicons()


if __name__ == "__main__":
    main()
