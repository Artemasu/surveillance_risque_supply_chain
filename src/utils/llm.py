"""Client du LLM local (Ollama ou serveur compatible OpenAI), repris du notebook v2 (section 5.3).

Deux usages : extraction JSON stricte pour l'agent médias (`call_llm`) et conversation avec outils pour le
copilot (`chat_with_tools`). Toute erreur devient une LLMError : l'appelant bascule alors sur son repli.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import requests

from src.config import settings


class LLMError(Exception):
    """Erreur du LLM. `network` vaut True si le serveur n'a pas répondu."""

    def __init__(self, message: str, network: bool = False):
        super().__init__(message)
        self.network = network


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}


def llm_available(timeout: float = 3) -> bool:
    """True si le serveur LLM répond. Ne lève jamais d'exception."""
    path = "/api/tags" if settings.llm_backend == "ollama" else "/v1/models"
    try:
        return requests.get(settings.llm_base_url.rstrip("/") + path, headers=_headers(), timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def _post(payload: dict, timeout: Optional[float]) -> dict:
    base = settings.llm_base_url.rstrip("/")
    if settings.llm_backend == "ollama":
        url = base + "/api/chat"
    elif settings.llm_backend == "openai":
        url = base + "/v1/chat/completions"
    else:
        raise LLMError(f"LLM_BACKEND inconnu : {settings.llm_backend!r} (attendu : ollama ou openai)")
    try:
        r = requests.post(url, json=payload, headers=_headers(), timeout=timeout or settings.llm_timeout_s)
    except requests.RequestException as e:
        raise LLMError(f"serveur injoignable ({type(e).__name__})", network=True)
    if r.status_code != 200:
        raise LLMError(f"HTTP {r.status_code} : {r.text[:120]}", network=r.status_code >= 500)
    try:
        return r.json()
    except ValueError as e:
        raise LLMError(f"réponse du serveur illisible ({type(e).__name__})")


def _message(data: dict) -> dict:
    try:
        msg = data["message"] if settings.llm_backend == "ollama" else data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"réponse du serveur inattendue ({type(e).__name__})")
    if not isinstance(msg, dict):
        raise LLMError("réponse du serveur inattendue (message absent)")
    return msg


def call_llm(system_prompt: str, user_prompt: str, timeout: Optional[float] = None) -> str:
    """Appel en mode JSON, température 0. Renvoie le texte de la réponse."""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    if settings.llm_backend == "ollama":
        payload = {"model": settings.llm_model, "messages": messages, "stream": False, "format": "json",
                   "options": {"temperature": 0}}
    else:
        payload = {"model": settings.llm_model, "messages": messages, "temperature": 0,
                   "response_format": {"type": "json_object"}}
    return str(_message(_post(payload, timeout)).get("content") or "")


def chat_with_tools(messages: list[dict], tools: list[dict], timeout: Optional[float] = None) -> dict:
    """Un tour de conversation avec outils. Renvoie {"content": str, "tool_calls": [{"name", "arguments"}], "raw": message}."""
    if settings.llm_backend == "ollama":
        payload = {"model": settings.llm_model, "messages": messages, "tools": tools, "stream": False,
                   "options": {"temperature": 0}}
    else:
        payload = {"model": settings.llm_model, "messages": messages, "tools": tools, "temperature": 0}
    msg = _message(_post(payload, timeout))
    calls = []
    for call in msg.get("tool_calls") or []:
        fn = (call or {}).get("function") or {}
        args: Any = fn.get("arguments") or {}
        if isinstance(args, str):                    # format OpenAI : les arguments arrivent en texte JSON
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if fn.get("name"):
            calls.append({"name": fn["name"], "arguments": args if isinstance(args, dict) else {}, "id": call.get("id")})
    return {"content": str(msg.get("content") or ""), "tool_calls": calls, "raw": msg}


def parse_llm_json(text: str) -> dict:
    """Extrait l'objet JSON de la réponse (tolère des balises Markdown ou du texte autour)."""
    text = str(text or "").strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise LLMError("aucun objet JSON dans la réponse")
    try:
        obj = json.loads(text[i:j + 1])
    except ValueError as e:
        raise LLMError(f"JSON invalide ({str(e)[:60]})")
    if not isinstance(obj, dict):
        raise LLMError("la réponse n'est pas un objet JSON")
    return obj
