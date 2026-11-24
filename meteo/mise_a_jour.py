"""
mise_a_jour.py - Mise à jour quotidienne de la base météo (data/meteo.db)

Pour chaque site de la base, récupère les jours manquants depuis la dernière mise à jour,
recalcule les indicateurs, les alertes et le score avec LES MÊMES SEUILS que le notebook,
et renouvelle les alertes prévues pour les 16 prochains jours.

    python mise_a_jour.py                      # mise à jour immédiate
    python mise_a_jour.py --planifier 18:00    # mise à jour automatique chaque jour à 18 h (Windows)
    python mise_a_jour.py --deplanifier        # supprimer la tâche planifiée

Sources : observation ERA5 jusqu'à J-6 (délai de la réanalyse), puis prévision pour les jours
récents (lignes marquées « prevision (provisoire) », remplacées par ERA5 les jours suivants)
et pour les 16 prochains jours (alertes de type « prevision »).
Le déroulement est écrit dans data/mise_a_jour.log.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DOSSIER = Path(__file__).resolve().parent
os.chdir(DOSSIER)          # la tâche planifiée démarre ailleurs : on se place dans le dossier meteo

import base_meteo  # noqa: E402
import meteo_collecte as mc  # noqa: E402

NOM_TACHE = "Projet6 - mise a jour meteo"
JOURNAL = DOSSIER / "data" / "mise_a_jour.log"
FIN_CALIBRATION = "2020-12-31"   # comme dans le notebook : les seuils viennent de 2010-2020
PLANCHER = {"neige": 1.0}        # en dessous d'1 cm, la neige ne bloque rien (notebook)
HISTORIQUE_J = 100               # jours d'historique relus pour les cumuls sur 90 jours
COLONNES_BRUTES = [base_meteo.RENOMMAGE[v] for v in mc.VARIABLES_JOUR] + ["debit_m3s"]


def journal(message: str) -> None:
    ligne = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    print(ligne)
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(ligne + "\n")


# --------------------------------------------------------------------------- calculs (identiques au notebook)
def ajouter_indicateurs(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()
    df["pluie_3j_mm"] = df["pluie_mm"].rolling(3, min_periods=3).sum()
    df["pluie_90j_mm"] = df["pluie_mm"].rolling(90, min_periods=80).sum()
    df["temp_min_3j_c"] = df["temperature_min_c"].rolling(3, min_periods=3).min()
    df["debit_7j_m3s"] = df["debit_m3s"].rolling(7, min_periods=5).mean()
    return df


def depasse(valeurs: pd.Series, seuil: float, indicateur: str, sens: str) -> pd.Series:
    if sens == "haut":
        return (valeurs > seuil) & (valeurs >= PLANCHER.get(indicateur, -np.inf))
    return valeurs < seuil


def rang(valeurs: np.ndarray, reference: np.ndarray, indicateur: str, sens: str) -> np.ndarray:
    if sens == "haut":
        r = np.searchsorted(reference, valeurs, side="left") / len(reference)
        r = np.where(valeurs < PLANCHER.get(indicateur, -np.inf), 0.0, r)
    else:
        r = 1 - np.searchsorted(reference, valeurs, side="right") / len(reference)
    return np.where(np.isnan(valeurs), np.nan, r)


class Regles:
    """Seuils, indicateurs suivis et références de calibration d'un site, lus dans la base."""

    def __init__(self, cx: sqlite3.Connection, site: str, suivis: set[str]):
        ind = pd.read_sql("SELECT indicateur, variable, sens, unite, risque FROM indicateurs", cx)
        seuils = dict(cx.execute("SELECT indicateur, seuil FROM seuils WHERE site = ?", (site,)).fetchall())
        self.liste = [r for r in ind.itertuples() if r.indicateur in suivis and r.indicateur in seuils]
        self.seuils = seuils
        calib = pd.read_sql("SELECT * FROM meteo_jour WHERE site = ? AND date <= ?", cx, params=(site, FIN_CALIBRATION))
        self.ref = {r.indicateur: np.sort(calib[r.variable].dropna().to_numpy()) for r in self.liste
                    if r.variable in calib}
        rmax = self._rang_max(calib)
        self.ref_score = np.sort(rmax[~np.isnan(rmax)])

    def _rang_max(self, df: pd.DataFrame) -> np.ndarray:
        rangs = [rang(df[r.variable].to_numpy(dtype=float), self.ref[r.indicateur], r.indicateur, r.sens)
                 for r in self.liste if len(self.ref.get(r.indicateur, [])) and r.variable in df]
        if not rangs:
            return np.full(len(df), np.nan)
        pile = np.vstack(rangs)
        with np.errstate(all="ignore"):
            return np.where(np.isnan(pile).all(axis=0), np.nan, np.nanmax(np.where(np.isnan(pile), -1, pile), axis=0))

    def score(self, df: pd.DataFrame) -> np.ndarray:
        v = self._rang_max(df)
        if not len(self.ref_score):
            return np.full(len(df), np.nan)
        return np.where(np.isnan(v), np.nan, np.searchsorted(self.ref_score, v, side="left") / len(self.ref_score))

    def alertes(self, df: pd.DataFrame, site: str, type_: str) -> pd.DataFrame:
        lignes = []
        for r in self.liste:
            s = self.seuils[r.indicateur]
            touche = df[depasse(df[r.variable], s, r.indicateur, r.sens).fillna(False)]
            for _, j in touche.iterrows():
                lignes.append({"site": site, "date": j["date"], "indicateur": r.indicateur,
                               "valeur": round(float(j[r.variable]), 2), "seuil": round(float(s), 2),
                               "unite": r.unite, "risque": r.risque, "type": type_})
        return pd.DataFrame(lignes, columns=list(base_meteo.SCHEMA["alertes"][1]))


# --------------------------------------------------------------------------- collecte
def _telecharger(site, debut: date, aujourd_hui: date) -> pd.DataFrame:
    """Jours debut -> J+15 : ERA5 jusqu'à J-6, puis prévision."""
    morceaux = []
    fin_era5 = aujourd_hui - timedelta(days=mc.RETARD_ERA5)
    debut_prev = debut
    if debut <= fin_era5:
        era5 = mc.historique(site.lat, site.lon, debut, fin_era5)
        era5 = era5[era5.drop(columns="date").notna().any(axis=1)]   # derniers jours ERA5 parfois vides
        if len(era5):
            morceaux.append(era5.assign(source="ERA5"))
            debut_prev = era5["date"].max().date() + timedelta(days=1)
    fin = aujourd_hui + timedelta(days=mc.HORIZON_PREVISION)
    try:
        prev = mc.prevision(site.lat, site.lon, debut=debut_prev, fin=fin)
    except mc.ErreurReseau:
        raise
    except mc.ErreurMeteo:   # trou trop ancien pour l'API de prévision : historique des prévisions
        hier = aujourd_hui - timedelta(days=1)
        prev = pd.concat([mc._quotidien(mc.URL_HIST_PREVISION, site.lat, site.lon, debut_prev, hier, mc.VARIABLES_JOUR),
                          mc.prevision(site.lat, site.lon, debut=aujourd_hui, fin=fin)])
    morceaux.append(prev.assign(source="prevision (provisoire)"))
    df = pd.concat(morceaux, ignore_index=True).rename(columns=base_meteo.RENOMMAGE)
    df["debit_m3s"] = np.nan
    if site.fluvial and pd.notna(site.lat_debit):
        for fin_debit in (fin, aujourd_hui):        # GloFAS : avec prévision si possible
            try:
                d = mc.debit(site.lat_debit, site.lon_debit, debut, fin_debit)
                df = df.drop(columns="debit_m3s").merge(
                    d.rename(columns={"river_discharge": "debit_m3s"})[["date", "debit_m3s"]], on="date", how="left")
                break
            except mc.ErreurReseau:
                raise
            except mc.ErreurMeteo:
                continue
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def mettre_a_jour_site(cx: sqlite3.Connection, site, aujourd_hui: date) -> str:
    derniere = cx.execute("SELECT MAX(date) FROM meteo_jour WHERE site = ? AND source = 'ERA5'",
                          (site.site,)).fetchone()[0]
    debut = date.fromisoformat(derniere) + timedelta(days=1)
    nouveau = _telecharger(site, debut, aujourd_hui)

    passe = pd.read_sql(f"SELECT date, {', '.join(COLONNES_BRUTES)} FROM meteo_jour WHERE site = ? AND date < ? "
                        "ORDER BY date DESC LIMIT ?", cx, params=(site.site, debut.isoformat(), HISTORIQUE_J))
    complet = ajouter_indicateurs(pd.concat([passe, nouveau], ignore_index=True))
    complet = complet[complet["date"] >= debut.isoformat()].copy()

    regles = Regles(cx, site.site, {i.strip() for i in str(site.indicateurs_suivis).split(",")})
    complet["score_meteo"] = np.round(regles.score(complet), 3)
    observe = complet[complet["date"] <= aujourd_hui.isoformat()].copy()
    futur = complet[complet["date"] > aujourd_hui.isoformat()]
    alertes_obs = regles.alertes(observe, site.site, "observation")
    alertes_prev = regles.alertes(futur, site.site, "prevision")
    observe["alerte_meteo"] = observe["date"].isin(alertes_obs["date"]).astype(int)
    observe.insert(0, "site", site.site)
    colonnes = [r[1] for r in cx.execute("PRAGMA table_info(meteo_jour)")]
    observe = observe[[c for c in colonnes if c in observe.columns]]

    # remplacement : les jours provisoires des mises à jour précédentes sont recalculés
    cx.execute("DELETE FROM meteo_jour WHERE site = ? AND date >= ?", (site.site, debut.isoformat()))
    cx.execute("DELETE FROM alertes WHERE site = ? AND (type = 'prevision' OR date >= ?)",
               (site.site, debut.isoformat()))
    observe.to_sql("meteo_jour", cx, if_exists="append", index=False)
    pd.concat([alertes_obs, alertes_prev]).to_sql("alertes", cx, if_exists="append", index=False)
    era5 = (observe["source"] == "ERA5").sum()
    return (f"{len(observe)} jour(s) dont {era5} ERA5, {len(alertes_obs)} alerte(s) observée(s), "
            f"{len(alertes_prev)} alerte(s) prévue(s)")


def mettre_a_jour() -> int:
    if not base_meteo.CHEMIN_BASE.exists():
        journal("Base absente : lancez d'abord « python base_meteo.py ».")
        return 1
    aujourd_hui = date.today()
    journal(f"Début de la mise à jour ({aujourd_hui})")
    echecs, reussis = 0, 0
    with closing(sqlite3.connect(base_meteo.CHEMIN_BASE)) as cx:
        if "source" not in [r[1] for r in cx.execute("PRAGMA table_info(meteo_jour)")]:
            journal("Base construite avec une ancienne version : relancez « python base_meteo.py » puis réessayez.")
            return 1
        sites = pd.read_sql("SELECT * FROM sites", cx)
        for site in sites.itertuples():
            try:
                resume = mettre_a_jour_site(cx, site, aujourd_hui)
                cx.commit()                       # site par site : un échec n'annule pas les autres
                reussis += 1
                journal(f"  {site.site:<14} ✓ {resume}")
            except mc.ErreurReseau as e:
                cx.rollback()
                journal(f"  {site.site:<14} ✗ réseau : {e}")
                echecs += 1
                break                             # inutile d'essayer les autres sites sans réseau
            except Exception as e:                # on note l'erreur et on passe au site suivant
                cx.rollback()
                journal(f"  {site.site:<14} ✗ {type(e).__name__} : {e}")
                echecs += 1
        dernier = cx.execute("SELECT MAX(date) FROM meteo_jour").fetchone()[0]
        for cle, valeur in (("derniere_mise_a_jour", datetime.now().isoformat(timespec="seconds")),
                            ("dernier_jour", dernier)):
            cx.execute("DELETE FROM informations WHERE cle = ?", (cle,))
            cx.execute("INSERT INTO informations (cle, valeur) VALUES (?, ?)", (cle, valeur))
        cx.commit()
    journal(f"Fin : {reussis} site(s) à jour sur {len(sites)}, données jusqu'au {dernier}")
    return 0 if reussis == len(sites) else 1


# --------------------------------------------------------------------------- planification Windows
def _powershell(script: str) -> int:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr.strip() or r.stdout.strip())
    return r.returncode


def planifier(heure: str) -> int:
    if os.name != "nt":
        print("La planification automatique est prévue pour Windows. Sous Linux/macOS, utilisez cron :")
        print(f"  0 18 * * * cd '{DOSSIER}' && '{sys.executable}' mise_a_jour.py")
        return 1
    python = Path(sys.executable)
    sans_fenetre = python.with_name("pythonw.exe")       # pas de fenêtre noire à 18 h
    if sans_fenetre.exists():
        python = sans_fenetre
    script = (
        f"$a = New-ScheduledTaskAction -Execute '{python}' -Argument '\"{DOSSIER / 'mise_a_jour.py'}\"' "
        f"-WorkingDirectory '{DOSSIER}'; "
        f"$t = New-ScheduledTaskTrigger -Daily -At '{heure}'; "
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30); "
        f"Register-ScheduledTask -TaskName '{NOM_TACHE}' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
    )
    if _powershell(script) == 0:
        print(f"✓ Tâche « {NOM_TACHE} » créée : chaque jour à {heure}.")
        print("  Si l'ordinateur est éteint à cette heure, elle s'exécute au prochain démarrage.")
        print(f"  Suivi : {JOURNAL}")
        return 0
    return 1


def deplanifier() -> int:
    code = _powershell(f"Unregister-ScheduledTask -TaskName '{NOM_TACHE}' -Confirm:$false")
    print("✓ Tâche supprimée." if code == 0 else "Tâche introuvable ou suppression refusée.")
    return code


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mise à jour quotidienne de la base météo")
    p.add_argument("--planifier", metavar="HH:MM", help="créer la tâche Windows quotidienne (ex. 18:00)")
    p.add_argument("--deplanifier", action="store_true", help="supprimer la tâche Windows")
    a = p.parse_args()
    if a.planifier:
        sys.exit(planifier(a.planifier))
    if a.deplanifier:
        sys.exit(deplanifier())
    sys.exit(mettre_a_jour())
