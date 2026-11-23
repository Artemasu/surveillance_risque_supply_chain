"""Indicateurs finance, seuils et fiches fournisseurs — méthode du notebook `finance_signaux.ipynb`.

    indicateur    variation en % sur `horizon` observations (≈ 4 semaines), ou niveau brut (GSCPI)
    seuil         quantile des variations sur 2010-2020 (1 % des plus fortes en quotidien, 5 % en hebdo/mensuel)
    situation     dernière valeur connue À une date, jamais après (pas de fuite d'information)
    score_finance maximum des rangs du jour, RECALIBRÉ comme le score météo (dans le notebook il ne l'était pas :
                  avec 17 signaux, un jour ordinaire valait déjà ~0,9 ; les deux scores sont maintenant comparables)
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from src.analytics.thresholds import (calibration_values, is_alert, level_of_rank, rank_of, ranks, recalibrated_score,
                                      threshold)
from src.connectors import registries as reg
from src.connectors.http_cache import SourceError
from src.connectors.markets import DEBUT_DEFAUT, FIN_CALIBRATION, MANUELS, SIGNAUX, charger_signal

FFILL_LIMIT = {"J": 5, "S": 10, "M": 40}       # une série hebdo ou mensuelle garde sa dernière valeur ce nombre de jours


def supplier_signals() -> pd.DataFrame:
    rows = [(f"bourse_{f.cle}", f"Bourse : {f.nom}", "fournisseurs", f"yfinance {f.ticker}", "J", "bas", 20, "variation",
             0.99, "cours", f"{f.produit} : fournisseur en difficulté, faillite possible")
            for f in reg.FOURNISSEURS.itertuples() if isinstance(f.ticker, str)]
    return pd.DataFrame(rows, columns=SIGNAUX.columns)


def all_signals() -> pd.DataFrame:
    return pd.concat([SIGNAUX, supplier_signals()], ignore_index=True)


def catalog(signal: str) -> dict:
    cat = all_signals().set_index("signal")
    base = signal if signal in cat.index else ("gazole_EU" if signal.startswith("gazole_") else None)
    if base is None:
        raise KeyError(f"signal inconnu : {signal}")
    row = cat.loc[base].to_dict()
    row["signal"] = signal
    if signal != base:
        row["nom"] = f"Gazole à la pompe, {signal.split('_', 1)[1]}"
    return row


def indicator(serie: pd.DataFrame, mesure: str, horizon: int) -> pd.Series:
    v = serie.set_index("date")["valeur"].astype(float)
    if mesure == "niveau":
        return v
    if "segment" in serie:          # deux historiques collés : pas de variation à cheval sur la jonction
        return 100 * v.groupby(serie["segment"].to_numpy()).pct_change(horizon, fill_method=None)
    return 100 * v.pct_change(horizon, fill_method=None)


def load(signal: str, debut: str = DEBUT_DEFAUT) -> pd.DataFrame:
    return charger_signal(signal, debut, tickers=reg.supplier_tickers())


def situation(signal: str, serie: pd.DataFrame, jour: pd.Timestamp) -> Optional[dict]:
    """Dernière valeur connue à `jour`, son seuil, son rang et si elle est en alerte."""
    s = catalog(signal)
    brut = serie[serie["date"] <= jour]
    ind = indicator(brut, s["mesure"], int(s["horizon"])).dropna()
    if ind.empty:
        return None
    calib = calibration_values(ind, FIN_CALIBRATION)
    sl = threshold(calib, s["sens"], float(s["q"]))
    d, val = ind.index[-1], float(ind.iloc[-1])
    rank = rank_of(val, calib, s["sens"])
    source = str(s["source"]).split()[0].lower()
    return {"signal": signal, "nom": s["nom"], "famille": s["famille"], "date_valeur": str(d.date()),
            "valeur_brute": round(float(brut["valeur"].iloc[-1]), 4), "indicateur": round(val, 2),
            "mesure": "variation_%" if s["mesure"] == "variation" else "niveau", "horizon": int(s["horizon"]),
            "seuil": None if pd.isna(sl) else round(sl, 2), "sens": s["sens"], "en_alerte": is_alert(val, sl, s["sens"]),
            "rang": rank, "niveau": level_of_rank(rank), "unite": s["unite"], "impact": s["impact"],
            "source": s["source"], "source_id": f"{source}:{signal}:{d.date()}"}


def daily_table(series: dict[str, pd.DataFrame], fin: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Calendrier quotidien commun (format long) : indicateur, seuil, alerte, rang par signal ; puis le score."""
    fin = pd.Timestamp(fin or date.today())
    if not series:
        return pd.DataFrame()
    inds = {}
    for sig, serie in series.items():
        s = catalog(sig)
        inds[sig] = (indicator(serie, s["mesure"], int(s["horizon"])).dropna(), s)
    start = max(pd.Timestamp("2010-01-01"), min(i.index.min() for i, _ in inds.values() if len(i)))
    cal = pd.date_range(start, fin, freq="D")
    rows, rank_cols = [], {}
    for sig, (ind, s) in inds.items():
        if ind.empty:
            continue
        ind = ind[~ind.index.duplicated(keep="last")]
        serie = ind.reindex(cal, method="ffill", limit=FFILL_LIMIT[s["freq"]])
        calib = calibration_values(ind, FIN_CALIBRATION)
        sl = threshold(calib, s["sens"], float(s["q"]))
        r = ranks(serie.to_numpy(), calib, s["sens"])
        rank_cols[sig] = r
        rows.append(pd.DataFrame({"date": cal, "signal": sig, "valeur": serie.to_numpy(), "seuil": sl,
                                  "alerte": is_alert(serie, sl, s["sens"]).to_numpy(), "rang": r}))
    long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    rmax = pd.DataFrame(rank_cols, index=cal).max(axis=1)
    score = recalibrated_score(rmax, pd.Series(cal <= pd.Timestamp(FIN_CALIBRATION), index=cal))
    alerts = long.groupby("date")["alerte"].any() if len(long) else pd.Series(False, index=cal)
    score_df = pd.DataFrame({"date": cal, "signal": "_score", "valeur": score.to_numpy(), "seuil": np.nan,
                             "alerte": alerts.reindex(cal).fillna(False).to_numpy(), "rang": rmax.to_numpy()})
    return pd.concat([long, score_df], ignore_index=True)


def episode_start(serie: pd.DataFrame, signal: str, jour: pd.Timestamp, lookback: int = 120) -> Optional[str]:
    """Premier jour de l'épisode d'alerte en cours (à `jour`), pour dater l'événement au premier signal."""
    s = catalog(signal)
    ind = indicator(serie[serie["date"] <= jour], s["mesure"], int(s["horizon"])).dropna()
    if ind.empty:
        return None
    sl = threshold(calibration_values(ind, FIN_CALIBRATION), s["sens"], float(s["q"]))
    flags = is_alert(ind, sl, s["sens"])
    flags = flags[flags.index >= jour - pd.Timedelta(days=lookback)]
    if flags.empty or not bool(flags.iloc[-1]):
        return None
    k = len(flags) - 1
    while k > 0 and bool(flags.iloc[k - 1]):
        k -= 1
    return str(flags.index[k].date())


def supplier_sheet(cle: str, date_cible=None, listes: Optional[pd.DataFrame] = None) -> dict:
    """Ce qu'on sait d'un fournisseur à une date : bourse, maisons mères, sanctions, procédures collectives."""
    jour = pd.Timestamp(date_cible or date.today())
    f = reg.fournisseur(cle)
    fiche = {"cle": cle, "fournisseur": f["nom"], "nom_legal": f["nom_legal"], "pays": f["pays"], "produit": f["produit"],
             "ticker": f["ticker"], "siren": f["siren"], "date": str(jour.date()), "alertes": [], "donnees_manquantes": [],
             "bourse": None, "proprietaires": [], "lei": None, "sanctions": [], "procedures_collectives": [],
             "sources_lues": []}
    if f["ticker"]:
        try:
            sit = situation(f"bourse_{cle}", load(f"bourse_{cle}"), jour)
            fiche["sources_lues"].append("bourse")
            if sit:
                fiche["bourse"] = {"variation_20j_%": sit["indicateur"], "seuil": sit["seuil"], "en_alerte": sit["en_alerte"],
                                   "rang": sit["rang"], "date_valeur": sit["date_valeur"], "cours": sit["valeur_brute"],
                                   "source_id": sit["source_id"]}
                if sit["en_alerte"]:
                    fiche["alertes"].append(f"chute de l'action : {sit['indicateur']:.0f} % en 20 séances")
        except SourceError:
            fiche["donnees_manquantes"].append("bourse")
    try:
        fiche["proprietaires"], fiche["lei"], gleif_ok = reg.proprietaires(f["nom_legal"])
    except Exception:                                   # réponse GLEIF inattendue : on continue sans
        gleif_ok = False
    fiche["sources_lues" if gleif_ok else "donnees_manquantes"].append("gleif")
    if listes is None:
        listes, _ = reg.listes_sanctions()
    if not listes.empty:
        fiche["sources_lues"].append("sanctions")
    touchees = []
    for nom, role in [(f["nom_legal"], "lui-même")] + [(p["nom"], f"maison mère {p['type']}") for p in fiche["proprietaires"]]:
        c = reg.correspondances(nom, listes)
        c = c[c["date_inscription"].isna() | (c["date_inscription"] <= jour)]
        for r in c.itertuples():
            touchees.append({"entite": nom, "role": role, "liste": r.liste, "nom_sur_liste": r.nom,
                             "date_inscription": None if pd.isna(r.date_inscription) else str(r.date_inscription.date()),
                             "source_id": r.source_id})
    fiche["sanctions"] = touchees
    if listes.empty:
        fiche["donnees_manquantes"].append("sanctions")
    if touchees:
        fiche["alertes"].append("sanction sur " + ", ".join(sorted({t["role"] for t in touchees})))
    if f["siren"]:
        try:
            b = reg.bodacc(f["siren"])
            fiche["sources_lues"].append("bodacc")
            b = b[b["date"] <= jour]
            fiche["procedures_collectives"] = b.assign(date=b["date"].dt.date.astype(str)).to_dict("records")
            if len(b):
                fiche["alertes"].append(f"procédure collective publiée au BODACC le {b['date'].max().date()}")
        except SourceError:
            fiche["donnees_manquantes"].append("bodacc")
    fiche["en_alerte"] = bool(fiche["alertes"])
    return fiche


def market_signals_status(signals: Iterable[str], jour=None, debut: str = DEBUT_DEFAUT) -> tuple[list[dict], dict, dict]:
    """Situation de chaque signal à `jour` ; renvoie (situations, séries chargées, état des sources)."""
    jour = pd.Timestamp(jour or date.today())
    out, series, etat = [], {}, {}
    for sig in dict.fromkeys(signals):
        try:
            serie = load(sig, debut)
        except SourceError as e:
            base = "gazole_EU" if sig.startswith("gazole_") else sig
            etat[sig] = {"status": "unavailable" if base in MANUELS else "failed", "detail": str(e)[:160]}
            continue
        series[sig] = serie
        sit = situation(sig, serie, jour)
        if sit is None:
            etat[sig] = {"status": "partial", "detail": "aucune valeur à cette date"}
            continue
        etat[sig] = {"status": "ok", "valeurs": len(serie), "derniere": sit["date_valeur"]}
        out.append(sit)
    return out, series, etat
