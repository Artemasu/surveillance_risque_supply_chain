"""Signaux de marché (famille 1 du volet Finance) et cours des fournisseurs cotés (famille 2).

Repris de `finance_collecte.py`. Chaque loader renvoie une série (date, valeur) triée, sans doublon.
Différences avec le module d'origine :
  - Banque mondiale : lecture directe du Pink Sheet mensuel (fichier Excel public) au lieu du paquet
    `worldbank-commodities`, peu répandu ; le paquet reste utilisé s'il est installé et que le fichier échoue ;
  - chemins (cache, fichiers manuels) réglés par `settings`, aucun dossier créé à l'import.
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import pandas as pd

from src.config import settings
from src.connectors.http_cache import SourceError, cache_dir, fetch_bytes

NS = "finance"
DEBUT_DEFAUT = "2010-01-01"
FIN_CALIBRATION = "2020-12-31"   # seuils calculés sur 2010-2020, crises testées après

URL_ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.{devise}.EUR.SP00.A"
URL_GSCPI = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"
URL_OIL_HISTO = ("https://energy.ec.europa.eu/document/download/906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
                 "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx")
URL_EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}"
URL_PINK_SHEET_PAGE = "https://www.worldbank.org/en/research/commodity-markets"

# sens : "haut" = une hausse est un risque ; "bas" = une baisse est un risque (euro qui faiblit, action qui chute)
# horizon : nombre d'observations de la variation ; q : quantile du seuil
SIGNAUX = pd.DataFrame([
    ("brent", "Pétrole Brent", "énergie", "yfinance BZ=F", "J", "haut", 20, "variation", 0.99, "USD/baril", "Carburant puis transport plus chers"),
    ("gaz_europe", "Gaz naturel, Europe", "énergie", "Banque mondiale (Pink Sheet)", "M", "haut", 1, "variation", 0.95, "USD/mmbtu", "Fournisseurs énergivores plus chers"),
    ("gazole_EU", "Gazole à la pompe, moyenne UE", "énergie", "Weekly Oil Bulletin (CE)", "S", "haut", 4, "variation", 0.95, "EUR/L", "Transport routier plus cher"),
    ("gscpi", "Pression supply chain (GSCPI)", "fret", "NY Fed", "M", "haut", 1, "niveau", 0.95, "écarts-types", "Délais et coûts de fret en hausse"),
    ("eur_usd", "Euro en dollars", "change", "BCE", "J", "bas", 20, "variation", 0.99, "USD pour 1 EUR", "Importations en dollars plus chères"),
    ("eur_cny", "Euro en yuans", "change", "BCE", "J", "bas", 20, "variation", 0.99, "CNY pour 1 EUR", "Importations de Chine plus chères"),
    ("cuivre", "Cuivre", "métaux", "yfinance HG=F", "J", "haut", 20, "variation", 0.99, "USD/livre", "Composants électriques plus chers"),
    ("aluminium", "Aluminium", "métaux", "yfinance ALI=F", "J", "haut", 20, "variation", 0.99, "USD/tonne", "Pièces et emballages plus chers"),
    ("zinc", "Zinc", "métaux", "Banque mondiale (Pink Sheet)", "M", "haut", 1, "variation", 0.95, "USD/tonne", "Acier galvanisé et alliages plus chers"),
    ("nickel", "Nickel", "métaux", "Banque mondiale (Pink Sheet)", "M", "haut", 1, "variation", 0.95, "USD/tonne", "Batteries et inox plus chers"),
    ("prix_production_EU", "Prix de production industriels, UE", "prix fournisseurs", "Eurostat sts_inpp_m", "M", "haut", 3, "variation", 0.95, "indice 2021=100", "Les fournisseurs industriels augmentent leurs prix"),
    ("carbone_eua", "Carbone EU ETS", "énergie", "fichier manuel (ICAP)", "J", "haut", 20, "variation", 0.99, "EUR/t CO2", "Industriels soumis au quota carbone et importations CBAM plus chers"),
    ("electricite_DE", "Électricité de gros, Allemagne", "énergie", "fichier manuel (Ember)", "J", "haut", 20, "variation", 0.99, "EUR/MWh", "Fournisseurs électro-intensifs plus chers"),
], columns=["signal", "nom", "famille", "source", "freq", "sens", "horizon", "mesure", "q", "unite", "impact"])

TICKERS = {"brent": "BZ=F", "cuivre": "HG=F", "aluminium": "ALI=F"}
BANQUE_MONDIALE = {"gaz_europe": "Natural gas, Europe", "zinc": "Zinc", "nickel": "Nickel"}
DEVISES = {"eur_usd": "USD", "eur_cny": "CNY"}
MANUELS = {
    "carbone_eua": "https://icapcarbonaction.com/en/ets-prices (série de prix EU ETS)",
    "electricite_DE": "https://ember-energy.org/data/european-wholesale-electricity-price-data/ (Allemagne, quotidien)",
}


def manual_dir() -> Path:
    """Fichiers déposés à la main (colonnes date, valeur) : data/manuel/<signal>.csv."""
    return settings.data_dir / "manuel"


def _serie(df: pd.DataFrame, col_date: str, col_val: str) -> pd.DataFrame:
    out = pd.DataFrame({"date": pd.to_datetime(df[col_date], errors="coerce"),
                        "valeur": pd.to_numeric(df[col_val], errors="coerce")})
    return out.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)


def _lire_excel(contenu: bytes, quoi: str) -> dict:
    for engine in ("calamine", None):
        try:
            return pd.read_excel(io.BytesIO(contenu), sheet_name=None, header=None, engine=engine)
        except ImportError:
            continue
        except Exception as e:
            if engine is None:
                raise SourceError(f"{quoi} : le fichier téléchargé n'est pas un Excel lisible ({type(e).__name__})") from e
    raise SourceError(f"{quoi} : aucune librairie pour lire ce fichier (pip install python-calamine openpyxl)")


# --------------------------------------------------------------------------- sources
def marche(ticker: str, debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    """Cours de clôture quotidien (yfinance), cache d'un jour, copie précédente si Yahoo ne répond pas."""
    fichier = cache_dir(NS) / f"yf_{re.sub(r'[^A-Za-z0-9]+', '_', ticker)}_{debut}.csv"
    if fichier.exists() and ((time.time() - fichier.stat().st_mtime) / 86400 < 1 or settings.offline):
        return pd.read_csv(fichier, parse_dates=["date"])
    if settings.offline:
        raise SourceError(f"hors ligne et absent du cache : {ticker}")
    try:
        import yfinance as yf
    except ImportError as e:
        raise SourceError("yfinance n'est pas installé (pip install yfinance)") from e
    try:
        df = yf.download(ticker, start=debut, progress=False, auto_adjust=False)
    except Exception as e:                              # yfinance lève des erreurs très variées
        df, err = None, e
    else:
        err = None
    if df is None or df.empty:
        if fichier.exists():
            return pd.read_csv(fichier, parse_dates=["date"])
        raise SourceError(f"yfinance ne renvoie rien pour {ticker}" + (f" ({type(err).__name__})" if err else ""))
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    out = pd.DataFrame({"date": pd.to_datetime(close.index).tz_localize(None), "valeur": close.to_numpy(dtype=float)})
    out = out.dropna().reset_index(drop=True)
    out.to_csv(fichier, index=False)
    return out


def change(devise: str = "USD", debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    """Taux de référence BCE : combien de `devise` pour 1 euro, quotidien."""
    contenu = fetch_bytes(URL_ECB.format(devise=devise), {"startPeriod": debut, "format": "csvdata"},
                          namespace=NS, ext="csv", ttl_days=1)
    try:
        df = pd.read_csv(io.BytesIO(contenu))
    except Exception as e:
        raise SourceError(f"réponse BCE illisible ({type(e).__name__})") from e
    if "TIME_PERIOD" not in df or "OBS_VALUE" not in df:
        raise SourceError(f"format BCE inattendu : {list(df.columns)[:8]}")
    return _serie(df, "TIME_PERIOD", "OBS_VALUE")


def gscpi() -> pd.DataFrame:
    """Global Supply Chain Pressure Index (NY Fed), mensuel, en écarts-types."""
    feuilles = _lire_excel(fetch_bytes(URL_GSCPI, namespace=NS, ext="xlsx", ttl_days=7), "GSCPI")
    for brut in feuilles.values():
        for i in range(min(15, len(brut))):
            ligne = [str(x).strip().lower() for x in brut.iloc[i].tolist()]
            if "gscpi" in ligne:
                df = brut.iloc[i + 1:].copy()
                df.columns = ligne
                col_date = next((c for c in df.columns if "date" in c), df.columns[0])
                out = _serie(df, col_date, "gscpi")
                if len(out) > 24:
                    out["date"] = out["date"] + pd.offsets.MonthEnd(0)    # connu en fin de mois seulement
                    return out
    raise SourceError("colonne GSCPI introuvable dans le fichier de la NY Fed : son format a changé")


def _lire_oil_bulletin(contenu: bytes) -> pd.DataFrame:
    motif = re.compile(r"^([A-Z]{2})_price_with_tax_diesel$", re.I)
    for brut in _lire_excel(contenu, "Weekly Oil Bulletin").values():
        for i in range(min(10, len(brut))):
            entetes = [str(x).strip() for x in brut.iloc[i].tolist()]
            cols = {j: motif.match(h).group(1).upper() for j, h in enumerate(entetes) if motif.match(h)}
            if not cols:
                continue
            dates = pd.to_datetime(brut.iloc[i + 1:, 0], errors="coerce", format="mixed")
            morceaux = []
            for j, code in cols.items():
                v = pd.to_numeric(brut.iloc[i + 1:, j].astype(str).str.replace(",", "").str.replace(" ", ""), errors="coerce")
                morceaux.append(pd.DataFrame({"date": dates.to_numpy(), "pays": code, "valeur": v.to_numpy()}))
            out = pd.concat(morceaux).dropna()
            if out.empty:
                continue
            if out["valeur"].median() > 50:            # prix publiés en € pour 1 000 litres
                out["valeur"] = out["valeur"] / 1000
            return out.reset_index(drop=True)
    raise SourceError("colonnes « XX_price_with_tax_diesel » introuvables dans le fichier de la Commission")


def gazole_ue(pays: tuple = ("EU", "FR", "DE", "IT", "ES", "NL", "BE", "PL")) -> pd.DataFrame:
    """Prix du gazole à la pompe TTC par pays (€/L), hebdomadaire. Repli : data/manuel/oil_bulletin.csv."""
    manuel = manual_dir() / "oil_bulletin.csv"
    try:
        out = _lire_oil_bulletin(fetch_bytes(URL_OIL_HISTO, namespace=NS, ext="xlsx", ttl_days=7))
    except SourceError as e:
        if not manuel.exists():
            raise SourceError(f"{e}. Repli possible : panel « EU Weekly Oil Bulletin » de fuel-prices.eu dans {manuel}") from e
        df = pd.read_csv(manuel)
        df.columns = [c.strip().lower() for c in df.columns]
        if {"country_code", "week", "diesel_eur_l"} <= set(df.columns):
            df = df.rename(columns={"country_code": "pays", "week": "date", "diesel_eur_l": "valeur"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce")
        out = df[["date", "pays", "valeur"]].dropna()
    out = out[out["pays"].isin(pays)] if pays else out
    if out.empty:
        raise SourceError("aucun prix du gazole pour les pays demandés")
    return out.sort_values(["pays", "date"]).reset_index(drop=True)


def _pink_sheet() -> pd.DataFrame:
    """Feuille « Monthly Prices » du Pink Sheet (Banque mondiale) : une colonne par matière première."""
    page = fetch_bytes(URL_PINK_SHEET_PAGE, namespace=NS, ext="html", ttl_days=7).decode("utf-8", "ignore")
    m = re.search(r'https?://[^"\']*CMO-Historical-Data-Monthly\.xlsx', page)
    if not m:
        raise SourceError("lien du Pink Sheet introuvable sur la page de la Banque mondiale")
    feuilles = _lire_excel(fetch_bytes(m.group(0), namespace=NS, ext="xlsx", ttl_days=7), "Pink Sheet")
    brut = feuilles.get("Monthly Prices")
    if brut is None:
        raise SourceError("feuille « Monthly Prices » absente du Pink Sheet")
    ligne = next((i for i in range(12) if "Crude oil, Brent" in [str(x).strip() for x in brut.iloc[i].tolist()]), None)
    if ligne is None:
        raise SourceError("en-têtes du Pink Sheet introuvables : format changé")
    df = brut.iloc[ligne + 2:].copy()
    df.columns = ["periode"] + [str(x).strip() for x in brut.iloc[ligne, 1:].tolist()]
    df = df[df["periode"].astype(str).str.fullmatch(r"\d{4}M\d{2}")]
    # La valeur d'un mois n'est connue qu'à sa fin : on la date au dernier jour du mois (pas de fuite d'information).
    df["date"] = pd.to_datetime(df["periode"].astype(str).str.replace("M", "-"), format="%Y-%m") + pd.offsets.MonthEnd(0)
    return df


def banque_mondiale(nom: str) -> pd.DataFrame:
    """Prix mensuel d'une matière première (Pink Sheet), daté en fin de mois."""
    try:
        df = _pink_sheet()
        if nom not in df.columns:
            raise SourceError(f"série « {nom} » absente du Pink Sheet")
        return _serie(df, "date", nom)
    except SourceError as first:
        try:
            from worldbank_commodities import WorldBankCommodities   # repli : paquet utilisé par le notebook
        except ImportError:
            raise first
        try:
            df = WorldBankCommodities().get_prices(freq="monthly", commodities=nom)
        except Exception as e:
            raise SourceError(f"Banque mondiale indisponible ({type(e).__name__})") from e
        out = _serie(df, "date", "price")
        out["date"] = out["date"] + pd.offsets.MonthEnd(0)
        return out


def eurostat(code: str = "sts_inpp_m", **filtres) -> pd.DataFrame:
    """Série mensuelle Eurostat (JSON-stat). Défaut : prix de production de l'industrie manufacturière UE."""
    params = {"geo": "EU27_2020", "nace_r2": "C", "indic_bt": "PRC_PRR", "s_adj": "NSA", "unit": "I21", "lang": "en"}
    params.update(filtres)
    try:
        data = json.loads(fetch_bytes(URL_EUROSTAT.format(code=code), params, namespace=NS, ext="json", ttl_days=7))
    except ValueError as e:
        raise SourceError("réponse Eurostat illisible") from e
    if "value" not in data or "dimension" not in data:
        raise SourceError(f"Eurostat : réponse inattendue ({str(data)[:150]})")
    tailles = dict(zip(data["id"], data["size"]))
    if any(v > 1 for k, v in tailles.items() if k != "time"):
        raise SourceError(f"Eurostat : filtres insuffisants ({tailles})")
    temps, valeurs = data["dimension"]["time"]["category"]["index"], data["value"]
    lignes = [(t, valeurs.get(str(i)) if isinstance(valeurs, dict) else valeurs[i]) for t, i in temps.items()]
    df = pd.DataFrame(lignes, columns=["date", "valeur"])
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    return _serie(df, "date", "valeur")


def lire_csv_manuel(chemin: Path) -> pd.DataFrame:
    """CSV déposé à la main : une colonne date et une colonne valeur (ou Close, Price, Dernier, Prix...)."""
    df = pd.read_csv(chemin, sep=None, engine="python")
    df.columns = [str(c).strip().lower() for c in df.columns]
    col_date = next((c for c in df.columns if c in ("date", "datetime", "time", "jour", "week")), None)
    col_val = next((c for c in ("valeur", "adj close", "close", "price", "dernier", "prix", "price (eur/mwhe)") if c in df.columns), None)
    if col_val is None:
        col_val = next((c for c in df.columns if c != col_date and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.8), None)
    if col_date is None or col_val is None:
        raise SourceError(f"{chemin} : colonnes date et valeur introuvables")
    df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(",", ".", regex=False)
                                .str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
    df[col_date] = pd.to_datetime(df[col_date], errors="coerce", format="mixed")
    return _serie(df, col_date, col_val)


def charger_signal(signal: str, debut: str = DEBUT_DEFAUT, tickers: dict | None = None) -> pd.DataFrame:
    """Série brute (date, valeur) d'un signal du catalogue. `tickers` : cours de fournisseurs (bourse_<clé>)."""
    tickers = {**TICKERS, **(tickers or {})}
    if signal.startswith("bourse_"):
        cle = signal.split("_", 1)[1]
        chemin = manual_dir() / f"bourse_{cle}.csv"
        manuel = lire_csv_manuel(chemin) if chemin.exists() else None
        try:
            yahoo = marche(tickers[signal], debut)
        except (SourceError, KeyError):
            if manuel is None:
                raise SourceError(f"cours indisponible pour {cle}")
            return manuel.assign(segment=0)
        if manuel is None:
            return yahoo
        # l'historique manuel complète Yahoo avant sa première date ; segments séparés (pas de variation à cheval)
        avant = manuel[manuel["date"] < yahoo["date"].min()].assign(segment=0)
        return pd.concat([avant, yahoo.assign(segment=1)], ignore_index=True)
    if signal in tickers:
        return marche(tickers[signal], debut)
    if signal in BANQUE_MONDIALE:
        return banque_mondiale(BANQUE_MONDIALE[signal])
    if signal == "prix_production_EU":
        return eurostat()
    if signal in MANUELS:
        chemin = manual_dir() / f"{signal}.csv"
        if not chemin.exists():
            raise SourceError(f"fichier manuel absent : {chemin} (source : {MANUELS[signal]})")
        return lire_csv_manuel(chemin)
    if signal in DEVISES:
        return change(DEVISES[signal], debut)
    if signal == "gscpi":
        return gscpi()
    if signal.startswith("gazole_"):
        return gazole_ue((signal.split("_", 1)[1],))[["date", "valeur"]].reset_index(drop=True)
    raise SourceError(f"signal inconnu : {signal}")
