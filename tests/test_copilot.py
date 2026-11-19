"""Copilot : routeur déterministe, appel d'outils par le LLM (simulé), replis."""
import pytest

from src.copilot.assistant import TOOL_SPECS, CopilotAssistant
from src.schemas.events import ChatRequest
from src.utils.llm import LLMError


def ask(service, message, context=None, use_llm=False):
    return service.chat(ChatRequest(message=message, context=context or {}), use_llm=use_llm)


def test_tool_specs_match_tools(service):
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert names == set(service.assistant.tools)
    for spec in TOOL_SPECS:
        assert set(spec["function"]["parameters"]["required"]) <= set(spec["function"]["parameters"]["properties"])


@pytest.mark.parametrize("message, tool, args", [
    ("Quels produits finis sont menacés aujourd'hui ?", "produits_menaces", {}),
    ("Simule une fermeture du port de Rotterdam", "simuler_perturbation", {"noeud": "port_rotterdam", "gravite": 1.0}),
    ("Que se passe-t-il si le port de Kaohsiung est bloqué à 80% ?", "simuler_perturbation", {"noeud": "port_kaohsiung", "gravite": 0.8}),
    ("What if Formoz is down at 50 percent?", "simuler_perturbation", {"noeud": "sup_chip_tw", "gravite": 0.5}),
    ("Quels fournisseurs alternatifs pour Formoz ?", "fournisseurs_alternatifs", {"noeud": "sup_chip_tw"}),
    ("Quels sont les nœuds les plus exposés ?", "noeuds_exposes", {}),
    ("Explique les alertes actives", "expliquer_alertes", {}),
    ("De quoi dépend l'usine de Valenciennes ?", "chemin_critique", {"noeud": "plant_assembly_fr"}),
    ("Bonjour", "etat_global", {}),
])
def test_deterministic_routing(service, message, tool, args):
    assert service.assistant.route(message, {}) == (tool, args)


def test_quick_questions_end_to_end(loaded_service):
    r1 = ask(loaded_service, "Quels produits finis sont menacés aujourd'hui ?")
    assert r1.mode == "deterministic" and [c.name for c in r1.tool_calls] == ["produits_menaces"]
    assert "Citadine électrique E-City" in r1.answer and "Port of Kaohsiung" in r1.answer

    r2 = ask(loaded_service, "Explique les alertes actives")
    assert "replay:" in r2.answer and "Chemin" in r2.answer, "l'explication cite les sources et le chemin"

    r3 = ask(loaded_service, "Pourquoi l'usine de Stuttgart est-elle en alerte ?")
    assert r3.tool_calls[0].result["total"] == 1 and "Rhein Power Modules" in r3.answer


def test_what_if_then_mitigation_uses_conversation_context(service):
    before = service.engine.current.index
    sim = ask(service, "Que se passe-t-il si le port de Kaohsiung est bloqué à 80 % ?")
    call = sim.tool_calls[0]
    assert call.name == "simuler_perturbation" and call.arguments == {"noeud": "port_kaohsiung", "gravite": 0.8}
    assert call.result["etat_reel_modifie"] is False and call.result["indice_apres"] > call.result["indice_avant"]
    assert "Citadine électrique E-City" in sim.answer and "n'est pas modifié" in sim.answer
    assert service.engine.current.index == before, "la simulation ne modifie pas l'état réel"
    assert sim.context == {"last_node_id": "port_kaohsiung"}

    plan = ask(service, "Propose un plan de contournement", context=sim.context)
    assert plan.tool_calls[0].name == "plan_mitigation" and plan.tool_calls[0].arguments == {"noeud": "port_kaohsiung"}
    assert "Port of Keelung" in plan.answer and "Waal Semiconductors" in plan.answer


def test_mitigation_without_context_targets_the_main_source_of_risk(loaded_service):
    plan = ask(loaded_service, "Propose un plan de contournement")
    assert plan.tool_calls[0].arguments["noeud"] == loaded_service.engine.alerts()[0].path[0]


def test_missing_or_unknown_node(service):
    r = ask(service, "Simule une panne")
    assert r.tool_calls == [] and "Sur quel nœud" in r.answer
    out = service.assistant.run_tool("simuler_perturbation", {"noeud": "port d'Atlantis", "gravite": 0.5})
    assert "erreur" in out and "Je ne peux pas répondre" in service.assistant.render("simuler_perturbation", out)
    assert "erreur" in service.assistant.run_tool("outil_inexistant", {})
    assert "erreur" in service.assistant.run_tool("simuler_perturbation", {"mauvais_argument": 1})


def test_empty_state_message(service):
    assert "lancez d'abord le pipeline" in ask(service, "Bonjour").answer


def test_severity_parsing():
    parse = CopilotAssistant.parse_severity
    assert parse("bloqué à 80%") == 0.8 and parse("à 35 % de capacité") == 0.35
    assert parse("fermeture du port") == 1.0 and parse("le port est bloqué") == 0.8 and parse("une perturbation") == 0.7


def scripted_llm(steps):
    """Faux LLM : rend les réponses de `steps` une par une et garde les messages reçus."""
    seen = []
    def chat_fn(messages, tools):
        seen.append([dict(m) for m in messages])
        step = steps[len(seen) - 1]
        return {"content": step.get("content", ""), "tool_calls": step.get("tool_calls", []),
                "raw": {"role": "assistant", "content": step.get("content", ""), "tool_calls": step.get("tool_calls", [])}}
    return chat_fn, seen


def test_llm_tool_calling_loop(service):
    chat_fn, seen = scripted_llm([
        {"tool_calls": [{"name": "simuler_perturbation", "arguments": {"noeud": "port de Kaohsiung", "gravite": 0.8}}]},
        {"tool_calls": [{"name": "plan_mitigation", "arguments": {"noeud": "port_kaohsiung"}}]},
        {"content": "Le blocage de Kaohsiung menace trois produits finis ; activez Keelung et Waal."}])
    bot = CopilotAssistant(service.engine, chat_fn=chat_fn, available_fn=lambda: True)
    r = bot.chat(ChatRequest(message="Et si Kaohsiung est bloqué à 80 % ? Que faire ?"), use_llm=True)
    assert r.mode == "llm" and r.answer.startswith("Le blocage de Kaohsiung")
    assert [c.name for c in r.tool_calls] == ["simuler_perturbation", "plan_mitigation"]
    assert r.tool_calls[0].result["noeud_id"] == "port_kaohsiung" and r.context["last_node_id"] == "port_kaohsiung"
    assert seen[0][0]["role"] == "system" and seen[0][-1]["role"] == "user"
    tool_messages = [m for m in seen[2] if m["role"] == "tool"]
    assert [m["tool_name"] for m in tool_messages] == ["simuler_perturbation", "plan_mitigation"]
    assert '"etat_reel_modifie": false' in tool_messages[0]["content"]


def test_llm_answer_without_tool_is_not_trusted(loaded_service):
    chat_fn, _ = scripted_llm([{"content": "Tout va bien, aucun produit n'est menacé."}])
    bot = CopilotAssistant(loaded_service.engine, chat_fn=chat_fn, available_fn=lambda: True)
    r = bot.chat(ChatRequest(message="Quels produits finis sont menacés ?"), use_llm=True)
    assert r.mode == "deterministic" and "Citadine électrique E-City" in r.answer
    assert "sans consulter le graphe" in r.note


def test_llm_failures_fall_back(service):
    def broken(messages, tools):
        raise LLMError("serveur injoignable (ConnectionError)", network=True)
    r = CopilotAssistant(service.engine, chat_fn=broken, available_fn=lambda: True).chat(
        ChatRequest(message="Simule une fermeture du port de Rotterdam"), use_llm=True)
    assert r.mode == "deterministic" and r.tool_calls[0].name == "simuler_perturbation" and "LLM indisponible" in r.note

    r = CopilotAssistant(service.engine, available_fn=lambda: False).chat(ChatRequest(message="Bonjour"), use_llm=True)
    assert r.mode == "deterministic" and "injoignable" in r.note

    loop, _ = scripted_llm([{"tool_calls": [{"name": "etat_global", "arguments": {}}]}] * 10)
    r = CopilotAssistant(service.engine, chat_fn=loop, available_fn=lambda: True).chat(ChatRequest(message="Bonjour"), use_llm=True)
    assert r.mode == "deterministic" and "pas de réponse finale" in r.note
