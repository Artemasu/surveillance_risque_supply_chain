"""
finance_collecte.py — Collecte des signaux finance et marchés (Projet 6, agent finance)

Module général avec cache disque (une même requête n'est jamais envoyée deux fois)
et un tool au format JSON commun des agents.

L'agent surveille cinq familles de signaux qui bougent AVANT qu'un fournisseur lâche son client :
    1. marchés : énergie, carbone, fret, change, métaux, prix de production ;
    2. fournisseurs cotés : cours de bourse ;
    3. santé des fournisseurs : procédures collectives (BODACC) ;
    4. règles et taxes : Federal Register (US), règles UE suivies à la main ;
    5. sanctions et propriété : sanctions UE et US, maisons mères (GLEIF).

Trois usages en ligne de commande
---------------------------------
1. Vérifier que chaque source répond (à lancer en premier) :
       python finance_collecte.py verifier
2. Contexte finance à une date (format JSON commun des agents) :
       python finance_collecte.py contexte --date 2025-04-15 --pays FR --fournisseurs wolfspeed,wingtech
3. Collecter tout l'historique dans data/ :
       python finance_collecte.py collecter --debut 2010-01-01

Utilisation depuis Python (notebook ou autre agent)
---------------------------------------------------
       from finance_collecte import contexte_finance, charger_signal, SIGNAUX
       contexte_finance(date_cible="2026-03-15", pays="FR")

Dépendances : pip install -r requirements.txt
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "cache"
MANUEL_DIR = DATA_DIR / "manuel"
for _d in (CACHE_DIR, MANUEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEBUT_DEFAUT = "2010-01-01"
FIN_CALIBRATION = "2020-12-31"   # seuils calculés sur 2010-2020, crises testées après
USER_AGENT = "projet6-supply-chain-finance (projet etudiant ESME)"

URL_ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.{devise}.EUR.SP00.A"
URL_GSCPI = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"
URL_OIL_HISTO = ("https://energy.ec.europa.eu/document/download/906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
                 "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx")
URL_FEDREG = "https://www.federalregister.gov/api/v1/documents.json"
URL_EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}"
URL_SANCTIONS_UE = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
JETON_SANCTIONS_UE = "dG9rZW4tMjAxNw"   # jeton public de téléchargement de la Commission (sans inscription)
URL_CSL = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv"
URL_GLEIF = "https://api.gleif.org/api/v1"
URL_BODACC = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"


# --------------------------------------------------------------------------
# Les signaux surveillés
# --------------------------------------------------------------------------
# sens : "haut" = une hausse est un risque ; "bas" = une baisse est un risque (euro qui faiblit)
# horizon : nombre d'observations sur lequel on mesure la variation (≈ 4 semaines)
# q : quantile du seuil (1 % des variations les plus fortes en quotidien, 5 % en hebdo/mensuel)
SIGNAUX = pd.DataFrame([
    # signal,       nom,                          famille,        source,                    freq,  sens,  horizon, mesure,     q,    unite,       impact
    ("brent",       "Pétrole Brent",              "énergie",      "yfinance BZ=F",           "J",   "haut", 20, "variation", 0.99, "USD/baril", "Carburant puis transport plus chers"),
    ("gaz_europe",  "Gaz naturel, Europe",        "énergie",      "Banque mondiale (Pink Sheet)", "M", "haut", 1, "variation", 0.95, "USD/mmbtu", "Fournisseurs énergivores plus chers"),
    ("gazole_EU",   "Gazole à la pompe, moyenne UE", "énergie",   "Weekly Oil Bulletin (CE)", "S",  "haut", 4,  "variation", 0.95, "EUR/L",     "Transport routier plus cher"),
    ("gscpi",       "Pression supply chain (GSCPI)", "fret",      "NY Fed",                  "M",   "haut", 1,  "niveau",    0.95, "écarts-types", "Délais et coûts de fret en hausse"),
    ("eur_usd",     "Euro en dollars",            "change",       "BCE",                     "J",   "bas",  20, "variation", 0.99, "USD pour 1 EUR", "Importations en dollars plus chères"),
    ("eur_cny",     "Euro en yuans",              "change",       "BCE",                     "J",   "bas",  20, "variation", 0.99, "CNY pour 1 EUR", "Importations de Chine plus chères"),
    ("cuivre",      "Cuivre",                     "métaux",       "yfinance HG=F",           "J",   "haut", 20, "variation", 0.99, "USD/livre", "Composants électriques plus chers"),
    ("aluminium",   "Aluminium",                  "métaux",       "yfinance ALI=F",          "J",   "haut", 20, "variation", 0.99, "USD/tonne", "Pièces et emballages plus chers"),
    ("zinc",        "Zinc",                       "métaux",       "Banque mondiale (Pink Sheet)", "M", "haut", 1, "variation", 0.95, "USD/tonne", "Acier galvanisé et alliages plus chers"),
    ("nickel",      "Nickel",                     "métaux",       "Banque mondiale (Pink Sheet)", "M", "haut", 1, "variation", 0.95, "USD/tonne", "Batteries et inox plus chers"),
    ("prix_production_EU", "Prix de production industriels, UE", "prix fournisseurs", "Eurostat sts_inpp_m", "M", "haut", 3, "variation", 0.95, "indice 2021=100", "Les fournisseurs industriels augmentent leurs prix"),
    ("carbone_eua", "Carbone EU ETS",             "énergie",      "fichier manuel (ICAP)",   "J",   "haut", 20, "variation", 0.99, "EUR/t CO2", "Industriels soumis au quota carbone et importations CBAM plus chers"),
    ("electricite_DE", "Électricité de gros, Allemagne", "énergie", "fichier manuel (Ember)", "J",  "haut", 20, "variation", 0.99, "EUR/MWh",   "Fournisseurs électro-intensifs plus chers"),
], columns=["signal", "nom", "famille", "source", "freq", "sens", "horizon", "mesure", "q", "unite", "impact"])

TICKERS = {"brent": "BZ=F", "cuivre": "HG=F", "aluminium": "ALI=F"}
BANQUE_MONDIALE = {"gaz_europe": "Natural gas, Europe", "zinc": "Zinc", "nickel": "Nickel"}   # pas d'historique TTF sur yfinance

# Sources sans API simple : lues depuis un fichier CSV (colonnes date, valeur) placé dans data/manuel/<signal>.csv
MANUELS = {
    "carbone_eua": "https://icapcarbonaction.com/en/ets-prices (série de prix EU ETS)",
    "electricite_DE": "https://ember-energy.org/data/european-wholesale-electricity-price-data/ (fichier quotidien, Allemagne)",
}

# Fournisseurs suivis. ticker = action cotée (sinon vide) ; siren = entreprise française (BODACC) ;
# nom_legal = nom exact pour GLEIF et les listes de sanctions. Fournisseurs du cas d'étude.
FOURNISSEURS = pd.DataFrame([
    # cle,          nom,                 nom_legal,                         ticker,      pays, siren,       produit
    ("wolfspeed",   "Wolfspeed",         "Wolfspeed, Inc.",                 "WOLF",      "US", None,        "Carbure de silicium (puces de puissance)"),
    ("wingtech",    "Wingtech (maison mère de Nexperia)", "Wingtech Technology Co., Ltd.", "600745.SS", "CN", None, "Puces (via Nexperia)"),
    ("nexperia",    "Nexperia",          "Nexperia B.V.",                   None,        "NL", None,        "Puces discrètes et logiques"),
    ("infineon",    "Infineon",          "Infineon Technologies AG",        "IFX.DE",    "DE", None,        "Semi-conducteurs"),
    ("stmicro",     "STMicroelectronics", "STMicroelectronics N.V.",        "STMPA.PA",  "FR", None,        "Semi-conducteurs"),
    ("valeo",       "Valeo",             "Valeo SE",                        "FR.PA",     "FR", "552030967", "Équipements automobiles"),
    ("forvia",      "Forvia",            "Forvia SE",                       "FRVIA.PA",  "FR", "542005376", "Équipements automobiles"),
    ("nyrstar",     "Nyrstar",           "Nyrstar NV",                      None,        "BE", None,        "Zinc"),
], columns=["cle", "nom", "nom_legal", "ticker", "pays", "siren", "produit"])
FOURNISSEURS_COTES = FOURNISSEURS[FOURNISSEURS["ticker"].notna()].reset_index(drop=True)

SIGNAUX_FOURNISSEURS = pd.DataFrame([
    (f"bourse_{f.cle}", f"Bourse : {f.nom}", "fournisseurs", f"yfinance {f.ticker}", "J", "bas", 20, "variation", 0.99,
     "cours", f"{f.produit} : fournisseur en difficulté, faillite possible")
    for f in FOURNISSEURS_COTES.itertuples()], columns=SIGNAUX.columns)
TICKERS.update({f"bourse_{f.cle}": f.ticker for f in FOURNISSEURS_COTES.itertuples()})


def tous_les_signaux() -> pd.DataFrame:
    """Signaux de marché + fournisseurs cotés."""
    return pd.concat([SIGNAUX, SIGNAUX_FOURNISSEURS], ignore_index=True)
DEVISES = {"eur_usd": "USD", "eur_cny": "CNY"}

# Règles UE suivies à la main (EUR-Lex n'a pas d'API simple sans inscription) : date de publication,
# date d'entrée en vigueur, effet attendu, source. Complété au fil du projet.
REGLES_UE = pd.DataFrame([
    ("2023-05-16", "2026-01-01", "UE", "CBAM : taxe carbone aux frontières, phase définitive",
     "Surcoût sur acier, aluminium, ciment, engrais, électricité, hydrogène importés",
     "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en"),
    ("2024-07-04", "2024-07-05", "UE", "Droits provisoires sur les voitures électriques importées de Chine",
     "Véhicules et sous-ensembles chinois plus chers",
     "https://policy.trade.ec.europa.eu/news/commission-imposes-provisional-countervailing-duties-imports-battery-electric-vehicles-china-while-discussions-china-continue-2024-07-04_en"),
    ("2022-02-25", "2022-02-25", "UE", "Sanctions contre la Russie (premiers paquets après l'invasion)",
     "Ruptures d'approvisionnement en provenance de Russie",
     "https://www.consilium.europa.eu/fr/policies/sanctions-against-russia/"),
], columns=["publication", "entree_en_vigueur", "zone", "regle", "effet", "url"])


class ErreurFinance(RuntimeError):
    """Erreur de collecte, avec un message lisible."""


# --------------------------------------------------------------------------
# Accès réseau avec cache disque
# --------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT


def telecharger(url: str, params: dict | None = None, ext: str = "bin", max_age_jours: float | None = 1,
                pause: float = 0.5, essais: int = 4) -> bytes:
    """GET avec cache disque. max_age_jours=None : le cache ne périme jamais (données historiques figées)."""
    cle = hashlib.md5((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    fichier = CACHE_DIR / f"{cle}.{ext}"
    if fichier.exists():
        age = (time.time() - fichier.stat().st_mtime) / 86400
        if max_age_jours is None or age < max_age_jours:
            return fichier.read_bytes()
    derniere = None
    for i in range(essais):
        try:
            r = SESSION.get(url, params=params, timeout=60)
        except requests.RequestException as e:
            derniere = str(e)
            time.sleep(pause * (2 ** i))
            continue
        if r.status_code == 429:
            time.sleep(pause * (2 ** (i + 2)))
            continue
        if r.status_code != 200:
            derniere = f"HTTP {r.status_code}"
            break
        fichier.write_bytes(r.content)
        time.sleep(pause)
        return r.content
    if fichier.exists():   # réseau en panne : on garde l'ancienne version plutôt que rien
        return fichier.read_bytes()
    raise ErreurFinance(f"Téléchargement impossible ({derniere}) : {url}")


def _serie(df: pd.DataFrame, col_date: str, col_val: str) -> pd.DataFrame:
    out = pd.DataFrame({"date": pd.to_datetime(df[col_date], errors="coerce"),
                        "valeur": pd.to_numeric(df[col_val], errors="coerce")})
    return out.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
def marche(ticker: str, debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    """Cours de clôture quotidien d'un contrat à terme (yfinance), cache d'un jour."""
    fichier = CACHE_DIR / f"yf_{ticker.replace('=', '_')}_{debut}.csv"
    if fichier.exists() and (time.time() - fichier.stat().st_mtime) / 86400 < 1:
        return pd.read_csv(fichier, parse_dates=["date"])
    try:
        import yfinance as yf
    except ImportError as e:
        raise ErreurFinance("yfinance n'est pas installé (pip install yfinance)") from e
    df = yf.download(ticker, start=debut, progress=False, auto_adjust=False)
    if df is None or df.empty:
        if fichier.exists():
            return pd.read_csv(fichier, parse_dates=["date"])
        raise ErreurFinance(f"yfinance ne renvoie rien pour {ticker}")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    out = pd.DataFrame({"date": pd.to_datetime(close.index).tz_localize(None), "valeur": close.to_numpy(dtype=float)})
    out = out.dropna().reset_index(drop=True)
    out.to_csv(fichier, index=False)
    return out


def change(devise: str = "USD", debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    """Taux de référence BCE : combien de `devise` pour 1 euro, quotidien."""
    contenu = telecharger(URL_ECB.format(devise=devise), {"startPeriod": debut, "format": "csvdata"}, "csv")
    try:
        df = pd.read_csv(io.BytesIO(contenu))
    except Exception as e:
        raise ErreurFinance(f"Réponse BCE illisible ({type(e).__name__})") from e
    if "TIME_PERIOD" not in df or "OBS_VALUE" not in df:
        raise ErreurFinance(f"Format BCE inattendu, colonnes : {list(df.columns)[:8]}")
    return _serie(df, "TIME_PERIOD", "OBS_VALUE")


def gscpi() -> pd.DataFrame:
    """Global Supply Chain Pressure Index (NY Fed), mensuel. Cherche la feuille et les colonnes Date / GSCPI."""
    contenu = telecharger(URL_GSCPI, ext="xlsx", max_age_jours=7)
    feuilles = _lire_excel(contenu, "GSCPI")
    for nom, brut in feuilles.items():
        for i in range(min(15, len(brut))):
            ligne = [str(x).strip().lower() for x in brut.iloc[i].tolist()]
            if "gscpi" in ligne:
                df = brut.iloc[i + 1:].copy()
                df.columns = ligne
                col_date = next((c for c in df.columns if "date" in c), df.columns[0])
                out = _serie(df, col_date, "gscpi")
                if len(out) > 24:
                    return out
    raise ErreurFinance("Colonne GSCPI introuvable dans le fichier de la NY Fed : son format a changé")


def gazole_ue(pays: tuple = ("EU", "FR", "DE", "IT", "ES", "NL", "BE", "PL")) -> pd.DataFrame:
    """
    Prix du gazole à la pompe, toutes taxes, par pays (€/L), hebdomadaire depuis 2005.
    1) Fichier historique de la Commission (colonnes du type « FR_price_with_tax_diesel »).
    2) Sinon, fichier déposé à la main dans data/manuel/oil_bulletin.csv : panel fuel-prices.eu
       (colonnes country_code, week, diesel_eur_l) ou colonnes date, pays, valeur.
    """
    manuel = MANUEL_DIR / "oil_bulletin.csv"
    try:
        contenu = telecharger(URL_OIL_HISTO, ext="xlsx", max_age_jours=7)
        out = _lire_oil_bulletin(contenu)
    except ErreurFinance as e:
        if not manuel.exists():
            raise ErreurFinance(f"{e}. Source de repli : panel « EU Weekly Oil Bulletin » de "
                                f"https://www.fuel-prices.eu/research/, lu depuis {manuel}") from e
        out = _lire_manuel(manuel)
    out = out[out["pays"].isin(pays)] if pays else out
    if out.empty:
        raise ErreurFinance("Aucun prix du gazole pour les pays demandés")
    return out.sort_values(["pays", "date"]).reset_index(drop=True)


def _lire_excel(contenu: bytes, quoi: str) -> dict:
    """Toutes les feuilles d'un fichier Excel ; erreur lisible si le fichier n'est pas un Excel (page d'erreur, etc.)."""
    try:   # calamine lit .xls et .xlsx ; sinon, lecteur par défaut de pandas
        return pd.read_excel(io.BytesIO(contenu), sheet_name=None, header=None, engine="calamine")
    except Exception:
        pass
    try:
        return pd.read_excel(io.BytesIO(contenu), sheet_name=None, header=None)
    except ImportError as e:   # ancien format .xls : nécessite xlrd
        raise ErreurFinance(f"{quoi} : librairie manquante pour lire ce fichier (pip install xlrd) ({e})") from e
    except Exception as e:
        raise ErreurFinance(f"{quoi} : le fichier téléchargé n'est pas un Excel lisible ({type(e).__name__})") from e


def _lire_oil_bulletin(contenu: bytes) -> pd.DataFrame:
    motif = re.compile(r"^([A-Z]{2})_price_with_tax_diesel$", re.I)
    feuilles = _lire_excel(contenu, "Weekly Oil Bulletin")
    for nom, brut in feuilles.items():
        for i in range(min(10, len(brut))):
            entetes = [str(x).strip() for x in brut.iloc[i].tolist()]
            cols = {j: motif.match(h).group(1).upper() for j, h in enumerate(entetes) if motif.match(h)}
            if not cols:
                continue
            dates = pd.to_datetime(brut.iloc[i + 1:, 0], errors="coerce", format="mixed")
            morceaux = []
            for j, code in cols.items():
                v = pd.to_numeric(brut.iloc[i + 1:, j].astype(str).str.replace(",", "").str.replace(" ", ""),
                                  errors="coerce")
                morceaux.append(pd.DataFrame({"date": dates.to_numpy(), "pays": code, "valeur": v.to_numpy()}))
            out = pd.concat(morceaux).dropna()
            if out.empty:
                continue
            if out["valeur"].median() > 50:   # prix publiés en € pour 1 000 litres
                out["valeur"] = out["valeur"] / 1000
            return out.reset_index(drop=True)
    raise ErreurFinance("Colonnes « XX_price_with_tax_diesel » introuvables dans le fichier de la Commission")


def _lire_manuel(chemin: Path) -> pd.DataFrame:
    df = pd.read_csv(chemin)
    df.columns = [c.strip().lower() for c in df.columns]
    if {"country_code", "week", "diesel_eur_l"} <= set(df.columns):
        df = df.rename(columns={"country_code": "pays", "week": "date", "diesel_eur_l": "valeur"})
    elif not {"date", "pays", "valeur"} <= set(df.columns):
        raise ErreurFinance(f"{chemin} : colonnes attendues country_code, week, diesel_eur_l (ou date, pays, valeur)")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce")
    return df[["date", "pays", "valeur"]].dropna()


def banque_mondiale(nom: str) -> pd.DataFrame:
    """
    Prix mensuel d'une matière première (Pink Sheet de la Banque mondiale), cache de 7 jours.
    La valeur d'un mois n'est connue qu'à sa fin : on la date au dernier jour du mois (pas de fuite d'information).
    """
    fichier = CACHE_DIR / f"bm_{re.sub(r'[^a-z0-9]+', '_', nom.lower())}.csv"
    if fichier.exists() and (time.time() - fichier.stat().st_mtime) / 86400 < 7:
        return pd.read_csv(fichier, parse_dates=["date"])
    try:
        from worldbank_commodities import WorldBankCommodities
    except ImportError as e:
        raise ErreurFinance("worldbank-commodities n'est pas installé (pip install worldbank-commodities)") from e
    try:
        df = WorldBankCommodities().get_prices(freq="monthly", commodities=nom)
    except Exception as e:
        if fichier.exists():
            return pd.read_csv(fichier, parse_dates=["date"])
        raise ErreurFinance(f"Banque mondiale indisponible ({type(e).__name__}: {str(e)[:100]})") from e
    df = df[df["commodity"].str.lower() == nom.lower()] if (df["commodity"].str.lower() == nom.lower()).any() else df
    out = _serie(df, "date", "price")
    if out.empty:
        raise ErreurFinance(f"Série « {nom} » introuvable à la Banque mondiale")
    out["date"] = out["date"] + pd.offsets.MonthEnd(0)
    out.to_csv(fichier, index=False)
    return out


def lire_csv_manuel(chemin: Path) -> pd.DataFrame:
    """CSV déposé à la main : une colonne date (ou Date) et une colonne valeur (ou Close, Adj Close, Price, Dernier, Prix)."""
    df = pd.read_csv(chemin, sep=None, engine="python")
    df.columns = [str(c).strip().lower() for c in df.columns]
    col_date = next((c for c in df.columns if c in ("date", "datetime", "time", "jour", "week")), None)
    col_val = next((c for c in ("valeur", "adj close", "close", "price", "dernier", "prix", "price (eur/mwhe)") if c in df.columns), None)
    if col_val is None:
        col_val = next((c for c in df.columns if c != col_date and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.8), None)
    if col_date is None or col_val is None:
        raise ErreurFinance(f"{chemin} : colonnes date et valeur introuvables")
    df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(",", ".", regex=False)
                                .str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
    df[col_date] = pd.to_datetime(df[col_date], errors="coerce", format="mixed")
    return _serie(df, col_date, col_val)


def bourse_manuelle(cle: str) -> pd.DataFrame | None:
    """
    Historique boursier déposé à la main dans data/manuel/bourse_<cle>.csv (quand Yahoo l'a perdu,
    par exemple après une faillite où les anciennes actions sont annulées). Colonnes acceptées :
    date (ou Date) et valeur (ou Close, Adj Close, Price, Dernier).
    """
    chemin = MANUEL_DIR / f"bourse_{cle}.csv"
    return lire_csv_manuel(chemin) if chemin.exists() else None


def eurostat(code: str = "sts_inpp_m", **filtres) -> pd.DataFrame:
    """
    Série mensuelle Eurostat (format JSON-stat). Par défaut : prix de production de l'industrie manufacturière
    dans l'UE (indice 2021 = 100, non désaisonnalisé). Chaque filtre doit fixer une seule valeur par dimension.
    """
    params = {"geo": "EU27_2020", "nace_r2": "C", "indic_bt": "PRC_PRR", "s_adj": "NSA", "unit": "I21", "lang": "en"}
    params.update(filtres)
    try:
        data = json.loads(telecharger(URL_EUROSTAT.format(code=code), params, "json", max_age_jours=7))
    except json.JSONDecodeError as e:
        raise ErreurFinance("Réponse Eurostat illisible") from e
    if "value" not in data or "dimension" not in data:
        raise ErreurFinance(f"Eurostat : réponse inattendue ({str(data)[:150]})")
    tailles = dict(zip(data["id"], data["size"]))
    if any(v > 1 for k, v in tailles.items() if k != "time"):
        raise ErreurFinance(f"Eurostat : plusieurs valeurs pour une dimension, filtres insuffisants ({tailles})")
    temps = data["dimension"]["time"]["category"]["index"]
    valeurs = data["value"]
    lignes = [(t, valeurs.get(str(i)) if isinstance(valeurs, dict) else valeurs[i]) for t, i in temps.items()]
    df = pd.DataFrame(lignes, columns=["date", "valeur"])
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    return _serie(df, "date", "valeur")


def federal_register(terme: str, agence: str | None = None, types: tuple = ("RULE",),
                     debut: str = "2018-01-01", max_pages: int = 5) -> pd.DataFrame:
    """Textes officiels américains (droits de douane, Entity List...) : publication et entrée en vigueur."""
    params = {"conditions[term]": terme, "conditions[publication_date][gte]": debut,
              "per_page": 100, "order": "oldest",
              "fields[]": ["title", "publication_date", "effective_on", "html_url", "document_number", "type", "agencies"]}
    if agence:
        params["conditions[agencies][]"] = agence
    if types:
        params["conditions[type][]"] = list(types)
    lignes, page = [], 1
    while page <= max_pages:
        params["page"] = page
        try:
            data = json.loads(telecharger(URL_FEDREG, params, "json"))
        except json.JSONDecodeError as e:
            raise ErreurFinance("Réponse du Federal Register illisible") from e
        for d in data.get("results", []):
            lignes.append({"publication": d.get("publication_date"), "entree_en_vigueur": d.get("effective_on"),
                           "titre": d.get("title"), "type": d.get("type"), "url": d.get("html_url"),
                           "document": d.get("document_number"),
                           "agences": ", ".join(a.get("name", "") for a in (d.get("agencies") or []))})
        if not data.get("next_page_url"):
            break
        page += 1
    df = pd.DataFrame(lignes, columns=["publication", "entree_en_vigueur", "titre", "type", "url", "document", "agences"])
    for c in ("publication", "entree_en_vigueur"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["terme"] = terme
    df["delai_jours"] = (df["entree_en_vigueur"] - df["publication"]).dt.days
    return df


def charger_signal(signal: str, debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    """Série brute (date, valeur) d'un signal de SIGNAUX."""
    if signal.startswith("bourse_"):
        cle = signal.split("_", 1)[1]
        manuel = bourse_manuelle(cle)
        try:
            yahoo = marche(TICKERS[signal], debut)
        except ErreurFinance:
            if manuel is None:
                raise
            return manuel.assign(segment=0)
        if manuel is None:
            return yahoo
        # l'historique manuel complète Yahoo avant sa première date ; segments séparés (pas de variation à cheval)
        avant = manuel[manuel["date"] < yahoo["date"].min()].assign(segment=0)
        return pd.concat([avant, yahoo.assign(segment=1)], ignore_index=True)
    if signal in TICKERS:
        return marche(TICKERS[signal], debut)
    if signal in BANQUE_MONDIALE:
        return banque_mondiale(BANQUE_MONDIALE[signal])
    if signal == "prix_production_EU":
        return eurostat()
    if signal in MANUELS:
        chemin = MANUEL_DIR / f"{signal}.csv"
        if not chemin.exists():
            raise ErreurFinance(f"fichier manuel absent : {chemin} (source : {MANUELS[signal]})")
        return lire_csv_manuel(chemin)
    if signal in DEVISES:
        return change(DEVISES[signal], debut)
    if signal == "gscpi":
        return gscpi()
    if signal.startswith("gazole_"):
        code = signal.split("_", 1)[1]
        g = gazole_ue((code,))
        return g[["date", "valeur"]].reset_index(drop=True)
    raise ErreurFinance(f"Signal inconnu : {signal}")


# --------------------------------------------------------------------------
# Sanctions, propriété, procédures collectives
# --------------------------------------------------------------------------
SUFFIXES = r"\b(co|ltd|limited|inc|corp|corporation|company|b ?v|n ?v|ag|se|sa|s ?a|gmbh|plc|llc|holding|holdings|group|ab|spa|nv)\b"


def normaliser(nom: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(nom or "").lower())
    s = re.sub(SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def csl() -> pd.DataFrame:
    """Consolidated Screening List américaine (dont l'Entity List) : entités, liste, date d'inscription."""
    df = pd.read_csv(io.BytesIO(telecharger(URL_CSL, ext="csv", max_age_jours=1)), dtype=str).fillna("")
    df.columns = [c.strip().lower() for c in df.columns]
    if "name" not in df:
        raise ErreurFinance(f"Format CSL inattendu : {list(df.columns)[:8]}")
    if "type" in df:
        df = df[df["type"].str.lower() != "individual"]
    out = pd.DataFrame({"nom": df["name"], "autres_noms": df.get("alt_names", ""), "liste": "US : " + df.get("source", ""),
                        "programme": df.get("programs", ""),
                        "date_inscription": pd.to_datetime(df.get("start_date", pd.Series(index=df.index, dtype=str)), errors="coerce"),
                        "source_id": "csl:" + df.get("_id", df.get("entity_number", ""))})
    return out.reset_index(drop=True)


def sanctions_ue() -> pd.DataFrame:
    """Liste consolidée des sanctions financières de l'UE (XML) : entreprises seulement."""
    import xml.etree.ElementTree as ET
    manuel = MANUEL_DIR / "sanctions_ue.xml"
    try:
        contenu = telecharger(URL_SANCTIONS_UE, {"token": JETON_SANCTIONS_UE}, ext="xml", max_age_jours=1)
    except ErreurFinance as e:
        if not manuel.exists():
            raise ErreurFinance(f"{e}. Source de repli : fichier XML de https://data.europa.eu/data/datasets/"
                                f"consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions, "
                                f"lu depuis {manuel}") from e
        contenu = manuel.read_bytes()
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as e:
        raise ErreurFinance("Sanctions UE : le fichier téléchargé n'est pas un XML lisible") from e
    local = lambda el: el.tag.rsplit("}", 1)[-1]
    lignes = []
    for ent in racine.iter():
        if local(ent) != "sanctionEntity":
            continue
        type_ = next((c.get("code") for c in ent if local(c) == "subjectType"), "")
        if type_ and type_.lower() == "person":
            continue
        noms = [c.get("wholeName") for c in ent if local(c) == "nameAlias" and c.get("wholeName")]
        reg = next((c for c in ent if local(c) == "regulation"), None)
        if not noms:
            continue
        lignes.append({"nom": noms[0], "autres_noms": "; ".join(noms[1:]), "liste": "UE : sanctions financières",
                       "programme": reg.get("programme", "") if reg is not None else "",
                       "date_inscription": pd.to_datetime(reg.get("publicationDate") if reg is not None else None, errors="coerce"),
                       "source_id": f"ue_fsf:{ent.get('logicalId', '')}"})
    if not lignes:
        raise ErreurFinance("Sanctions UE : aucune entité trouvée dans le fichier")
    return pd.DataFrame(lignes)


def listes_sanctions() -> pd.DataFrame:
    """CSL américaine + sanctions UE, au même format ; une liste indisponible est simplement omise."""
    morceaux = []
    for f in (csl, sanctions_ue):
        try:
            morceaux.append(f())
        except ErreurFinance as e:
            print(f"  liste de sanctions indisponible : {e}")
    return pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame(
        columns=["nom", "autres_noms", "liste", "programme", "date_inscription", "source_id"])


def correspondances(nom: str, listes: pd.DataFrame, seuil_score: int = 92) -> pd.DataFrame:
    """Entrées des listes de sanctions dont un nom ressemble fortement à `nom` (token_sort_ratio, strict)."""
    from rapidfuzz import fuzz
    cible = normaliser(nom)
    if len(cible) < 4 or listes.empty:
        return listes.iloc[0:0].assign(score=[])
    def score(ligne):
        noms = [ligne["nom"]] + [n for n in str(ligne["autres_noms"]).split(";") if n.strip()]
        return max(fuzz.token_sort_ratio(cible, normaliser(n)) for n in noms)
    sc = listes.apply(score, axis=1)
    return listes[sc >= seuil_score].assign(score=sc[sc >= seuil_score])


def gleif_lei(nom_legal: str) -> dict | None:
    """Meilleure fiche GLEIF pour un nom légal (recherche plein texte, puis nom exact)."""
    from rapidfuzz import fuzz
    res = None
    for filtre in ("filter[fulltext]", "filter[entity.legalName]"):
        try:
            res = json.loads(telecharger(f"{URL_GLEIF}/lei-records", {filtre: nom_legal, "page[size]": 10}, "json", max_age_jours=30))
        except (ErreurFinance, json.JSONDecodeError):
            res = None
        if res and res.get("data"):
            break
    if not res or not res.get("data"):
        return None
    meilleur = max(res["data"], key=lambda r: (fuzz.token_sort_ratio(normaliser(nom_legal),
                                                                      normaliser(r["attributes"]["entity"]["legalName"]["name"])),
                                               r["attributes"]["entity"].get("status") == "ACTIVE"))
    nom_trouve = meilleur["attributes"]["entity"]["legalName"]["name"]
    return meilleur if fuzz.token_sort_ratio(normaliser(nom_legal), normaliser(nom_trouve)) >= 85 else None


def gleif_parents(lei: str) -> list[dict]:
    """Maisons mères directe et ultime déclarées à GLEIF (consolidation comptable, pas de pourcentage)."""
    parents = []
    for kind in ("direct", "ultimate"):
        try:
            res = json.loads(telecharger(f"{URL_GLEIF}/lei-records/{lei}/{kind}-parent", None, "json", max_age_jours=30))
        except (ErreurFinance, json.JSONDecodeError):
            continue
        d = res.get("data") if res else None
        if d and d["attributes"]["lei"] != lei:
            parents.append({"type": "directe" if kind == "direct" else "ultime", "lei": d["attributes"]["lei"],
                            "nom": d["attributes"]["entity"]["legalName"]["name"]})
    return parents


# Liens de propriété connus mais absents de GLEIF
PROPRIETE_MANUELLE = pd.DataFrame([
    ("Nexperia B.V.", "Wingtech Technology Co., Ltd.", "ultime", "Rachat de Nexperia par Wingtech (2019)"),
], columns=["enfant", "parent", "type", "source"])


def proprietaires(nom_legal: str) -> list[dict]:
    """Maisons mères : GLEIF d'abord, puis liens manuels sourcés."""
    out = []
    fiche = gleif_lei(nom_legal)
    if fiche:
        out = gleif_parents(fiche["attributes"]["lei"])
    for m in PROPRIETE_MANUELLE[PROPRIETE_MANUELLE["enfant"].map(normaliser) == normaliser(nom_legal)].itertuples():
        if not any(normaliser(p["nom"]) == normaliser(m.parent) for p in out):
            out.append({"type": m.type, "lei": None, "nom": m.parent, "source": m.source})
    return out


def bodacc(siren: str, debut: str = "2015-01-01") -> pd.DataFrame:
    """Procédures collectives (sauvegarde, redressement, liquidation) publiées au BODACC pour un SIREN."""
    siren = re.sub(r"\D", "", str(siren))
    params = {"where": f"familleavis='collective' AND '{siren}' AND dateparution>=date'{debut}'",
              "order_by": "dateparution", "limit": 100}
    try:
        data = json.loads(telecharger(URL_BODACC, params, "json", max_age_jours=1))
    except json.JSONDecodeError as e:
        raise ErreurFinance("Réponse BODACC illisible") from e
    if "results" not in data:
        raise ErreurFinance(f"BODACC : réponse inattendue ({str(data)[:150]})")
    lignes = [{"date": r.get("dateparution"), "type": r.get("familleavis_lib"), "entreprise": r.get("commercant"),
               "tribunal": r.get("tribunal"), "detail": str(r.get("jugement") or "")[:200],
               "source_id": f"bodacc:{r.get('id', '')}"} for r in data["results"]]
    df = pd.DataFrame(lignes, columns=["date", "type", "entreprise", "tribunal", "detail", "source_id"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def fiche_fournisseur(cle: str, date_cible=None, listes: pd.DataFrame | None = None) -> dict:
    """
    Tout ce que l'agent sait d'un fournisseur à une date : bourse, maisons mères, sanctions (sur lui ou ses
    maisons mères, inscrites avant la date), procédures collectives. Ne regarde jamais après date_cible.
    """
    jour = pd.Timestamp(date_cible or date.today())
    f = FOURNISSEURS.set_index("cle").loc[cle]
    fiche = {"fournisseur": f["nom"], "pays": f["pays"], "produit": f["produit"], "alertes": [], "donnees_manquantes": []}
    # bourse
    if pd.notna(f["ticker"]):
        try:
            brut = charger_signal(f"bourse_{cle}")
            brut = brut[brut["date"] <= jour]
            ind = indicateur(brut, "variation", 20).dropna()
            sl = seuil(ind, "bas", 0.99)
            if len(ind):
                v = float(ind.iloc[-1])
                fiche["bourse"] = {"variation_20j_%": round(v, 1), "seuil": None if pd.isna(sl) else round(sl, 1),
                                   "en_alerte": en_alerte(v, sl, "bas"), "date_valeur": str(ind.index[-1].date())}
                if fiche["bourse"]["en_alerte"]:
                    fiche["alertes"].append(f"chute de l'action : {v:.0f} % en 20 jours")
        except ErreurFinance:
            fiche["donnees_manquantes"].append("bourse")
    # propriété et sanctions
    parents = proprietaires(f["nom_legal"])
    fiche["proprietaires"] = parents
    listes = listes_sanctions() if listes is None else listes
    touchees = []
    for nom, role in [(f["nom_legal"], "lui-même")] + [(p["nom"], f"maison mère {p['type']}") for p in parents]:
        c = correspondances(nom, listes)
        c = c[c["date_inscription"].isna() | (c["date_inscription"] <= jour)]
        for r in c.itertuples():
            touchees.append({"entite": nom, "role": role, "liste": r.liste, "nom_sur_liste": r.nom,
                             "date_inscription": None if pd.isna(r.date_inscription) else str(r.date_inscription.date()),
                             "source_id": r.source_id})
    fiche["sanctions"] = touchees
    if touchees:
        fiche["alertes"].append("sanction sur " + ", ".join(sorted({t["role"] for t in touchees})))
    # procédures collectives (entreprises françaises)
    if pd.notna(f["siren"]):
        try:
            b = bodacc(f["siren"])
            b = b[b["date"] <= jour]
            fiche["procedures_collectives"] = b.assign(date=b["date"].dt.date.astype(str)).to_dict("records")
            if len(b):
                fiche["alertes"].append(f"procédure collective publiée au BODACC le {b['date'].max().date()}")
        except ErreurFinance:
            fiche["donnees_manquantes"].append("bodacc")
    fiche["en_alerte"] = bool(fiche["alertes"])
    return fiche


# --------------------------------------------------------------------------
# Indicateurs, seuils, situation d'une valeur
# --------------------------------------------------------------------------
def indicateur(serie: pd.DataFrame, mesure: str, horizon: int) -> pd.Series:
    """Variation en % sur `horizon` observations, ou niveau brut (GSCPI, déjà standardisé)."""
    v = serie.set_index("date")["valeur"].astype(float)
    if mesure == "niveau":
        return v
    if "segment" in serie:   # deux historiques collés : pas de variation calculée à cheval sur la jonction
        return 100 * v.groupby(serie["segment"].to_numpy()).pct_change(horizon, fill_method=None)
    return 100 * v.pct_change(horizon, fill_method=None)


def periode_calibration(ind: pd.Series, fin_calibration: str = FIN_CALIBRATION) -> pd.Series:
    """Valeurs jusqu'à fin_calibration ; pour une série trop récente, ses 3 premières années."""
    calib = ind[ind.index <= pd.Timestamp(fin_calibration)].dropna()
    if len(calib) < 250 and len(ind.dropna()):
        debut = ind.dropna().index[0]
        calib = ind[(ind.index >= debut) & (ind.index <= debut + pd.DateOffset(years=3))].dropna()
    return calib


def seuil(ind: pd.Series, sens: str, q: float, fin_calibration: str = FIN_CALIBRATION) -> float:
    """Seuil d'alerte : quantile des variations sur la période de calibration."""
    calib = periode_calibration(ind, fin_calibration)
    if len(calib) < 30:
        return np.nan
    return float(calib.quantile(q if sens == "haut" else 1 - q))


def en_alerte(valeur: float, s: float, sens: str) -> bool:
    if pd.isna(valeur) or pd.isna(s):
        return False
    return valeur >= s if sens == "haut" else valeur <= s


def rang(valeur: float, reference: pd.Series, sens: str) -> float | None:
    """0,99 = parmi les 1 % de valeurs les plus extrêmes dans le sens du risque."""
    ref = reference.dropna()
    if pd.isna(valeur) or ref.empty:
        return None
    r = (ref <= valeur).mean() if sens == "haut" else (ref >= valeur).mean()
    return round(float(r), 3)


# --------------------------------------------------------------------------
# Le tool : contexte finance à une date (format JSON commun)
# --------------------------------------------------------------------------
def contexte_finance(date_cible=None, pays: str = "EU", fournisseurs: tuple = (), debut: str = DEBUT_DEFAUT) -> dict:
    """
    Contexte finance et marchés à une date : pour chaque signal, sa dernière valeur connue à cette date,
    son seuil et s'il est en alerte. Ne regarde jamais après date_cible (pas de fuite d'information).
    fournisseurs : clés de FOURNISSEURS_COTES à inclure (ex. ("wolfspeed", "wingtech")).
    """
    jour = pd.Timestamp(date_cible or date.today())
    sortie = {"date": str(jour.date()), "location": {"pays": pays}, "finance": None, "donnees_manquantes": []}
    signaux = []
    for s in SIGNAUX.itertuples():
        nom_signal = f"gazole_{pays}" if s.signal == "gazole_EU" and pays != "EU" else s.signal
        try:
            brut = charger_signal(nom_signal, debut)
        except ErreurFinance:
            if s.signal not in MANUELS:   # un fichier manuel non déposé n'est pas une donnée manquante
                sortie["donnees_manquantes"].append(nom_signal)
            continue
        brut = brut[brut["date"] <= jour]
        ind = indicateur(brut, s.mesure, s.horizon).dropna()
        if ind.empty:
            sortie["donnees_manquantes"].append(nom_signal)
            continue
        sl = seuil(ind, s.sens, s.q)
        derniere_date, val = ind.index[-1], float(ind.iloc[-1])
        signaux.append({
            "signal": nom_signal, "nom": s.nom, "famille": s.famille,
            "date_valeur": str(derniere_date.date()), "valeur_brute": round(float(brut["valeur"].iloc[-1]), 4),
            "indicateur": round(val, 2), "mesure": "variation_%" if s.mesure == "variation" else "niveau",
            "seuil": None if pd.isna(sl) else round(sl, 2), "en_alerte": en_alerte(val, sl, s.sens),
            "rang": rang(val, periode_calibration(ind), s.sens),
            "impact": s.impact,
            "source_id": f"{s.source.split()[0].lower()}:{nom_signal}:{derniere_date.date()}",
        })
    regles = REGLES_UE[(pd.to_datetime(REGLES_UE["publication"]) <= jour)
                       & (pd.to_datetime(REGLES_UE["entree_en_vigueur"]) >= jour - pd.Timedelta(days=365))]
    fiches = []
    if fournisseurs:
        listes = listes_sanctions()
        fiches = [fiche_fournisseur(c, jour, listes) for c in fournisseurs if c in set(FOURNISSEURS["cle"])]
    sortie["finance"] = {
        "signaux": signaux,
        "fournisseurs": fiches,
        "nb_alertes": sum(x["en_alerte"] for x in signaux),
        "regles_ue": regles.assign(publication=regles["publication"].astype(str),
                                   entree_en_vigueur=regles["entree_en_vigueur"].astype(str)).to_dict("records"),
        "source_id": [x["source_id"] for x in signaux],
    }
    return sortie


# --------------------------------------------------------------------------
# Vérification et collecte (ligne de commande)
# --------------------------------------------------------------------------
def verifier() -> pd.DataFrame:
    """Teste chaque maillon de la collecte et renvoie un tableau de bilan."""
    tests = [(f"{s.nom} ({s.source})", (lambda sig=s.signal: charger_signal(sig, "2015-01-01")), s.freq)
             for s in tous_les_signaux().itertuples()]
    tests.append(("Federal Register (Entity List)",
                  lambda: federal_register("entity list", "industry-and-security-bureau", debut="2025-01-01", max_pages=1), "R"))
    tests.append(("Sanctions UE (liste consolidée)", lambda: sanctions_ue()[["date_inscription", "nom"]].dropna().sort_values("date_inscription"), "R"))
    tests.append(("Consolidated Screening List (US)", lambda: csl()[["date_inscription", "nom"]].dropna().sort_values("date_inscription"), "R"))
    tests.append(("GLEIF (Nexperia B.V.)", lambda: pd.DataFrame([{"date": date.today(), "lei": (gleif_lei("Nexperia B.V.") or {}).get("id")}]).dropna(), "R"))
    tests.append(("BODACC (Valeo)", lambda: bodacc("552030967"), "B"))
    lignes = []
    for nom, f, freq in tests:
        try:
            df = f()
            if freq == "B":   # BODACC : zéro procédure collective est une bonne nouvelle
                ok = "✓"
            elif len(df) < 2 and freq != "R":
                ok = "✗"
            elif len(df) == 0:
                ok = "✗"
            elif freq in ("J", "S", "M") and pd.Timestamp(df.iloc[0, 0]) > pd.Timestamp("2015-12-31"):
                ok = "⚠"   # historique trop court pour calibrer les seuils et rejouer les crises
            else:
                ok = "✓"
            detail = f"{len(df)} lignes" + (f", du {pd.Timestamp(df.iloc[0, 0]).date()} au {pd.Timestamp(df.iloc[-1, 0]).date()}" if len(df) else "")
            lignes.append({"maillon": nom, "ok": ok, "detail": detail})
        except Exception as e:   # on veut voir toutes les erreurs, pas s'arrêter à la première
            manuel = "fichier manuel absent" in str(e)
            lignes.append({"maillon": nom, "ok": "–" if manuel else "✗", "detail": str(e)[:110]})
    return pd.DataFrame(lignes)


def collecter(debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    """Historique de tous les signaux, au format long (signal, date, valeur), enregistré dans data/."""
    morceaux = []
    for s in tous_les_signaux().itertuples():
        try:
            df = charger_signal(s.signal, debut)
            morceaux.append(df.assign(signal=s.signal))
            print(f"→ {s.signal:<11} ✓  {len(df)} valeurs")
        except ErreurFinance as e:
            print(f"→ {s.signal:<11} ✗  {e}")
    out = pd.concat(morceaux)[["signal", "date", "valeur"]] if morceaux else pd.DataFrame(columns=["signal", "date", "valeur"])
    out.to_csv(DATA_DIR / "finance_brut.csv", index=False)
    return out


def _main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collecte des signaux finance et marchés du projet 6")
    sous = p.add_subparsers(dest="cmd", required=True)
    sous.add_parser("verifier", help="tester chaque source")
    c = sous.add_parser("contexte", help="contexte finance à une date (JSON)")
    c.add_argument("--date", default=None)
    c.add_argument("--pays", default="EU")
    c.add_argument("--fournisseurs", default="", help="clés séparées par des virgules, ex. wolfspeed,wingtech")
    k = sous.add_parser("collecter", help="historique de tous les signaux")
    k.add_argument("--debut", default=DEBUT_DEFAUT)
    a = p.parse_args(argv)
    if a.cmd == "verifier":
        print(verifier().to_string(index=False))
    elif a.cmd == "contexte":
        f = tuple(x.strip() for x in a.fournisseurs.split(",") if x.strip())
        print(json.dumps(contexte_finance(a.date, a.pays, f), indent=2, ensure_ascii=False))
    else:
        collecter(a.debut)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
