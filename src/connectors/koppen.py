"""Classe climatique de Köppen-Geiger (facultative) — repris de `meteo_collecte.py`.

Demande les cartes à 1 km de Beck et al. (2023) (archive koppen_geiger_tif.zip sur figshare) et le paquet
`rasterio`. Emplacement : variables KOPPEN_TIF (carte 1991-2020) et KOPPEN_LEGENDE (legend.txt). Sans elles,
`classe_climatique` renvoie None et tout le reste fonctionne.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional


@lru_cache(maxsize=4)
def _legende(chemin: str) -> dict:
    out = {}
    for ligne in Path(chemin).read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^\s*(\d+)\s*[:=]?\s+([A-Z][A-Za-z]{0,2})\b\s*(.*?)\s*(\[.*\])?\s*$", ligne)
        if m:
            out[int(m.group(1))] = f"{m.group(2)} – {m.group(3)}".strip(" –")
    return out


def classe_climatique(lat: float, lon: float, tif: Optional[str] = None, legende: Optional[str] = None) -> Optional[dict]:
    tif = tif or os.environ.get("KOPPEN_TIF")
    legende = legende or os.environ.get("KOPPEN_LEGENDE")
    if not tif or not Path(tif).exists():
        return None
    try:
        import rasterio
    except ImportError:
        return None
    with rasterio.open(tif) as carte:
        code = int(next(carte.sample([(lon, lat)]))[0])
    libelle = _legende(legende).get(code) if legende and Path(legende).exists() else None
    return {"code": code, "classe": libelle.split(" – ")[0] if libelle else None, "libelle": libelle,
            "source": "Beck et al. (2023), Köppen-Geiger 1 km"}
