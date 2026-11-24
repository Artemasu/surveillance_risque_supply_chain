"""
Outils que le LLM peut appeler. Le LLM ne touche jamais directement aux données :
il demande un outil, le code Python l'exécute, et le résultat lui est renvoyé.

Ajouter un outil = écrire une fonction et la décorer avec @outil(...) :

    @outil("nom_outil", "Ce que fait l'outil (le LLM lit cette phrase pour décider de l'utiliser).",
           {"site": {"type": "string", "description": "nom du site"}}, obligatoires=["site"])
    def nom_outil(site):
        return {...}          # un dict sérialisable en JSON

Puis ajouter son nom dans la liste d'outils de l'agent (agent.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
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
    cx = sqlite3.connect(f"file:{chemin.as_posix()}?mode=ro", uri=True)
    cx.execute("PRAGMA query_only = ON")
    debut = time.monotonic()
    cx.set_progress_handler(lambda: int(time.monotonic() - debut > DELAI_SQL_S), 10_000)
    return cx


def _source_id(texte: str) -> str:
    return "base_meteo:sql:" + hashlib.md5(texte.encode()).hexdigest()[:10]


def _lire(requete: str, parametres: tuple = ()) -> dict:
    with _connexion() as cx:
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


@outil("episodes_extremes",
       "Liste les jours où un site a dépassé ses propres seuils (inhabituel ou exceptionnel) : fortes "
       "pluies, rafales, chaleur, gel, crues, basses eaux. C'est l'outil principal pour repérer les risques.",
       {"site": {"type": "string", "description": "nom du site (facultatif : tous les sites sinon)"},
        "debut": {"type": "string", "description": "date de début AAAA-MM-JJ (facultatif)"},
        "fin": {"type": "string", "description": "date de fin AAAA-MM-JJ (facultatif)"},
        "niveau": {"type": "string", "enum": ["inhabituel", "exceptionnel"],
                   "description": "niveau minimal (exceptionnel par défaut)"},
        "variable": {"type": "string", "description": "limiter à une variable, ex. pluie_3j_mm (facultatif)"}})
def episodes_extremes(site=None, debut=None, fin=None, niveau="exceptionnel", variable=None):
    with _connexion() as cx:
        regles = cx.execute("SELECT site, variable, sens, seuil_inhabituel, seuil_exceptionnel FROM seuils").fetchall()
    morceaux, params = [], []
    colonne_seuil = "seuil_exceptionnel" if niveau == "exceptionnel" else "seuil_inhabituel"
    for s, var, sens, s_inh, s_exc in regles:
        if (site and s.lower() != site.lower()) or (variable and var != variable):
            continue
        seuil = s_exc if colonne_seuil == "seuil_exceptionnel" else s_inh
        comparaison = ">=" if sens == "haut" else "<="
        niveau_sql = (f"CASE WHEN {var} {comparaison} ? THEN 'exceptionnel' ELSE 'inhabituel' END")
        morceaux.append(f"SELECT site, date, '{var}' AS variable, '{sens}' AS sens, {var} AS valeur, "
                        f"? AS seuil, {niveau_sql} AS niveau FROM meteo_jour "
                        f"WHERE site = ? AND {var} {comparaison} ?")
        params += [seuil, s_exc, s, seuil]
    if not morceaux:
        return {"episodes": [], "remarque": "Aucun seuil pour ce site ou cette variable (historique trop court ?)."}
    requete = "SELECT * FROM (" + " UNION ALL ".join(morceaux) + ") WHERE 1=1"
    if debut:
        requete += " AND date >= ?"; params.append(debut)
    if fin:
        requete += " AND date <= ?"; params.append(fin)
    requete += " ORDER BY date DESC"
    resultat = _lire(requete, tuple(params))
    resultat["critere"] = f"niveau >= {niveau}, seuils propres à chaque site (table seuils)"
    return resultat
