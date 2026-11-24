"""
carte_koppen.py - Afficher la carte des climats de Köppen-Geiger (Beck et al., 2023)

Exemples (depuis le dossier meteo) :
    python carte_koppen.py --tif 1991_2020/koppen_geiger_0p1.tif --legende legend.txt
    python carte_koppen.py --tif 1991_2020/koppen_geiger_0p1.tif --legende legend.txt --zone europe --lieux "Paris, France" "Valence, Espagne"
    python carte_koppen.py --tif 1991_2020/koppen_geiger_0p1.tif --legende legend.txt --zone monde
    python carte_koppen.py --tif 1991_2020/koppen_geiger_0p1.tif --legende legend.txt --zone -10 30 35 60      (lon_min lon_max lat_min lat_max)

La carte est affichée et enregistrée en PNG (carte_koppen.png par défaut).
Dépendances : rasterio, numpy, matplotlib (+ meteo_collecte.py pour placer des lieux par leur nom).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch
from rasterio.windows import from_bounds

ZONES = {
    "monde": (-180, 180, -60, 85),
    "europe": (-12, 35, 34, 62),
    "france": (-5.5, 10, 41, 51.5),
    "asie": (60, 150, -12, 55),
    "amerique-nord": (-130, -60, 15, 60),
}


def lire_legende(chemin: str) -> dict[int, tuple[str, str, tuple[float, float, float]]]:
    """legend.txt de Beck : '  15:  Cfb  Temperate, no dry season, warm summer  [100 255 80]'."""
    legende = {}
    for ligne in Path(chemin).read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^\s*(\d+)\s*:?\s+([A-Z][A-Za-z]{0,2})\s+(.*?)\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s*\]", ligne)
        if m:
            num, code, texte = int(m.group(1)), m.group(2), m.group(3).strip(" ,")
            couleur = tuple(int(m.group(i)) / 255 for i in (4, 5, 6))
            legende[num] = (code, texte, couleur)
    if not legende:
        raise SystemExit(f"Aucune classe lue dans {chemin} : est-ce bien le legend.txt des cartes ?")
    return legende


def lire_zone(tif: str, zone: tuple[float, float, float, float]):
    lon_min, lon_max, lat_min, lat_max = zone
    with rasterio.open(tif) as carte:
        fenetre = from_bounds(lon_min, lat_min, lon_max, lat_max, carte.transform)
        donnees = carte.read(1, window=fenetre, boundless=True, fill_value=0)
    return donnees


def placer_lieux(noms: list[str]) -> list[tuple[str, float, float]]:
    if not noms:
        return []
    from meteo_collecte import geocoder  # le module météo du projet
    points = []
    for nom in noms:
        g = geocoder(nom)
        points.append((g["nom"], g["lat"], g["lon"]))
    return points


def dessiner(tif: str, legende_txt: str, zone, lieux: list[str], sortie: str, afficher: bool = True):
    legende = lire_legende(legende_txt)
    donnees = lire_zone(tif, zone)

    # Couleurs officielles de la légende ; 0 = mer ou pas de donnée (blanc)
    couleurs = [(1, 1, 1)] + [legende.get(i, ("?", "", (0.8, 0.8, 0.8)))[2] for i in range(1, 31)]
    cmap = ListedColormap(couleurs)
    norm = BoundaryNorm(np.arange(-0.5, 31.5, 1), cmap.N)

    lon_min, lon_max, lat_min, lat_max = zone
    largeur = 12
    hauteur = max(4, largeur * (lat_max - lat_min) / (lon_max - lon_min) * 1.15)
    fig, ax = plt.subplots(figsize=(largeur + 4, hauteur))
    ax.imshow(donnees, cmap=cmap, norm=norm, extent=(lon_min, lon_max, lat_min, lat_max),
              interpolation="nearest", origin="upper")
    ax.set_xlabel("Longitude (°)")
    ax.set_ylabel("Latitude (°)")
    ax.set_title("Climats de Köppen-Geiger, 1991-2020 (Beck et al., 2023)")

    for nom, lat, lon in placer_lieux(lieux):
        with rasterio.open(tif) as carte:
            num = int(next(carte.sample([(lon, lat)]))[0])
        code = legende.get(num, ("?",))[0]
        ax.plot(lon, lat, "o", color="black", markersize=6, markeredgecolor="white")
        ax.annotate(f"{nom} ({code})", (lon, lat), xytext=(6, 6), textcoords="offset points",
                    fontsize=10, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8))

    # Légende : seulement les classes présentes dans la zone, de la plus fréquente à la plus rare
    valeurs, nombres = np.unique(donnees[donnees > 0], return_counts=True)
    ordre = valeurs[np.argsort(-nombres)]
    patches = [Patch(color=legende[v][2], label=f"{legende[v][0]} : {legende[v][1]}")
               for v in ordre if v in legende]
    ax.legend(handles=patches, loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9, frameon=False,
              title="Classes présentes")

    fig.tight_layout()
    fig.savefig(sortie, dpi=150, bbox_inches="tight")
    print(f"Carte enregistrée : {sortie}")
    if afficher:
        plt.show()


def main(argv=None):
    p = argparse.ArgumentParser(description="Afficher la carte Köppen-Geiger")
    p.add_argument("--tif", default="1991_2020/koppen_geiger_0p1.tif", help="fichier .tif de la carte")
    p.add_argument("--legende", default="legend.txt", help="legend.txt fourni avec les cartes")
    p.add_argument("--zone", nargs="+", default=["europe"],
                   help=f"{', '.join(ZONES)} ou 4 nombres : lon_min lon_max lat_min lat_max")
    p.add_argument("--lieux", nargs="*", default=[], help='lieux à placer, ex. "Paris, France"')
    p.add_argument("--sortie", default="carte_koppen.png")
    p.add_argument("--sans-fenetre", action="store_true", help="enregistrer le PNG sans ouvrir de fenêtre")
    a = p.parse_args(argv)

    if len(a.zone) == 1 and a.zone[0].lower() in ZONES:
        zone = ZONES[a.zone[0].lower()]
    elif len(a.zone) == 4:
        zone = tuple(float(x) for x in a.zone)
    else:
        raise SystemExit("--zone : un nom (" + ", ".join(ZONES) + ") ou 4 nombres.")
    dessiner(a.tif, a.legende, zone, a.lieux, a.sortie, afficher=not a.sans_fenetre)


if __name__ == "__main__":
    main()