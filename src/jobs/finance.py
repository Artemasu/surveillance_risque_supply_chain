"""Tâches du volet Finance : collecte des signaux, indicateurs jour par jour, fiches fournisseurs, règles."""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.analytics import finance_indicators as fi
from src.analytics.thresholds import episodes
from src.connectors import registries as reg
from src.connectors.http_cache import SourceError
from src.connectors.markets import DEBUT_DEFAUT, gazole_ue
from src.storage import db

log = logging.getLogger("supplychain.jobs")


def store_catalog() -> None:
    cat = fi.all_signals()
    db.upsert("fin_signals", cat[["signal", "nom", "famille", "source", "freq", "sens", "horizon", "mesure", "q", "unite", "impact"]])


def store_series(series: dict[str, pd.DataFrame]) -> int:
    """Séries brutes -> fin_raw ; indicateurs, seuils et score recalibré -> indicators (agent finance)."""
    if not series:
        return 0
    raw = pd.concat([s[["date", "valeur"]].assign(signal=k) for k, s in series.items()], ignore_index=True)
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    raw = raw.dropna().drop_duplicates(["signal", "date"], keep="last")
    daily = fi.daily_table(series)
    with db.connect() as con:
        con.execute("DELETE FROM fin_raw WHERE signal IN (SELECT UNNEST(?))", [list(series)])
        db.upsert("fin_raw", raw[["signal", "date", "valeur"]], con)
        if len(daily):
            rows = pd.DataFrame({"agent": "finance", "series": daily["signal"], "indicator": "indicateur",
                                 "date": pd.to_datetime(daily["date"]).dt.date, "value": daily["valeur"],
                                 "threshold": daily["seuil"], "rank": daily["rang"], "alert": daily["alerte"].astype(bool)})
            rows.loc[rows["series"] == "_score", ["series", "indicator"]] = ["_global", "_score"]
            rows = rows[rows["value"].notna() | rows["alert"]]
            con.execute("DELETE FROM indicators WHERE agent='finance'")
            db.upsert("indicators", rows, con)
            # bruit : épisodes d'alerte par an et par signal
            years = max((daily["date"].max() - daily["date"].min()).days / 365.25, 1)
            noise = [{"agent": "finance", "series": sig, "indicator": "indicateur",
                      "episodes_per_year": round(len(episodes(g.set_index("date")["alerte"])) / years, 3)}
                     for sig, g in daily[daily["signal"] != "_score"].groupby("signal")]
            db.upsert("noise", pd.DataFrame(noise), con)
    return len(raw)


def store_suppliers(fiches: list[dict]) -> None:
    now = datetime.now()
    db.upsert("fin_suppliers", pd.DataFrame([{"cle": f["cle"], "nom": f["fournisseur"], "pays": f["pays"],
                                              "en_alerte": bool(f.get("en_alerte")), "payload": db.dumps(f),
                                              "updated_at": now} for f in fiches]))


def store_rules(regles: pd.DataFrame) -> None:
    if regles.empty:
        return
    df = regles.copy()
    df["id"] = df.apply(lambda r: str(r.get("document") or "") or f"{r['zone']}:{r['publication']}:{str(r['titre'])[:40]}", axis=1)
    out = pd.DataFrame({"id": df["id"], "zone": df["zone"], "famille": df.get("famille", df.get("terme")),
                        "publication": pd.to_datetime(df["publication"], errors="coerce").dt.date,
                        "entree_en_vigueur": pd.to_datetime(df["entree_en_vigueur"], errors="coerce").dt.date,
                        "titre": df["titre"], "effet": df.get("effet"), "url": df["url"], "delai_jours": df["delai_jours"]})
    db.upsert("fin_rules", out.drop_duplicates("id"))


# --------------------------------------------------------------------------- collecte live
def ingest(debut: str = DEBUT_DEFAUT, suppliers: bool = True, rules: bool = True) -> dict:
    """Tous les signaux, fiches fournisseurs, règles et gazole par pays, enregistrés dans la base."""
    store_catalog()
    sigs = list(fi.all_signals()["signal"])
    _, series, etat = fi.market_signals_status(sigs, date.today(), debut)
    n = store_series(series)
    bilan = {"signaux": len(sigs), "lus": len(series), "valeurs": n,
             "echecs": {k: v["detail"] for k, v in etat.items() if v["status"] != "ok"}}
    try:
        g = gazole_ue()
        db.upsert("fin_diesel", g.assign(date=g["date"].dt.date)[["pays", "date", "valeur"]].drop_duplicates(["pays", "date"]))
        bilan["gazole_pays"] = int(g["pays"].nunique())
    except SourceError as e:
        bilan["gazole_pays"] = f"✗ {e}"
    if rules:
        store_rules(reg.regles())
    if suppliers:
        listes, etat_s = reg.listes_sanctions()
        fiches = []
        for cle in reg.FOURNISSEURS["cle"]:
            try:
                fiches.append(fi.supplier_sheet(cle, date.today(), listes))
            except Exception as e:
                bilan.setdefault("echecs", {})[f"fiche {cle}"] = str(e)[:120]
        store_suppliers(fiches)
        bilan["fournisseurs"] = len(fiches)
        bilan["listes_sanctions"] = etat_s
    rows = [{"source_id": f"finance:{k}", "agent": "finance", "provider": k, "status": v["status"],
             "detail": v.get("detail") or v.get("derniere"), "checked_at": datetime.now()} for k, v in etat.items()]
    db.upsert("sources", pd.DataFrame(rows))
    return bilan


# --------------------------------------------------------------------------- import du notebook
def import_notebook(folder: Path) -> dict:
    """Sorties de `finance_signaux.ipynb` -> base (sans réseau) : séries brutes, indicateurs, fournisseurs, règles."""
    sorties = folder / "finance" / "sorties"
    store_catalog()
    out = {}
    brut = pd.read_csv(sorties / "finance_brut.csv", parse_dates=["date"])
    series = {sig: g[["date", "valeur"]].sort_values("date").reset_index(drop=True) for sig, g in brut.groupby("signal")}
    out["valeurs"] = store_series(series)
    out["signaux"] = len(series)
    f = sorties / "finance_fournisseurs.csv"
    if f.exists():
        four = pd.read_csv(f)
        fiches = []
        by_name = {r.nom: r.cle for r in reg.FOURNISSEURS.itertuples()}
        for r in four.astype(object).where(pd.notna(four), None).to_dict("records"):
            cle = by_name.get(r["fournisseur"])
            if not cle:
                continue
            meta = reg.fournisseur(cle)
            fiches.append({"cle": cle, "fournisseur": r["fournisseur"], "nom_legal": meta["nom_legal"], "pays": r["pays"],
                           "produit": meta["produit"], "ticker": meta["ticker"], "siren": meta["siren"],
                           "date": None, "en_alerte": str(r["en_alerte"]).lower() == "true",
                           "alertes": [a for a in str(r.get("alertes") or "").split(";") if a.strip()],
                           "bourse": None if r.get("bourse_20j_%") is None else {"variation_20j_%": float(r["bourse_20j_%"])},
                           "proprietaires": [] if r.get("maisons_meres") in (None, "-") else
                           [{"type": "ultime", "nom": n.strip(), "lei": None} for n in str(r["maisons_meres"]).split(",")],
                           "sanctions_count": int(r.get("sanctions") or 0), "sanctions": [],
                           "procedures_collectives": [], "donnees_manquantes": [], "origine": "notebook"})
        store_suppliers(fiches)
        out["fournisseurs"] = len(fiches)
    f = sorties / "finance_regles.csv"
    if f.exists():
        r = pd.read_csv(f)
        r["titre"] = r["titre"].fillna(r.get("regle"))
        store_rules(r)
        out["regles"] = len(r)
    f = sorties / "finance_gazole_pays.csv"
    if f.exists():
        g = pd.read_csv(f, parse_dates=["date"])
        db.upsert("fin_diesel", g.assign(date=g["date"].dt.date)[["pays", "date", "valeur"]].drop_duplicates(["pays", "date"]))
    f = sorties / "finance_transmission_brent_gazole.csv"
    if f.exists():
        db.upsert("fin_transmission", pd.read_csv(f)[["pays", "decalage_semaines", "correlation"]])
    f = sorties / "finance_validation_cas.csv"
    if f.exists():
        v = pd.read_csv(f)
        db.upsert("validation", pd.DataFrame({
            "agent": "finance", "cas": v["cas"], "cible": v["signal"], "indicator": v["type"],
            "detected": v["alerte_avant_impact"].astype(bool), "lead_days": v["jours_avance"],
            "payload": [db.dumps(x) for x in v.astype(object).where(pd.notna(v), None).to_dict("records")]
        }).drop_duplicates(["agent", "cas", "cible", "indicator"]))
        out["cas_valides"] = len(v)
    return out


def latest_situations(jour: Optional[str] = None) -> list[dict]:
    """Situation de chaque signal à une date, calculée depuis la base (sans réseau)."""
    raw = db.query("SELECT signal, date, valeur FROM fin_raw ORDER BY signal, date")
    if raw.empty:
        return []
    raw["date"] = pd.to_datetime(raw["date"])
    j = pd.Timestamp(jour or date.today())
    out = []
    for sig, g in raw.groupby("signal"):
        try:
            sit = fi.situation(sig, g[["date", "valeur"]].reset_index(drop=True), j)
        except KeyError:
            continue
        if sit:
            out.append(sit)
    return out


def _nan_none(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x
