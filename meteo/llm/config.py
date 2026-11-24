"""
Configuration du LLM : quel fournisseur, quel modèle, quelle clé.

Tout se règle dans le fichier .env (à copier depuis .env.exemple, jamais envoyé sur GitHub)
ou par des variables d'environnement :

    LLM_FOURNISSEUR=ollama        # ollama | mistral | anthropic | openai | compatible
    LLM_MODELE=qwen3:8b           # facultatif : sinon le modèle par défaut du fournisseur
    LLM_URL=...                   # facultatif : adresse du serveur (ex. autre machine Ollama)
    MISTRAL_API_KEY=...           # la clé du fournisseur choisi, si nécessaire

Ajouter un fournisseur = ajouter une entrée dans FOURNISSEURS.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# "protocole" : format de l'API. Presque tous les fournisseurs parlent le format OpenAI ;
# Anthropic (Claude) a son propre format.
FOURNISSEURS = {
    "ollama":    {"protocole": "openai", "url": "http://localhost:11434/v1", "modele": "qwen3:8b",
                  "variable_cle": None},
    "mistral":   {"protocole": "openai", "url": "https://api.mistral.ai/v1", "modele": "mistral-small-latest",
                  "variable_cle": "MISTRAL_API_KEY"},
    "anthropic": {"protocole": "anthropic", "url": "https://api.anthropic.com/v1", "modele": "claude-haiku-5-5",
                  "variable_cle": "ANTHROPIC_API_KEY"},
    "openai":    {"protocole": "openai", "url": "https://api.openai.com/v1", "modele": "gpt-4o-mini",
                  "variable_cle": "OPENAI_API_KEY"},
    # tout autre serveur au format OpenAI (Groq, LM Studio, vLLM...) : renseigner LLM_URL et LLM_MODELE
    "compatible": {"protocole": "openai", "url": None, "modele": None, "variable_cle": "LLM_CLE"},
}


@dataclass
class ConfigLLM:
    fournisseur: str
    protocole: str
    url: str
    modele: str
    cle: str | None = None
    temperature: float = 0.1      # bas : on veut des réponses factuelles et reproductibles
    max_tokens: int = 1500
    delai_s: int = 120            # un modèle local sur processeur peut être lent

    def __repr__(self):           # ne jamais afficher la clé en clair
        return f"ConfigLLM({self.fournisseur}, modele={self.modele}, url={self.url}, cle={'oui' if self.cle else 'non'})"


def charger_env(chemin: str | Path = ".env") -> None:
    """Lit un fichier .env simple (CLE=valeur) sans écraser les variables déjà définies."""
    chemin = Path(chemin)
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


def charger_config(fournisseur: str | None = None, modele: str | None = None) -> ConfigLLM:
    charger_env()
    nom = (fournisseur or os.environ.get("LLM_FOURNISSEUR") or "ollama").lower()
    if nom not in FOURNISSEURS:
        raise ValueError(f"Fournisseur inconnu : {nom}. Choix : {', '.join(FOURNISSEURS)}")
    f = FOURNISSEURS[nom]
    url = os.environ.get("LLM_URL") or f["url"]
    modele = modele or os.environ.get("LLM_MODELE") or f["modele"]
    cle = os.environ.get(f["variable_cle"]) if f["variable_cle"] else None
    cle = cle or os.environ.get("LLM_CLE")
    if not url or not modele:
        raise ValueError(f"Pour « {nom} », renseignez LLM_URL et LLM_MODELE dans le fichier .env.")
    if f["variable_cle"] and not cle:
        raise ValueError(f"Clé manquante pour « {nom} » : ajoutez {f['variable_cle']}=... dans le fichier .env.")
    return ConfigLLM(nom, f["protocole"], url.rstrip("/"), modele, cle,
                     temperature=float(os.environ.get("LLM_TEMPERATURE", 0.1)))
