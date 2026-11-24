"""
base_meteo.py - Base de données interne de l'agent météo (SQLite)

Rassemble les résultats de l'analyse météo (dossier sorties/, produit par le notebook
meteo_supply_chain_v2.ipynb) dans une base SQLite unique, que le LLM interroge ensuite
en lecture seule :

    sorties/*.csv   ->   data/meteo.db

    python base_meteo.py                      # construit la base
    python base_meteo.py --sorties autre_dossier

Tables
------
- sites           : les sites surveillés (pays, rôle, indicateurs suivis, classe climatique)
- meteo_jour      : météo et indicateurs, une ligne par site et par jour
- indicateurs     : les 8 indicateurs de risque (variable, sens, unité, risque, performance)
- seuils          : seuil d'alerte de chaque indicateur pour chaque site
- alertes         : jours où un indicateur a dépassé son seuil (observé) ou va le dépasser (prévu)
- episodes_par_an : fréquence moyenne des épisodes par site et indicateur
- validation_cas  : test de la méthode sur les crises passées (Helene, Uri, Rhin, Thaïlande)
- informations    : date de construction, période couverte, dernière mise à jour

Attention : reconstruire la base repart des fichiers du notebook. Relancer ensuite
« python mise_a_jour.py » pour rattraper les jours manquants.

Ajouter une colonne ou une table : la décrire dans SCHEMA. Sa description est
automatiquement transmise au LLM (fonction decrire_schema).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

DOSSIER_SORTIES = Path(os.environ.get("METEO_SORTIES", "sorties"))
CHEMIN_BASE = Path(os.environ.get("METEO_BASE", "data/meteo.db"))
KOPPEN_TIF = Path(os.environ.get("KOPPEN_TIF", "1991_2020/koppen_geiger_0p1.tif"))
KOPPEN_LEGENDE = Path(os.environ.get("KOPPEN_LEGENDE", "legend.txt"))

# Noms Open-Meteo / notebook -> noms lisibles (par l'équipe comme par le LLM)
RENOMMAGE = {
    "temperature_2m_max": "temperature_max_c", "temperature_2m_min": "temperature_min_c",
    "precipitation_sum": "pluie_mm", "precipitation_hours": "heures_pluie", "snowfall_sum": "neige_cm",
    "wind_speed_10m_max": "vent_max_kmh", "wind_gusts_10m_max": "rafales_kmh",
    "weather_code": "code_temps_omm", "river_discharge": "debit_m3s",
    "pluie_3j": "pluie_3j_mm", "pluie_90j": "pluie_90j_mm", "temp_min_3j": "temp_min_3j_c",
    "debit_7j": "debit_7j_m3s",
}

# Les 8 indicateurs du notebook : colonne de meteo_jour, sens de l'extrême, unité
INDICATEURS = {
    "pluie_3j":    ("pluie_3j_mm", "haut", "mm"),
    "pluie_90j":   ("pluie_90j_mm", "haut", "mm"),
    "rafales":     ("rafales_kmh", "haut", "km/h"),
    "neige":       ("neige_cm", "haut", "cm"),
    "chaleur":     ("temperature_max_c", "haut", "°C"),
    "gel":         ("temp_min_3j_c", "bas", "°C"),
    "crue":        ("debit_7j_m3s", "haut", "m³/s"),
    "basses_eaux": ("debit_7j_m3s", "bas", "m³/s"),
}

# Description des tables et colonnes : c'est ce que le LLM lit pour écrire ses requêtes.
SCHEMA = {
    "sites": ("Sites surveillés (usines, ports, mines...).", {
        "site": "nom du site (clé utilisée dans toutes les tables)", "pays": "pays",
        "lat": "latitude (°)", "lon": "longitude (°)", "role": "rôle du site dans la chaîne d'approvisionnement",
        "fluvial": "1 si le site dépend d'un fleuve (débit suivi)",
        "indicateurs_suivis": "indicateurs de risque pertinents pour ce site (les seuls qui déclenchent des alertes)",
        "climat_classe": "classe climatique de Köppen-Geiger (ex. Cfb)", "climat_libelle": "classe climatique en clair",
        "lat_debit": "latitude du point de mesure du débit (fleuve principal)", "lon_debit": "longitude de ce point",
    }),
    "meteo_jour": ("Météo observée (réanalyse ERA5) et indicateurs, une ligne par site et par jour.", {
        "site": "nom du site", "date": "jour, texte AAAA-MM-JJ",
        "temperature_max_c": "température maximale du jour (°C)", "temperature_min_c": "température minimale du jour (°C)",
        "pluie_mm": "pluie du jour (mm)", "heures_pluie": "heures de pluie dans la journée",
        "neige_cm": "chute de neige du jour (cm)", "vent_max_kmh": "vent moyen maximal (km/h)",
        "rafales_kmh": "rafale maximale (km/h)", "code_temps_omm": "code du temps OMM (95-99 = orage)",
        "debit_m3s": "débit du fleuve (m³/s, GloFAS), vide si non fluvial",
        "pluie_3j_mm": "cumul de pluie sur 3 jours (mm)", "pluie_90j_mm": "cumul de pluie sur 90 jours (mm)",
        "temp_min_3j_c": "température minimale sur 3 jours (°C)", "debit_7j_m3s": "débit moyen sur 7 jours (m³/s)",
        "score_meteo": "score de risque météo du jour, de 0 à 1 (0,99 = parmi les 1 % de jours les plus extrêmes du site)",
        "alerte_meteo": "1 si au moins un indicateur suivi a dépassé son seuil ce jour-là",
        "source": "'ERA5' (observation définitive) ou 'prevision (provisoire)' pour les derniers jours, "
                  "remplacés par ERA5 dès qu'il est disponible (environ 6 jours de retard)",
    }),
    "indicateurs": ("Les indicateurs de risque et leur performance mesurée sur les crises passées.", {
        "indicateur": "identifiant (pluie_3j, pluie_90j, rafales, neige, chaleur, gel, crue, basses_eaux)",
        "variable": "colonne de meteo_jour utilisée", "sens": "'haut' = alerte au-dessus du seuil, 'bas' = en dessous",
        "unite": "unité", "risque": "conséquence pour la supply chain",
        "cas_testes": "nombre de crises passées où l'indicateur a été testé",
        "detecte_en_observation": "crises détectées avec les observations",
        "detecte_en_prevision": "crises détectées avec les prévisions",
        "meilleure_avance_j": "meilleure avance de détection (jours)",
        "episodes_par_an_et_site": "nombre moyen d'alertes par an et par site",
    }),
    "seuils": ("Seuil d'alerte de chaque indicateur pour chaque site (quantile 99 % ou 1 %, calculé sur 2010-2020).", {
        "site": "nom du site", "indicateur": "indicateur", "seuil": "valeur du seuil",
        "unite": "unité", "sens": "'haut' ou 'bas'",
    }),
    "alertes": ("Jours où un indicateur suivi dépasse le seuil du site. type = 'observation' (passé) "
                "ou 'prevision' (16 prochains jours, au moment de l'analyse).", {
        "site": "nom du site", "date": "jour AAAA-MM-JJ", "indicateur": "indicateur en alerte",
        "valeur": "valeur atteinte", "seuil": "seuil du site", "unite": "unité",
        "risque": "conséquence pour la supply chain", "type": "'observation' ou 'prevision'",
    }),
    "episodes_par_an": ("Nombre moyen d'épisodes d'alerte par an (un épisode = jours d'alerte consécutifs).", {
        "site": "nom du site", "indicateur": "indicateur", "episodes_par_an": "épisodes par an",
    }),
    "validation_cas": ("Test de la méthode sur des crises réelles : l'alerte serait-elle partie à temps ?", {
        "cas": "nom de la crise", "site": "site", "indicateur": "indicateur testé",
        "source": "observation (ERA5) ou prévision", "seuil": "seuil du site",
        "valeur_extreme": "valeur maximale (ou minimale) atteinte pendant la crise", "unite": "unité",
        "alerte_avant_perturbation": "1 si l'alerte est partie avant la perturbation",
        "debut_episode": "premier jour d'alerte", "jours_avance": "avance de l'alerte (jours)",
        "deja_au_debut_de_fenetre": "1 si l'épisode durait déjà (risque lent)",
    }),
    "informations": ("Métadonnées de la base.", {"cle": "nom", "valeur": "valeur"}),
}


def _lire(dossier: Path, nom: str, obligatoire: bool = True) -> pd.DataFrame | None:
    f = dossier / nom
    if not f.exists():
        if obligatoire:
            raise SystemExit(f"Fichier manquant : {f}. Exécutez d'abord le notebook meteo_supply_chain_v2.ipynb.")
        return None
    return pd.read_csv(f)


def _booleen(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1", "vrai"]).astype(int)


def _climat(sites: pd.DataFrame) -> pd.DataFrame:
    """Classe Köppen lue sur la carte de Beck et al. (si la carte et rasterio sont disponibles)."""
    sites["climat_classe"], sites["climat_libelle"] = None, None
    if not KOPPEN_TIF.exists():
        print(f"  (carte Köppen absente : {KOPPEN_TIF}, colonne climat laissée vide)")
        return sites
    try:
        from meteo_collecte import KOPPEN, _koppen_carte
        for i, s in sites.iterrows():
            r = _koppen_carte(s["lat"], s["lon"], str(KOPPEN_TIF), str(KOPPEN_LEGENDE))
            if r:
                sites.at[i, "climat_classe"] = r["classe"]
                sites.at[i, "climat_libelle"] = KOPPEN[r["classe"]][1]
    except ImportError as e:
        print(f"  (classe Köppen non calculée : {e})")
    return sites


def construire(sorties: Path = DOSSIER_SORTIES, chemin_base: Path = CHEMIN_BASE) -> dict:
    """Construit (ou reconstruit entièrement) la base SQLite à partir du dossier sorties/."""
    brut = _lire(sorties, "meteo_brut.csv")
    indic = _lire(sorties, "meteo_indicateurs_journaliers.csv")
    sites_csv = _lire(sorties, "meteo_sites.csv")
    seuils_csv = _lire(sorties, "meteo_seuils_par_site.csv")
    synthese = _lire(sorties, "meteo_synthese_indicateurs.csv", obligatoire=False)
    validation = _lire(sorties, "meteo_validation_cas.csv", obligatoire=False)
    par_an = _lire(sorties, "meteo_episodes_par_an.csv", obligatoire=False)
    prevues = _lire(sorties, "meteo_alertes_16_jours.csv", obligatoire=False)

    # --- sites
    sites = pd.DataFrame({
        "site": sites_csv["site"], "pays": sites_csv.get("pays"), "lat": sites_csv["lat"], "lon": sites_csv["lon"],
        "role": sites_csv.get("role"), "fluvial": _booleen(sites_csv.get("fluvial", pd.Series(False, index=sites_csv.index))),
        "indicateurs_suivis": sites_csv.get("indicateurs"),
        "lat_debit": sites_csv.get("lat_debit"), "lon_debit": sites_csv.get("lon_debit"),
    })
    sites = _climat(sites)
    suivis = {s: {i.strip() for i in str(t).split(",")} for s, t in zip(sites["site"], sites["indicateurs_suivis"])}

    # --- météo du jour + indicateurs
    meteo = brut.rename(columns=RENOMMAGE)
    colonnes_indic = ["site", "date", "pluie_3j", "pluie_90j", "temp_min_3j", "debit_7j", "score_meteo", "alerte_meteo"]
    ind = indic[[c for c in colonnes_indic if c in indic.columns]].rename(columns=RENOMMAGE)
    meteo = meteo.merge(ind, on=["site", "date"], how="left")
    meteo["date"] = pd.to_datetime(meteo["date"]).dt.strftime("%Y-%m-%d")
    if "alerte_meteo" in meteo:
        meteo["alerte_meteo"] = _booleen(meteo["alerte_meteo"])
    meteo["score_meteo"] = meteo["score_meteo"].round(3)
    meteo = meteo.sort_values(["site", "date"]).drop_duplicates(["site", "date"])
    meteo["source"] = "ERA5"

    # --- indicateurs et seuils
    indicateurs = pd.DataFrame([(k, v[0], v[1], v[2]) for k, v in INDICATEURS.items()],
                               columns=["indicateur", "variable", "sens", "unite"])
    if synthese is not None:
        indicateurs = indicateurs.merge(synthese.drop(columns="sites_suivis", errors="ignore"), on="indicateur", how="left")
    seuils = seuils_csv.dropna(subset=["seuil"]).merge(indicateurs[["indicateur", "unite", "sens"]], on="indicateur")
    seuils["seuil"] = seuils["seuil"].round(2)

    # --- alertes observées (format long) + prévues
    risque = dict(zip(indicateurs["indicateur"], indicateurs.get("risque", pd.Series(dtype=str))))
    morceaux = []
    for nom, (variable, _, unite) in INDICATEURS.items():
        col = f"alerte_{nom}"
        if col not in indic:
            continue
        jours = indic.loc[_booleen(indic[col]) == 1, ["site", "date"]]
        jours = jours[jours["site"].map(lambda s: nom in suivis.get(s, set()))]
        if jours.empty:
            continue
        jours = jours.assign(date=pd.to_datetime(jours["date"]).dt.strftime("%Y-%m-%d"), indicateur=nom)
        jours = jours.merge(meteo[["site", "date", variable]].rename(columns={variable: "valeur"}), on=["site", "date"])
        jours = jours.merge(seuils[["site", "indicateur", "seuil"]], on=["site", "indicateur"], how="left")
        morceaux.append(jours.assign(unite=unite, risque=risque.get(nom), type="observation"))
    if prevues is not None and len(prevues):
        p = prevues.copy()
        p["indicateur"] = p["indicateur"].replace({"pluie_3j_mm": "pluie_3j"})
        morceaux.append(p.assign(type="prevision"))
    alertes = pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame(columns=list(SCHEMA["alertes"][1]))
    alertes = alertes[list(SCHEMA["alertes"][1])].sort_values(["date", "site"])
    alertes["valeur"] = pd.to_numeric(alertes["valeur"], errors="coerce").round(2)

    # --- tables de résultats du notebook
    if par_an is not None:
        par_an = (par_an.drop(columns="total_par_site", errors="ignore")
                  .melt(id_vars="site", var_name="indicateur", value_name="episodes_par_an")
                  .dropna().round({"episodes_par_an": 2}))
    if validation is not None:
        for c in ("alerte_avant_perturbation", "deja_au_debut_de_fenetre"):
            if c in validation:
                validation[c] = _booleen(validation[c])

    infos = pd.DataFrame({"cle": ["construite_le", "premier_jour", "dernier_jour", "nb_sites", "source", "methode"],
                          "valeur": [datetime.now().isoformat(timespec="seconds"), meteo["date"].min(),
                                     meteo["date"].max(), str(len(sites)), "Open-Meteo (ERA5, GloFAS, prévisions)",
                                     "seuils propres à chaque site, quantile 99 % (1 % pour gel et basses eaux) sur 2010-2020"]})

    tables = {"sites": sites, "meteo_jour": meteo, "indicateurs": indicateurs, "seuils": seuils,
              "alertes": alertes, "episodes_par_an": par_an, "validation_cas": validation, "informations": infos}
    chemin_base = Path(chemin_base)
    chemin_base.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin_base.with_suffix(".tmp")
    temporaire.unlink(missing_ok=True)
    # closing() ferme vraiment la connexion : sous Windows, un fichier encore ouvert ne peut pas être renommé
    with closing(sqlite3.connect(temporaire)) as cx:
        for nom, df in tables.items():
            if df is not None:
                df.to_sql(nom, cx, index=False)
        cx.execute("CREATE INDEX idx_meteo_site_date ON meteo_jour(site, date)")
        cx.execute("CREATE INDEX idx_alertes_site_date ON alertes(site, date)")
        cx.commit()
    temporaire.replace(chemin_base)      # remplacement d'un coup : la base n'est jamais à moitié écrite
    return {"base": str(chemin_base), "sites": len(sites), "jours": len(meteo), "alertes": len(alertes),
            "periode": f"{meteo['date'].min()} -> {meteo['date'].max()}"}


def uri_lecture_seule(chemin: Path) -> str:
    """Adresse SQLite en lecture seule ; les accents du chemin (ex. ingé-3) sont encodés."""
    return "file:" + quote(Path(chemin).resolve().as_posix(), safe="/:") + "?mode=ro"


def decrire_schema(chemin_base: Path = CHEMIN_BASE) -> str:
    """Description textuelle de la base (tables, colonnes présentes, sens), destinée au LLM."""
    chemin_base = Path(chemin_base)
    if not chemin_base.exists():
        raise FileNotFoundError(f"Base absente ({chemin_base}) : lancez « python base_meteo.py ».")
    lignes = []
    with closing(sqlite3.connect(uri_lecture_seule(chemin_base), uri=True)) as cx:
        for table, (description, colonnes) in SCHEMA.items():
            presentes = [r[1] for r in cx.execute(f"PRAGMA table_info({table})")]
            if not presentes:
                continue
            lignes.append(f"Table {table} : {description}")
            lignes += [f"  - {c} : {colonnes.get(c, '(pas de description)')}" for c in presentes]
        infos = dict(cx.execute("SELECT cle, valeur FROM informations").fetchall())
        sites = cx.execute("SELECT site, pays, role FROM sites ORDER BY site").fetchall()
    lignes.append(f"Période couverte : {infos.get('premier_jour')} au {infos.get('dernier_jour')}.")
    lignes.append("Sites : " + " ; ".join(f"{s} ({p}, {r})" for s, p, r in sites) + ".")
    return "\n".join(lignes)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Construire la base SQLite de l'agent météo")
    p.add_argument("--sorties", default=str(DOSSIER_SORTIES), help="dossier des résultats du notebook")
    p.add_argument("--base", default=str(CHEMIN_BASE), help="chemin de la base à créer")
    a = p.parse_args()
    print("Base construite :", construire(Path(a.sorties), Path(a.base)))
