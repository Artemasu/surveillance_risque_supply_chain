"""
base_meteo.py - Base de données interne de l'agent météo (SQLite)

Transforme les fichiers produits par la collecte en une base SQLite unique, que
le LLM interroge ensuite (en lecture seule) :
    data/meteo_historique.csv  +  data/sites_resolus.csv   ->   data/meteo.db

    python meteo_collecte.py collecter --sites mes_sites.csv   # 1. collecte
    python base_meteo.py                                       # 2. construction de la base

Tables
------
- sites       : un site par ligne (coordonnées, classe climatique)
- meteo_jour  : une ligne par site et par jour (températures, pluie, vent, débit...)
- seuils      : seuils propres à chaque site (inhabituel = 10 % des jours les plus
                extrêmes, exceptionnel = 1 %), calculés sur l'historique de la base
- informations: date de construction, période couverte

Pour ajouter une colonne ou une table : la déclarer dans SCHEMA ci-dessous. Sa
description est automatiquement transmise au LLM (fonction decrire_schema).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DOSSIER_DONNEES = Path(os.environ.get("meteo", "data"))
CHEMIN_BASE = DOSSIER_DONNEES / "meteo.db"

# Noms Open-Meteo -> noms lisibles (par l'équipe comme par le LLM)
RENOMMAGE = {
    "temperature_2m_max": "temperature_max_c",
    "temperature_2m_min": "temperature_min_c",
    "precipitation_sum": "pluie_mm",
    "precipitation_hours": "heures_pluie",
    "snowfall_sum": "neige_cm",
    "wind_speed_10m_max": "vent_max_kmh",
    "wind_gusts_10m_max": "rafales_kmh",
    "weather_code": "code_temps_omm",
    "river_discharge": "debit_m3s",
}

# Description de chaque table et colonne : c'est ce que le LLM lit pour écrire ses requêtes.
SCHEMA = {
    "sites": ("Sites surveillés (usines, entrepôts, ports, fournisseurs).", {
        "nom": "nom du site (clé, utilisée dans les autres tables)",
        "lat": "latitude en degrés", "lon": "longitude en degrés",
        "climat_classe": "classe climatique de Köppen-Geiger, ex. Cfb",
        "climat_libelle": "classe climatique en clair",
        "climat_methode": "'carte' (carte Beck et al. 2023) ou 'calcul' (normales 1991-2020)",
        "fluvial": "1 si le site dépend d'un fleuve (débit suivi), sinon 0",
    }),
    "meteo_jour": ("Météo observée, une ligne par site et par jour (réanalyse ERA5, Open-Meteo).", {
        "site": "nom du site (voir sites.nom)", "date": "jour, texte AAAA-MM-JJ",
        "temperature_max_c": "température maximale du jour (°C, l'après-midi)",
        "temperature_min_c": "température minimale du jour (°C, la nuit)",
        "pluie_mm": "cumul de pluie du jour (mm)",
        "pluie_3j_mm": "cumul de pluie sur 3 jours, jour inclus (mm) : bon indicateur d'inondation",
        "heures_pluie": "nombre d'heures de pluie dans la journée",
        "neige_cm": "chute de neige du jour (cm)",
        "vent_max_kmh": "vent moyen maximal (km/h)",
        "rafales_kmh": "rafale maximale (km/h) : tempêtes",
        "code_temps_omm": "code du temps de l'OMM (0 = ciel clair, 61-65 pluie, 71-77 neige, 95-99 orage)",
        "debit_m3s": "débit du fleuve le plus proche (m³/s, GloFAS), vide si le site n'est pas fluvial",
    }),
    "seuils": ("Seuils propres à chaque site, calculés sur tout l'historique de la base. "
               "Un jour est 'inhabituel' s'il dépasse seuil_inhabituel, 'exceptionnel' s'il dépasse "
               "seuil_exceptionnel (dans le sens indiqué).", {
        "site": "nom du site", "variable": "colonne de meteo_jour concernée",
        "sens": "'haut' (on surveille les valeurs fortes) ou 'bas' (valeurs faibles : gel, basses eaux)",
        "seuil_inhabituel": "valeur atteinte 10 % des jours (9 jours sur 10 sont moins extrêmes)",
        "seuil_exceptionnel": "valeur atteinte 1 % des jours (99 jours sur 100 sont moins extrêmes)",
        "nb_jours": "nombre de jours utilisés pour le calcul",
    }),
    "informations": ("Métadonnées de la base.", {"cle": "nom de l'information", "valeur": "valeur"}),
}

# Variables pour lesquelles on calcule des seuils, et le sens de l'extrême
VARIABLES_SEUILS = {
    "pluie_mm": "haut", "pluie_3j_mm": "haut", "rafales_kmh": "haut", "neige_cm": "haut",
    "temperature_max_c": "haut", "temperature_min_c": "bas", "debit_m3s": "haut",
}


def _seuils(meteo: pd.DataFrame) -> pd.DataFrame:
    lignes = []
    for site, d in meteo.groupby("site"):
        for variable, sens in VARIABLES_SEUILS.items():
            if variable not in d:
                continue
            serie = d[variable].dropna()
            if variable in ("pluie_mm", "pluie_3j_mm", "neige_cm"):
                serie = serie[serie > 0]          # les jours secs ne disent rien des fortes pluies
            if len(serie) < 100:
                continue
            q = (0.90, 0.99) if sens == "haut" else (0.10, 0.01)
            lignes.append({"site": site, "variable": variable, "sens": sens,
                           "seuil_inhabituel": round(float(serie.quantile(q[0])), 2),
                           "seuil_exceptionnel": round(float(serie.quantile(q[1])), 2),
                           "nb_jours": int(len(serie))})
    # basses eaux : on surveille aussi le débit faible
    for site, d in meteo.groupby("site"):
        if "debit_m3s" in d and d["debit_m3s"].notna().sum() >= 100:
            s = d["debit_m3s"].dropna()
            lignes.append({"site": site, "variable": "debit_m3s", "sens": "bas",
                           "seuil_inhabituel": round(float(s.quantile(0.10)), 2),
                           "seuil_exceptionnel": round(float(s.quantile(0.01)), 2), "nb_jours": int(len(s))})
    return pd.DataFrame(lignes)


def construire(dossier: Path = DOSSIER_DONNEES, chemin_base: Path | None = None) -> dict:
    """Construit (ou reconstruit entièrement) la base SQLite à partir des fichiers de la collecte."""
    chemin_base = Path(chemin_base or dossier / "meteo.db")
    fichier_meteo, fichier_sites = dossier / "meteo_historique.csv", dossier / "sites_resolus.csv"
    for f in (fichier_meteo, fichier_sites):
        if not f.exists():
            raise SystemExit(f"Fichier manquant : {f}. Lancez d'abord : python meteo_collecte.py collecter --sites ...")

    meteo = pd.read_csv(fichier_meteo).rename(columns=RENOMMAGE)
    meteo["date"] = pd.to_datetime(meteo["date"]).dt.strftime("%Y-%m-%d")
    meteo = meteo.sort_values(["site", "date"]).drop_duplicates(["site", "date"], keep="last")
    meteo.insert(meteo.columns.get_loc("pluie_mm") + 1, "pluie_3j_mm",
                 meteo.groupby("site")["pluie_mm"].transform(lambda s: s.rolling(3, min_periods=3).sum()).round(2))
    if "debit_m3s" in meteo and meteo["debit_m3s"].isna().all():
        meteo = meteo.drop(columns="debit_m3s")

    brut = pd.read_csv(fichier_sites)
    climat = brut.get("climat", pd.Series(dtype=str)).fillna("").astype(str)
    valide = ~climat.str.startswith(("✗", "-")) & climat.str.contains(" : ")
    sites = pd.DataFrame({
        "nom": brut["nom"], "lat": brut["lat"], "lon": brut["lon"],
        "climat_classe": climat.str.split(" : ").str[0].where(valide),
        "climat_libelle": climat.str.split(" : ", n=1).str[1].where(valide),
        "climat_methode": brut.get("climat_methode"),
        "fluvial": brut.get("debit", pd.Series("-", index=brut.index)).astype(str).ne("-").astype(int),
    })
    seuils = _seuils(meteo)
    infos = pd.DataFrame({"cle": ["construite_le", "premier_jour", "dernier_jour", "nb_sites", "source"],
                          "valeur": [datetime.now().isoformat(timespec="seconds"), meteo["date"].min(),
                                     meteo["date"].max(), str(len(sites)), "Open-Meteo (ERA5, GloFAS)"]})

    chemin_base.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin_base.with_suffix(".tmp")
    temporaire.unlink(missing_ok=True)
    with sqlite3.connect(temporaire) as cx:
        sites.to_sql("sites", cx, index=False)
        meteo.to_sql("meteo_jour", cx, index=False)
        seuils.to_sql("seuils", cx, index=False)
        infos.to_sql("informations", cx, index=False)
        cx.execute("CREATE INDEX idx_meteo_site_date ON meteo_jour(site, date)")
        cx.execute("CREATE INDEX idx_meteo_date ON meteo_jour(date)")
    temporaire.replace(chemin_base)       # remplacement d'un coup : la base n'est jamais à moitié écrite
    return {"base": str(chemin_base), "sites": len(sites), "jours": len(meteo), "seuils": len(seuils),
            "periode": f"{infos.valeur[1]} -> {infos.valeur[2]}"}


def decrire_schema(chemin_base: Path = CHEMIN_BASE) -> str:
    """Description textuelle de la base (tables, colonnes présentes, sens), destinée au LLM."""
    lignes = []
    with sqlite3.connect(f"file:{Path(chemin_base).as_posix()}?mode=ro", uri=True) as cx:
        for table, (description, colonnes) in SCHEMA.items():
            presentes = [r[1] for r in cx.execute(f"PRAGMA table_info({table})")]
            if not presentes:
                continue
            lignes.append(f"Table {table} : {description}")
            for c in presentes:
                lignes.append(f"  - {c} : {colonnes.get(c, '(pas de description)')}")
        infos = dict(cx.execute("SELECT cle, valeur FROM informations").fetchall())
        noms = [r[0] for r in cx.execute("SELECT nom FROM sites ORDER BY nom")]
    lignes.append(f"Période couverte : {infos.get('premier_jour')} au {infos.get('dernier_jour')}.")
    lignes.append(f"Sites : {', '.join(noms)}.")
    return "\n".join(lignes)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Construire la base SQLite de l'agent météo")
    p.add_argument("--dossier", default=str(DOSSIER_DONNEES), help="dossier des fichiers de la collecte")
    a = p.parse_args()
    resume = construire(Path(a.dossier))
    print("Base construite :", resume)
