"""
assistant_meteo.py - Interroger la base météo en langage naturel

    python assistant_meteo.py tester                      # vérifie la base et la connexion au LLM
    python assistant_meteo.py demander "Quels sites ont eu des pluies exceptionnelles en 2024 ?"
    python assistant_meteo.py demander "..." --json       # sortie au format JSON commun des agents
    python assistant_meteo.py discuter                    # conversation (questions de suite possibles)

Options : --fournisseur ollama|mistral|anthropic|...  --modele NOM  --journal (affiche les outils appelés)
"""
from __future__ import annotations

import argparse
import json
import sys

import base_meteo
from llm.agent import creer_agent_meteo
from llm.config import charger_config
from llm.fournisseurs import ErreurLLM, creer_fournisseur


def tester(fournisseur=None, modele=None) -> int:
    ok = True
    try:
        print("Base :", base_meteo.CHEMIN_BASE)
        print(base_meteo.decrire_schema().splitlines()[-2])
    except Exception as e:
        print("✗ Base :", e, "\n  -> lancez « python base_meteo.py » après la collecte.")
        ok = False
    try:
        config = charger_config(fournisseur, modele)
        print("LLM :", config)
        r = creer_fournisseur(config).discuter("Réponds en un mot.", [{"role": "user", "contenu": "Dis OK."}], [])
        print("✓ Le LLM répond :", (r.texte or "")[:60])
    except (ErreurLLM, ValueError) as e:
        print("✗ LLM :", e)
        ok = False
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Assistant de l'agent météo")
    p.add_argument("commande", choices=["tester", "demander", "discuter"])
    p.add_argument("question", nargs="?")
    p.add_argument("--fournisseur")
    p.add_argument("--modele")
    p.add_argument("--json", action="store_true")
    p.add_argument("--journal", action="store_true")
    a = p.parse_args(argv)

    if a.commande == "tester":
        return tester(a.fournisseur, a.modele)
    try:
        agent = creer_agent_meteo(a.fournisseur, a.modele, journal=a.journal)
    except Exception as e:
        print("Erreur :", e, file=sys.stderr)
        return 1

    if a.commande == "demander":
        if not a.question:
            p.error("indiquez la question entre guillemets")
        try:
            res = agent.demander(a.question)
        except ErreurLLM as e:
            print("Erreur :", e, file=sys.stderr)
            return 1
        if a.json:
            print(json.dumps({k: v for k, v in res.items() if not k.startswith("_")},
                             ensure_ascii=False, indent=2, default=str))
        else:
            print(res["reponse"])
        return 0

    print("Posez vos questions (ligne vide pour quitter).")
    historique = []
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        try:
            res = agent.demander(question, historique)
        except ErreurLLM as e:
            print("Erreur :", e)
            continue
        historique = res["_historique"][-20:]   # on garde les derniers échanges pour le contexte
        while historique and historique[0]["role"] != "user":
            historique.pop(0)                   # l'historique doit commencer par une question
        print(res["reponse"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
