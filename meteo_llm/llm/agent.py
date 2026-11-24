"""
Agent : un LLM + une consigne (prompt) + une liste d'outils.

    from llm.agent import creer_agent_meteo
    agent = creer_agent_meteo()
    resultat = agent.demander("Quels sites ont eu des pluies exceptionnelles en 2024 ?")
    print(resultat["reponse"])

Le résultat suit le format JSON commun des agents du projet (agent, question, reponse,
sources avec source_id, donnees_manquantes), pour pouvoir être relié plus tard aux agents
médias et finance et au graphe.

Créer un nouvel agent (médias, finance...) = une fonction comme creer_agent_meteo,
avec son propre prompt dans llm/prompts/ et ses propres outils dans llm/outils.py.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import base_meteo

from . import outils as registre
from .config import charger_config
from .fournisseurs import Fournisseur, creer_fournisseur

DOSSIER_PROMPTS = Path(__file__).parent / "prompts"


class Agent:
    def __init__(self, nom: str, prompt_systeme: str, outils: list[str], fournisseur: Fournisseur,
                 max_etapes: int = 6, journal: bool = False):
        self.nom = nom
        self.prompt_systeme = prompt_systeme
        self.outils = outils
        self.fournisseur = fournisseur
        self.max_etapes = max_etapes      # nombre maximal d'appels au LLM pour une question
        self.journal = journal            # afficher les appels d'outils (utile pour déboguer)

    def demander(self, question: str, historique: list[dict] | None = None) -> dict:
        """Pose une question. `historique` permet d'enchaîner les questions (mode conversation)."""
        messages = list(historique or []) + [{"role": "user", "contenu": question}]
        sources, debut = [], time.perf_counter()
        for _ in range(self.max_etapes):
            reponse = self.fournisseur.discuter(self.prompt_systeme, messages, registre.schemas(self.outils))
            messages.append({"role": "assistant", "contenu": reponse.texte, "appels": reponse.appels})
            if not reponse.appels:
                return self._resultat(question, reponse.texte, sources, messages, debut)
            for appel in reponse.appels:
                if appel["nom"] not in self.outils:
                    resultat = {"erreur": f"Outil non autorisé pour cet agent : {appel['nom']}"}
                else:
                    resultat = registre.executer(appel["nom"], appel["arguments"])
                if self.journal:
                    print(f"  [outil] {appel['nom']}({json.dumps(appel['arguments'], ensure_ascii=False)})"
                          f" -> {'erreur : ' + resultat['erreur'] if 'erreur' in resultat else str(resultat.get('nb_lignes', 'ok')) + ' ligne(s)'}")
                if "source_id" in resultat:
                    sources.append({"outil": appel["nom"], "arguments": appel["arguments"],
                                    "source_id": resultat["source_id"], "nb_lignes": resultat.get("nb_lignes")})
                messages.append({"role": "outil", "id": appel["id"], "nom": appel["nom"],
                                 "resultat": json.dumps(resultat, ensure_ascii=False, default=str)})
        texte = "Je n'ai pas pu aboutir à une réponse en un nombre raisonnable d'étapes. Reformulez la question."
        return self._resultat(question, texte, sources, messages, debut, incomplet=True)

    def _resultat(self, question, texte, sources, messages, debut, incomplet=False) -> dict:
        return {
            "agent": self.nom,
            "question": question,
            "reponse": texte or "",
            "sources": sources,
            "donnees_manquantes": ["reponse_incomplete"] if incomplet else [],
            "modele": f"{self.fournisseur.config.fournisseur}:{self.fournisseur.config.modele}",
            "duree_s": round(time.perf_counter() - debut, 1),
            "_historique": messages,      # à repasser à demander() pour poser une question de suite
        }


def creer_agent_meteo(fournisseur: str | None = None, modele: str | None = None, journal: bool = False) -> Agent:
    prompt = (DOSSIER_PROMPTS / "agent_meteo.md").read_text(encoding="utf-8")
    prompt = prompt.replace("{date_du_jour}", date.today().isoformat())
    prompt = prompt.replace("{schema}", base_meteo.decrire_schema())
    config = charger_config(fournisseur, modele)
    return Agent("meteo", prompt, ["episodes_extremes", "executer_sql", "decrire_base"],
                 creer_fournisseur(config), journal=journal)
