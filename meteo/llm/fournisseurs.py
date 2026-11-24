"""
Connexion aux LLM. Le reste du code ne connaît qu'une seule fonction :

    fournisseur.discuter(systeme, messages, outils) -> Reponse(texte, appels)

Les messages sont dans un format neutre, traduit ici vers le format de chaque API :
    {"role": "user", "contenu": "..."}
    {"role": "assistant", "contenu": "..." ou None, "appels": [{"id", "nom", "arguments": {...}}]}
    {"role": "outil", "id": ..., "nom": ..., "resultat": "texte JSON"}
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

import requests

from .config import ConfigLLM


class ErreurLLM(RuntimeError):
    pass


@dataclass
class Reponse:
    texte: str | None
    appels: list[dict] = field(default_factory=list)
    brut: dict | None = None


def _nettoyer(texte: str | None) -> str | None:
    """Retire le raisonnement interne que certains modèles (Qwen3, DeepSeek) écrivent entre <think>."""
    if texte is None:
        return None
    return re.sub(r"<think>.*?</think>", "", texte, flags=re.S).strip() or None


def _poster(url: str, entetes: dict, corps: dict, delai: int) -> dict:
    try:
        r = requests.post(url, headers=entetes, json=corps, timeout=(10, delai))
    except requests.ConnectionError as e:
        if "localhost" in url or "127.0.0.1" in url:
            raise ErreurLLM("Ollama ne répond pas : lancez l'application Ollama (ou « ollama serve »).") from e
        raise ErreurLLM(f"Serveur du LLM injoignable ({url}) : {e}") from e
    except requests.Timeout as e:
        raise ErreurLLM(f"Le LLM n'a pas répondu en {delai} s.") from e
    if r.status_code == 401:
        raise ErreurLLM("Clé API refusée (401) : vérifiez la clé dans le fichier .env.")
    if r.status_code == 404 and "localhost:11434" in url:
        raise ErreurLLM(f"Modèle introuvable dans Ollama : lancez « ollama pull {corps.get('model')} ».")
    if r.status_code >= 400:
        raise ErreurLLM(f"Erreur du LLM ({r.status_code}) : {r.text[:300]}")
    return r.json()


class Fournisseur:
    def __init__(self, config: ConfigLLM):
        self.config = config

    def discuter(self, systeme: str, messages: list[dict], outils: list[dict]) -> Reponse:
        raise NotImplementedError


class FournisseurOpenAI(Fournisseur):
    """Format OpenAI « chat/completions » : Ollama, Mistral, OpenAI, Groq, LM Studio..."""

    def discuter(self, systeme, messages, outils):
        msgs = [{"role": "system", "content": systeme}]
        for m in messages:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["contenu"]})
            elif m["role"] == "assistant":
                a = {"role": "assistant", "content": m.get("contenu") or ""}
                if m.get("appels"):
                    a["tool_calls"] = [{"id": c["id"], "type": "function",
                                        "function": {"name": c["nom"], "arguments": json.dumps(c["arguments"],
                                                                                              ensure_ascii=False)}}
                                       for c in m["appels"]]
                msgs.append(a)
            elif m["role"] == "outil":
                msgs.append({"role": "tool", "tool_call_id": m["id"], "name": m["nom"], "content": m["resultat"]})
        corps = {"model": self.config.modele, "messages": msgs, "temperature": self.config.temperature,
                 "max_tokens": self.config.max_tokens}
        if outils:
            corps["tools"] = [{"type": "function", "function": {"name": o["nom"], "description": o["description"],
                                                                "parameters": o["parametres"]}} for o in outils]
        entetes = {"Content-Type": "application/json"}
        if self.config.cle:
            entetes["Authorization"] = f"Bearer {self.config.cle}"
        data = _poster(f"{self.config.url}/chat/completions", entetes, corps, self.config.delai_s)
        message = data["choices"][0]["message"]
        appels = []
        for c in message.get("tool_calls") or []:
            arguments = c["function"].get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {"_illisible": arguments}
            appels.append({"id": c.get("id") or uuid.uuid4().hex[:12], "nom": c["function"]["name"],
                           "arguments": arguments})
        return Reponse(_nettoyer(message.get("content")), appels, data)


class FournisseurAnthropic(Fournisseur):
    """Format de l'API Messages d'Anthropic (Claude)."""

    def discuter(self, systeme, messages, outils):
        msgs = []
        for m in messages:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["contenu"]})
            elif m["role"] == "assistant":
                blocs = [{"type": "text", "text": m["contenu"]}] if m.get("contenu") else []
                blocs += [{"type": "tool_use", "id": c["id"], "name": c["nom"], "input": c["arguments"]}
                          for c in m.get("appels", [])]
                msgs.append({"role": "assistant", "content": blocs or [{"type": "text", "text": "..."}]})
            elif m["role"] == "outil":
                bloc = {"type": "tool_result", "tool_use_id": m["id"], "content": m["resultat"]}
                # les résultats d'outils consécutifs vont dans un seul message « user »
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                    msgs[-1]["content"].append(bloc)
                else:
                    msgs.append({"role": "user", "content": [bloc]})
        corps = {"model": self.config.modele, "system": systeme, "messages": msgs,
                 "max_tokens": self.config.max_tokens, "temperature": self.config.temperature}
        if outils:
            corps["tools"] = [{"name": o["nom"], "description": o["description"], "input_schema": o["parametres"]}
                              for o in outils]
        entetes = {"x-api-key": self.config.cle or "", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        data = _poster(f"{self.config.url}/messages", entetes, corps, self.config.delai_s)
        texte = " ".join(b["text"] for b in data.get("content", []) if b["type"] == "text") or None
        appels = [{"id": b["id"], "nom": b["name"], "arguments": b.get("input") or {}}
                  for b in data.get("content", []) if b["type"] == "tool_use"]
        return Reponse(_nettoyer(texte), appels, data)


def creer_fournisseur(config: ConfigLLM) -> Fournisseur:
    classes = {"openai": FournisseurOpenAI, "anthropic": FournisseurAnthropic}
    return classes[config.protocole](config)
