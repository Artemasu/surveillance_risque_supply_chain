"""
Outils que le LLM peut appeler. Le LLM ne touche jamais directement aux données :
il demande un outil, le code Python l'exécute, et le résultat lui est renvoyé.

Ajouter un outil = écrire une fonction et la décorer avec @outil(...) :

    @outil("nom_outil", "Ce que fait l'outil (le LLM lit cette phrase pour décider de l'utiliser).",
           {"site": {"type": "string", "description": "nom du site"}}, obligatoires=["site"])
    def nom_outil(site):
        return {...}          # un dict sérialisable en JSON

Puis ajouter son nom dans la liste d'outils de l'agent (creer_agent_meteo, dans agent.py).

Outils actuels : lister_alertes, profil_site, executer_sql, decrire_base.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import base_meteo

REGISTRE: dict[str, dict] = {}
MAX_LIGNES = 100          # lignes renvoyées au LLM au maximum (le reste est résumé)
DELAI_SQL_S = 5           # une requête plus longue est interrompue


def outil(nom: str, description: str, proprietes: dict, obligatoires: list[str] | None = None):
    def enregistrer(fonction):
        REGISTRE[nom] = {"nom": nom, "description": description, "fonction": fonction,
                         "parametres": {"type": "object", "properties": proprietes,
                                        "required": obligatoires or []}}
        return fonction
    return enregistrer


def schemas(noms: list[str]) -> list[dict]:
    return [{k: REGISTRE[n][k] for k in ("nom", "description", "parametres")} for n in noms]


def executer(nom: str, arguments: dict) -> dict:
    """Exécute un outil et renvoie toujours un dict (une erreur devient {"erreur": ...} que le LLM peut lire)."""
    if nom not in REGISTRE:
        return {"erreur": f"Outil inconnu : {nom}. Outils disponibles : {', '.join(REGISTRE)}"}
    try:
        return REGISTRE[nom]["fonction"](**(arguments or {}))
    except TypeError as e:
        return {"erreur": f"Arguments invalides pour {nom} : {e}"}
    except Exception as e:  # l'erreur est renvoyée au LLM, qui peut corriger sa requête
        return {"erreur": f"{type(e).__name__} : {e}"}


# --------------------------------------------------------------------------- accès à la base (lecture seule)
def _connexion() -> sqlite3.Connection:
    chemin = Path(base_meteo.CHEMIN_BASE)
    if not chemin.exists():
        raise FileNotFoundError(f"Base absente ({chemin}) : lancez « python base_meteo.py ».")
    cx = sqlite3.connect(f"file:{chemin.resolve().as_posix()}?mode=ro", uri=True)
    cx.execute("PRAGMA query_only = ON")
    debut = time.monotonic()
    cx.set_progress_handler(lambda: int(time.monotonic() - debut > DELAI_SQL_S), 10_000)
    return cx


def _source_id(texte: str) -> str:
    return "base_meteo:sql:" + hashlib.md5(texte.encode()).hexdigest()[:10]


def _lire(requete: str, parametres: tuple = ()) -> dict:
    with closing(_connexion()) as cx:
        curseur = cx.execute(requete, parametres)
        colonnes = [d[0] for d in curseur.description]
        lignes = curseur.fetchmany(MAX_LIGNES + 1)
    tronque = len(lignes) > MAX_LIGNES
    return {"colonnes": colonnes, "lignes": [list(l) for l in lignes[:MAX_LIGNES]],
            "nb_lignes": min(len(lignes), MAX_LIGNES), "tronque": tronque,
            "source_id": _source_id(requete + json.dumps(parametres, default=str)),
            **({"remarque": f"Résultat limité aux {MAX_LIGNES} premières lignes : agréger pour tout couvrir."}
               if tronque else {})}


_INTERDIT = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum)\b", re.I)


# --------------------------------------------------------------------------- les outils
@outil("decrire_base",
       "Décrit les tables et colonnes de la base météo, la période couverte et la liste des sites. "
       "À utiliser en cas de doute sur un nom de colonne ou de site.", {})
def decrire_base():
    return {"schema": base_meteo.decrire_schema()}


@outil("executer_sql",
       "Exécute UNE requête SQL SELECT (SQLite) sur la base météo et renvoie le résultat "
       f"(au plus {MAX_LIGNES} lignes : agréger avec GROUP BY, MAX, AVG, COUNT plutôt que tout lister).",
       {"requete": {"type": "string", "description": "requête SELECT en SQLite"}}, ["requete"])
def executer_sql(requete: str):
    requete = requete.strip().rstrip(";").strip()
    if ";" in requete:
        return {"erreur": "Une seule requête à la fois."}
    if not re.match(r"^(select|with)\b", requete, re.I) or _INTERDIT.search(requete):
        return {"erreur": "Seules les requêtes de lecture (SELECT) sont autorisées."}
    resultat = _lire(requete)
    resultat["requete"] = requete
    return resultat


@outil("lister_alertes",
       "Liste les alertes météo : jours où un indicateur suivi a dépassé le seuil propre au site "
       "(fortes pluies, rafales, neige, chaleur, gel, crue, basses eaux), avec le risque pour la supply "
       "chain. C'est l'outil principal pour repérer les événements à risque, passés ou prévus.",
       {"site": {"type": "string", "description": "nom du site (facultatif : tous les sites sinon)"},
        "debut": {"type": "string", "description": "date de début AAAA-MM-JJ (facultatif)"},
        "fin": {"type": "string", "description": "date de fin AAAA-MM-JJ (facultatif)"},
        "indicateur": {"type": "string", "description": "pluie_3j, pluie_90j, rafales, neige, chaleur, gel, "
                                                        "crue ou basses_eaux (facultatif)"},
        "type": {"type": "string", "enum": ["observation", "prevision"],
                 "description": "observation (passé) ou prevision (facultatif : les deux)"}})
def lister_alertes(site=None, debut=None, fin=None, indicateur=None, type=None):
    conditions, params = [], []
    for colonne, valeur, operateur in (("site", site, "= ? COLLATE NOCASE"), ("date", debut, ">= ?"),
                                       ("date", fin, "<= ?"), ("indicateur", indicateur, "= ?"),
                                       ("type", type, "= ?")):
        if valeur:
            conditions.append(f"{colonne} {operateur}")
            params.append(valeur)
    filtre = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    requete = ("SELECT site, date, indicateur, valeur, seuil, unite, risque, type FROM alertes"
               + filtre + " ORDER BY date DESC")
    resultat = _lire(requete, tuple(params))
    if resultat["tronque"]:   # trop d'alertes : on ajoute un résumé par site et indicateur
        resume = _lire("SELECT site, indicateur, COUNT(*) AS jours_alerte, MIN(date) AS premier, MAX(date) AS dernier "
                       "FROM alertes" + filtre + " GROUP BY site, indicateur ORDER BY jours_alerte DESC", tuple(params))
        resultat["resume"] = {"colonnes": resume["colonnes"], "lignes": resume["lignes"]}
    return resultat


@outil("profil_site",
       "Fiche d'un site : pays, rôle, classe climatique, indicateurs suivis, seuils d'alerte, fréquence "
       "des alertes et nombre total de jours d'alerte. Utile avant de juger si une valeur est grave.",
       {"site": {"type": "string", "description": "nom du site"}}, ["site"])
def profil_site(site: str):
    fiche = _lire("SELECT * FROM sites WHERE site = ? COLLATE NOCASE", (site,))
    if not fiche["lignes"]:
        noms = _lire("SELECT site FROM sites ORDER BY site")["lignes"]
        return {"erreur": f"Site inconnu : {site}. Sites disponibles : {', '.join(n[0] for n in noms)}"}
    nom = fiche["lignes"][0][0]
    seuils = _lire("SELECT s.indicateur, s.seuil, s.unite, s.sens, e.episodes_par_an, "
                   "(SELECT COUNT(*) FROM alertes a WHERE a.site = s.site AND a.indicateur = s.indicateur "
                   " AND a.type = 'observation') AS jours_alerte_total "
                   "FROM seuils s LEFT JOIN episodes_par_an e ON e.site = s.site AND e.indicateur = s.indicateur "
                   "WHERE s.site = ?", (nom,))
    infos = dict(zip(fiche["colonnes"], fiche["lignes"][0]))
    suivis = {i.strip() for i in str(infos.get("indicateurs_suivis") or "").split(",")}
    lignes = [l + [l[0] in suivis] for l in seuils["lignes"]]
    return {"site": infos,
            "seuils": {"colonnes": seuils["colonnes"] + ["suivi"], "lignes": lignes,
                       "remarque": "seuls les indicateurs suivis (suivi = true) déclenchent des alertes"},
            "source_id": fiche["source_id"], "nb_lignes": 1 + seuils["nb_lignes"]}
