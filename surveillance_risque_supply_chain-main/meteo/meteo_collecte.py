"""
meteo_collecte.py — Collecte des données météo et climatiques (Projet 6, agent météo)

Module général, sans site codé en dur : on lui donne un lieu (par son nom ou ses
coordonnées), une date, ou un fichier CSV de sites. Toutes les données viennent
d'Open-Meteo (gratuit pour un usage non commercial, sans clé) et sont mises en
cache dans data/cache/ : une même requête n'est jamais envoyée deux fois.

Trois usages en ligne de commande
---------------------------------
1. Vérifier que la collecte fonctionne (à lancer en premier) :
       python meteo_collecte.py verifier --lieu "Paris, France"
       python meteo_collecte.py verifier --lat 48.857 --lon 2.352

2. Obtenir le contexte météo d'un lieu à une date (format JSON commun des agents) :
       python meteo_collecte.py contexte --lieu "Paris, France" --date 2026-11-11

3. Collecter l'historique d'une liste de sites :
       python meteo_collecte.py collecter --sites mes_sites.csv
   Le CSV doit avoir une colonne `nom` ; `lat`, `lon` et `fluvial` (vrai/faux)
   sont facultatives : sans coordonnées, le nom est géocodé.

Utilisation depuis Python (notebook ou autre agent)
---------------------------------------------------
       from meteo_collecte import contexte_meteo, historique, classe_climatique
       contexte_meteo(lieu="Paris, France", date_cible="2026-11-11")

Couche climatique (facultative)
-------------------------------
La classe climatique de Köppen-Geiger demande les cartes de Beck et al. (2023),
à télécharger une fois (archive koppen_geiger_tif.zip sur figshare), et le paquet
`rasterio`. Indiquer leur emplacement avec les variables d'environnement
KOPPEN_TIF (fichier .tif de la période 1991-2020) et KOPPEN_LEGENDE (legend.txt),
ou avec les options --koppen-tif et --koppen-legende. Sans elles, tout le reste
fonctionne et le champ « climat » est signalé comme manquant.

Dépendances : pip install pandas numpy requests   (+ rasterio pour Köppen)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# --------------------------------------------------------------------------- configuration
URL_GEOCODAGE = "https://geocoding-api.open-meteo.com/v1/search"
URL_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
URL_PREVISION = "https://api.open-meteo.com/v1/forecast"
URL_DEBIT = "https://flood-api.open-meteo.com/v1/flood"

DOSSIER_DONNEES = Path(os.environ.get("METEO_DATA", "data"))
DOSSIER_CACHE = DOSSIER_DONNEES / "cache"

VARIABLES_JOUR = [
    "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "precipitation_hours",
    "snowfall_sum", "wind_speed_10m_max", "wind_gusts_10m_max", "weather_code",
]
# Période de référence climatique : les normales officielles de l'OMM (1991-2020)
REFERENCE = ("1991-01-01", "2020-12-31")
FENETRE_SAISON = 15        # jours autour de la date pour comparer à la même saison
RETARD_ERA5 = 6            # jours : en deçà, on prend la prévision plutôt que l'archive
HORIZON_PREVISION = 15     # jours après aujourd'hui couverts par la prévision
DEBIT_MIN_PLAUSIBLE = 20   # m³/s : en dessous, on a sans doute un ruisseau, pas un fleuve

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "projet6-agent-meteo"


class ErreurMeteo(RuntimeError):
    """Erreur de collecte, avec un message lisible."""


# --------------------------------------------------------------------------- accès API + cache
def appel_api(url: str, params: dict, pause: float = 0.5, essais: int = 4) -> dict:
    """Requête GET JSON avec cache disque et nouvelles tentatives en cas de limite de débit."""
    DOSSIER_CACHE.mkdir(parents=True, exist_ok=True)
    cle = hashlib.md5((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    fichier = DOSSIER_CACHE / f"{cle}.json"
    if fichier.exists():
        return json.loads(fichier.read_text())
    for essai in range(essais):
        try:
            reponse = _SESSION.get(url, params=params, timeout=90)
        except requests.RequestException as e:
            raise ErreurMeteo(f"Réseau injoignable ({url.split('/')[2]}) : {e}") from e
        if reponse.status_code == 429:
            time.sleep(15 * (essai + 1))
            continue
        try:
            data = reponse.json()
        except ValueError:
            raise ErreurMeteo(f"Réponse illisible ({reponse.status_code}) : {reponse.text[:200]}")
        if reponse.status_code != 200 or (isinstance(data, dict) and data.get("error")):
            raison = data.get("reason", data) if isinstance(data, dict) else data
            raise ErreurMeteo(f"Erreur API ({reponse.status_code}) : {raison}")
        fichier.write_text(json.dumps(data))
        time.sleep(pause)
        return data
    raise ErreurMeteo("Limite de requêtes atteinte : réessayer dans quelques minutes.")


def _vers_dataframe(data: dict, bloc: str = "daily") -> pd.DataFrame:
    if bloc not in data:
        raise ErreurMeteo(f"Réponse sans bloc « {bloc} ».")
    df = pd.DataFrame(data[bloc])
    df["time"] = pd.to_datetime(df["time"])
    return df.rename(columns={"time": "date"})


def _date(d) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    return pd.Timestamp(d).date()


# --------------------------------------------------------------------------- lieux
def geocoder(nom: str, pays: str | None = None) -> dict:
    """Nom de lieu → coordonnées (meilleure correspondance). Ex. : geocoder("Paris, France")."""
    params = {"name": nom, "count": 1, "language": "fr", "format": "json"}
    if pays:
        params["countryCode"] = pays
    resultats = appel_api(URL_GEOCODAGE, params, pause=0.2).get("results") or []
    if not resultats:
        raise ErreurMeteo(f"Lieu introuvable : « {nom} ».")
    r = resultats[0]
    return {"nom": r.get("name", nom), "lat": r["latitude"], "lon": r["longitude"],
            "pays": r.get("country"), "code_pays": r.get("country_code"),
            "fuseau": r.get("timezone"), "altitude_m": r.get("elevation")}


def resoudre_lieu(lieu: str | None = None, lat: float | None = None, lon: float | None = None) -> dict:
    if lat is not None and lon is not None:
        return {"nom": lieu or f"{lat:.3f}, {lon:.3f}", "lat": float(lat), "lon": float(lon)}
    if lieu:
        return geocoder(lieu)
    raise ErreurMeteo("Indiquer un lieu (--lieu) ou des coordonnées (--lat et --lon).")


# --------------------------------------------------------------------------- collecte brute
def historique(lat: float, lon: float, debut, fin, variables=VARIABLES_JOUR) -> pd.DataFrame:
    """Météo quotidienne observée (réanalyse ERA5), de debut à fin inclus."""
    params = dict(latitude=lat, longitude=lon, start_date=str(_date(debut)), end_date=str(_date(fin)),
                  daily=",".join(variables), timezone="auto")
    return _vers_dataframe(appel_api(URL_ARCHIVE, params))


def prevision(lat: float, lon: float, debut=None, fin=None, jours: int = 16, variables=VARIABLES_JOUR) -> pd.DataFrame:
    """Prévision quotidienne : soit les `jours` prochains jours, soit la période debut → fin."""
    params = dict(latitude=lat, longitude=lon, daily=",".join(variables), timezone="auto")
    if debut is not None:
        params.update(start_date=str(_date(debut)), end_date=str(_date(fin or debut)))
    else:
        params["forecast_days"] = jours
    return _vers_dataframe(appel_api(URL_PREVISION, params))


def debit(lat: float, lon: float, debut, fin) -> pd.DataFrame:
    """Débit quotidien de la rivière (GloFAS), en m³/s, au point donné."""
    params = dict(latitude=lat, longitude=lon, start_date=str(_date(debut)), end_date=str(_date(fin)),
                  daily="river_discharge")
    return _vers_dataframe(appel_api(URL_DEBIT, params))


def trouver_fleuve(lat: float, lon: float, rayon: float = 0.1, pas: float = 0.05) -> dict:
    """Cherche autour du point la cellule au plus fort débit médian (le fleuve principal)."""
    decalages = np.arange(-rayon, rayon + 1e-9, pas)
    meilleur = {"lat_debit": lat, "lon_debit": lon, "debit_median": np.nan}
    for dlat in decalages:
        for dlon in decalages:
            la, lo = round(lat + dlat, 3), round(lon + dlon, 3)
            try:
                med = debit(la, lo, "2015-01-01", "2016-12-31")["river_discharge"].median()
            except ErreurMeteo:
                continue
            if pd.notna(med) and not (med <= meilleur["debit_median"]):
                meilleur = {"lat_debit": la, "lon_debit": lo, "debit_median": float(med)}
    meilleur["plausible"] = bool(meilleur["debit_median"] >= DEBIT_MIN_PLAUSIBLE)
    return meilleur


# --------------------------------------------------------------------------- couche climatique
def climatologie(lat: float, lon: float, reference=REFERENCE) -> pd.DataFrame:
    """Météo quotidienne de la période de référence (1991-2020), pour situer un jour par rapport à la normale."""
    df = historique(lat, lon, reference[0], reference[1],
                    variables=["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                               "wind_gusts_10m_max"])
    df["pluie_3j"] = df["precipitation_sum"].rolling(3, min_periods=3).sum()
    return df


def _meme_saison(clim: pd.DataFrame, jour: date, fenetre: int = FENETRE_SAISON) -> pd.DataFrame:
    doy = pd.Timestamp(jour).dayofyear
    ecart = (clim["date"].dt.dayofyear - doy).abs()
    ecart = np.minimum(ecart, 366 - ecart)
    return clim[ecart <= fenetre]


# Comment juger chaque valeur : colonne de la climatologie, sens de l'extrême, comparaison saisonnière
CRITERES = {
    "pluie_3j_mm":       ("pluie_3j", "haut", False),
    "rafales_kmh":       ("wind_gusts_10m_max", "haut", False),
    "temperature_max_c": ("temperature_2m_max", "haut", True),
    "temperature_min_c": ("temperature_2m_min", "bas", True),
}


def situer(valeur: float, reference: pd.Series, sens: str) -> dict:
    """Rang d'une valeur dans sa référence : 0,99 = parmi les 1 % de jours les plus extrêmes."""
    ref = np.sort(reference.dropna().to_numpy())
    if valeur is None or pd.isna(valeur) or len(ref) < 100:
        return {"rang": None, "niveau": "inconnu", "normale": None}
    if sens == "haut":
        rang = np.searchsorted(ref, valeur, side="left") / len(ref)
    else:
        rang = 1 - np.searchsorted(ref, valeur, side="right") / len(ref)
    niveau = "exceptionnel" if rang >= 0.99 else "inhabituel" if rang >= 0.90 else "normal"
    return {"rang": round(float(rang), 3), "niveau": niveau, "normale": round(float(np.median(ref)), 1)}


def _lire_legende(chemin: str) -> dict:
    """Lit le legend.txt des cartes Köppen-Geiger (format « 1: Af Tropical, rainforest [0 0 255] »)."""
    legende = {}
    for ligne in Path(chemin).read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^\s*(\d+)\s*[:=]?\s+([A-Z][A-Za-z]{0,2})\b\s*(.*?)\s*(\[.*\])?\s*$", ligne)
        if m:
            legende[int(m.group(1))] = f"{m.group(2)} – {m.group(3)}".strip(" –")
    return legende


def classe_climatique(lat: float, lon: float, tif: str | None = None, legende: str | None = None) -> dict | None:
    """Classe climatique de Köppen-Geiger au point donné, ou None si les cartes ne sont pas configurées."""
    tif = tif or os.environ.get("KOPPEN_TIF")
    legende = legende or os.environ.get("KOPPEN_LEGENDE")
    if not tif or not Path(tif).exists():
        return None
    try:
        import rasterio
    except ImportError as e:
        raise ErreurMeteo("La couche climatique demande rasterio : pip install rasterio") from e
    with rasterio.open(tif) as carte:
        code = int(next(carte.sample([(lon, lat)]))[0])
    noms = _lire_legende(legende) if legende and Path(legende).exists() else {}
    libelle = noms.get(code)
    return {"code": code, "classe": libelle.split(" – ")[0] if libelle else None,
            "libelle": libelle, "source": "Beck et al. (2023), Köppen-Geiger 1 km"}


# --------------------------------------------------------------------------- l'outil de l'agent météo
def contexte_meteo(lieu: str | None = None, date_cible=None, lat: float | None = None, lon: float | None = None,
                   koppen_tif: str | None = None, koppen_legende: str | None = None) -> dict:
    """
    Contexte météo d'un lieu à une date, au format JSON commun des agents.
    - date passée (plus de 6 jours) : observation ERA5 ;
    - date récente ou dans les 15 prochains jours : prévision ;
    chaque valeur est située par rapport aux normales 1991-2020 du lieu, à la même saison.
    """
    jour = _date(date_cible) if date_cible is not None else _today()
    sortie = {"date": str(jour), "location": None, "weather": None, "donnees_manquantes": []}
    loc = resoudre_lieu(lieu, lat, lon)
    sortie["location"] = {k: loc.get(k) for k in ("nom", "lat", "lon", "pays", "fuseau")}

    aujourd_hui = _today()
    if jour <= aujourd_hui - timedelta(days=RETARD_ERA5):
        df, source, api = historique(loc["lat"], loc["lon"], jour - timedelta(days=2), jour), "observation (ERA5)", "archive"
    elif jour <= aujourd_hui + timedelta(days=HORIZON_PREVISION):
        df, source, api = prevision(loc["lat"], loc["lon"], jour - timedelta(days=2), jour), "prévision", "forecast"
    else:
        raise ErreurMeteo(f"Date trop lointaine : la prévision s'arrête au {aujourd_hui + timedelta(days=HORIZON_PREVISION)}.")

    df = df.sort_values("date")
    ligne = df[df["date"].dt.date == jour]
    if ligne.empty:
        sortie["donnees_manquantes"].append("weather")
        return sortie
    l = ligne.iloc[0]
    valeur = lambda c: None if c not in l or pd.isna(l[c]) else round(float(l[c]), 1)
    pluie_3j = df["precipitation_sum"].sum(min_count=3) if len(df) == 3 else np.nan
    valeurs = {
        "temperature_max_c": valeur("temperature_2m_max"), "temperature_min_c": valeur("temperature_2m_min"),
        "pluie_mm": valeur("precipitation_sum"), "pluie_3j_mm": None if pd.isna(pluie_3j) else round(float(pluie_3j), 1),
        "neige_cm": valeur("snowfall_sum"), "rafales_kmh": valeur("wind_gusts_10m_max"),
        "vent_max_kmh": valeur("wind_speed_10m_max"), "code_temps_omm": valeur("weather_code"),
    }

    contexte = {}
    try:
        clim = climatologie(loc["lat"], loc["lon"])
        saison = _meme_saison(clim, jour)
        for nom, (col, sens, saisonnier) in CRITERES.items():
            ref = saison[col] if saisonnier else clim[col]
            contexte[nom] = situer(valeurs[nom], ref, sens)
    except ErreurMeteo:
        sortie["donnees_manquantes"].append("normales_climatiques")

    try:
        climat = classe_climatique(loc["lat"], loc["lon"], koppen_tif, koppen_legende)
    except ErreurMeteo:
        climat = None
    if climat is None:
        sortie["donnees_manquantes"].append("climat_koppen")

    sortie["weather"] = {
        "source": source,
        "source_id": f"openmeteo:{api}:{loc['lat']:.3f},{loc['lon']:.3f}:{jour}",
        "valeurs": valeurs,
        "par_rapport_aux_normales_1991_2020": contexte,
        "climat": climat,
    }
    return sortie


def _today() -> date:
    return date.today()


# --------------------------------------------------------------------------- collecte en lot
def lire_sites(chemin: str) -> pd.DataFrame:
    sites = pd.read_csv(chemin)
    if "nom" not in sites.columns:
        raise ErreurMeteo("Le fichier de sites doit avoir une colonne « nom ».")
    for col in ("lat", "lon"):
        if col not in sites.columns:
            sites[col] = np.nan
    if "fluvial" not in sites.columns:
        sites["fluvial"] = False
    sites["fluvial"] = sites["fluvial"].astype(str).str.lower().isin(["1", "true", "vrai", "oui", "yes"])
    manquants = sites["lat"].isna() | sites["lon"].isna()
    for i in sites.index[manquants]:
        g = geocoder(sites.at[i, "nom"])
        sites.at[i, "lat"], sites.at[i, "lon"] = g["lat"], g["lon"]
    return sites


def collecter(chemin_sites: str, debut: str = "2010-01-01", fin: str | None = None,
              koppen_tif: str | None = None, koppen_legende: str | None = None) -> dict:
    """Historique météo (et débit pour les sites fluviaux) de chaque site, enregistré dans data/."""
    fin = fin or str(_today() - timedelta(days=RETARD_ERA5 + 1))
    sites = lire_sites(chemin_sites)
    tables, bilan = [], []
    for s in sites.itertuples():
        info = {"nom": s.nom, "lat": s.lat, "lon": s.lon, "meteo": "✗", "debit": "–", "climat": "–"}
        try:
            df = historique(s.lat, s.lon, debut, fin)
            df.insert(0, "site", s.nom)
            if s.fluvial:
                point = trouver_fleuve(s.lat, s.lon)
                info.update(point)
                d = debit(point["lat_debit"], point["lon_debit"], debut, fin)
                df = df.merge(d, on="date", how="left")
                info["debit"] = "✓" if point["plausible"] else "⚠ débit faible"
            tables.append(df)
            info["meteo"] = "✓"
        except ErreurMeteo as e:
            info["erreur"] = str(e)
        try:
            climat = classe_climatique(s.lat, s.lon, koppen_tif, koppen_legende)
            if climat:
                info["climat"] = climat["libelle"] or climat["code"]
        except ErreurMeteo as e:
            info["climat"] = f"✗ ({e})"
        bilan.append(info)
        print(f"  {s.nom:<25} météo {info['meteo']}  débit {info['debit']}  climat {info['climat']}")

    DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
    if tables:
        pd.concat(tables, ignore_index=True).to_csv(DOSSIER_DONNEES / "meteo_historique.csv", index=False)
    pd.DataFrame(bilan).to_csv(DOSSIER_DONNEES / "sites_resolus.csv", index=False)
    return {"sites": len(sites), "reussis": len(tables), "fichiers": ["meteo_historique.csv", "sites_resolus.csv"]}


# --------------------------------------------------------------------------- vérification
def verifier(lieu: str | None = None, lat: float | None = None, lon: float | None = None,
             koppen_tif: str | None = None, koppen_legende: str | None = None) -> pd.DataFrame:
    """Teste chaque maillon de la collecte sur un lieu et renvoie un tableau de bilan."""
    lignes = []

    def etape(nom, fonction, obligatoire=True, resume=None):
        t0 = time.perf_counter()
        try:
            res = fonction()
            ms = round(1000 * (time.perf_counter() - t0))
            if isinstance(res, pd.DataFrame):
                valeurs = res.drop(columns="date", errors="ignore")
                manque = round(100 * valeurs.isna().mean().mean(), 1) if len(res) else 100.0
                ok = len(res) > 0 and manque < 50
                lignes.append(dict(etape=nom, statut="✓" if ok else "⚠", lignes=len(res),
                                   manquant_pct=manque, duree_ms=ms, detail="", obligatoire=obligatoire))
            else:
                texte = (resume(res) if resume else str(res)) if res else "non configuré"
                lignes.append(dict(etape=nom, statut="✓" if res else "–", lignes=None, manquant_pct=None,
                                   duree_ms=ms, detail=texte[:90], obligatoire=obligatoire))
            return res
        except Exception as e:  # on veut un bilan complet même si une étape échoue
            lignes.append(dict(etape=nom, statut="✗", lignes=None, manquant_pct=None,
                               duree_ms=round(1000 * (time.perf_counter() - t0)), detail=str(e)[:120],
                               obligatoire=obligatoire))
            return None

    loc = etape("Lieu (géocodage)" if lat is None else "Lieu (coordonnées)",
                lambda: resoudre_lieu(lieu, lat, lon),
                resume=lambda r: f"{r['nom']} ({r['lat']:.3f}, {r['lon']:.3f})")
    if loc:
        la, lo = loc["lat"], loc["lon"]
        fin = _today() - timedelta(days=RETARD_ERA5 + 1)
        etape("Historique ERA5 (30 derniers jours)", lambda: historique(la, lo, fin - timedelta(days=29), fin))
        etape("Prévision (16 jours)", lambda: prevision(la, lo, jours=16))
        etape("Débit de rivière (30 jours)", lambda: debit(la, lo, fin - timedelta(days=29), fin), obligatoire=False)
        etape("Normales 1991-2020", lambda: climatologie(la, lo))
        etape("Classe climatique Köppen", lambda: classe_climatique(la, lo, koppen_tif, koppen_legende),
              obligatoire=False, resume=lambda r: r["libelle"] or f"code {r['code']}")
        etape("Outil contexte_meteo (hier)",
              lambda: contexte_meteo(lat=la, lon=lo, date_cible=_today() - timedelta(days=1),
                                     koppen_tif=koppen_tif, koppen_legende=koppen_legende)["weather"]["source"],
              resume=lambda r: f"source : {r}")
    bilan = pd.DataFrame(lignes)
    bilan["lignes"] = bilan["lignes"].astype("Int64")
    return bilan


# --------------------------------------------------------------------------- ligne de commande
def _main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collecte météo et climatique du projet 6")
    sous = p.add_subparsers(dest="commande", required=True)

    def options_lieu(sp):
        sp.add_argument("--lieu", help="nom du lieu, ex. « Paris, France »")
        sp.add_argument("--lat", type=float)
        sp.add_argument("--lon", type=float)

    def options_koppen(sp):
        sp.add_argument("--koppen-tif", help="carte Köppen-Geiger .tif (sinon variable KOPPEN_TIF)")
        sp.add_argument("--koppen-legende", help="legend.txt (sinon variable KOPPEN_LEGENDE)")

    v = sous.add_parser("verifier", help="tester toute la chaîne de collecte sur un lieu")
    options_lieu(v); options_koppen(v)
    c = sous.add_parser("contexte", help="contexte météo d'un lieu à une date (JSON)")
    options_lieu(c); options_koppen(c)
    c.add_argument("--date", required=True, help="AAAA-MM-JJ")
    k = sous.add_parser("collecter", help="historique d'une liste de sites (CSV)")
    k.add_argument("--sites", required=True)
    k.add_argument("--debut", default="2010-01-01")
    k.add_argument("--fin")
    options_koppen(k)
    a = p.parse_args(argv)

    try:
        if a.commande == "verifier":
            bilan = verifier(a.lieu, a.lat, a.lon, a.koppen_tif, a.koppen_legende)
            print(bilan.drop(columns="obligatoire").astype(object).fillna("").to_string(index=False))
            echecs = bilan[(bilan["statut"] == "✗") & bilan["obligatoire"]]
            print("\nCollecte opérationnelle ✓" if echecs.empty
                  else f"\n{len(echecs)} étape(s) obligatoire(s) en échec ✗")
            return 0 if echecs.empty else 1
        if a.commande == "contexte":
            res = contexte_meteo(a.lieu, a.date, a.lat, a.lon, a.koppen_tif, a.koppen_legende)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        if a.commande == "collecter":
            print(json.dumps(collecter(a.sites, a.debut, a.fin, a.koppen_tif, a.koppen_legende),
                             ensure_ascii=False, indent=2))
            return 0
    except ErreurMeteo as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
