"""Vue 4 : assistant conversationnel (Copilot Supply Chain)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.common import STRETCH, clear_chat, current_run, run_banner, setup_page  # noqa: E402

backend = setup_page("Copilot", "💬")
st.title("Copilot Supply Chain")
run_banner(current_run(backend))

# Questions rapides : les deux ports les plus critiques de la topologie chargée servent d'exemples de simulation.
ports = sorted((n for n in backend.graph_state()["nodes"] if n["type"] == "port"), key=lambda n: -n["criticality"])
QUICK = {"Produits menacés": "Quels produits finis sont menacés aujourd'hui ?"}
if ports:
    QUICK[f"{ports[0]['place']} bloqué à 80 %"] = f"Que se passe-t-il si {ports[0]['name']} est bloqué à 80 % ?"
if len(ports) > 1:
    QUICK[f"Fermeture de {ports[1]['place']}"] = f"Simule une fermeture de {ports[1]['name']}"
QUICK["Plan de contournement"] = "Propose un plan de contournement"
QUICK["Expliquer les alertes"] = "Explique les alertes actives"

st.session_state.setdefault("chat", [])
st.session_state.setdefault("chat_context", {})


def ask(question: str) -> None:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state["chat"]][-8:]
    st.session_state["chat"].append({"role": "user", "content": question})
    try:
        r = backend.chat(question, history, st.session_state["chat_context"])
        st.session_state["chat_context"] = r["context"]
        st.session_state["chat"].append({"role": "assistant", "content": r["answer"], "mode": r["mode"],
                                         "tool_calls": r["tool_calls"], "note": r.get("note", "")})
    except Exception as e:
        st.session_state["chat"].append({"role": "assistant", "content": f"Erreur du backend : {e}", "mode": "erreur",
                                         "tool_calls": [], "note": ""})


cols = st.columns(len(QUICK))
for col, (label, question) in zip(cols, QUICK.items()):
    if col.button(label, help=question, **STRETCH):
        ask(question)

# La conversation est aussi vidée automatiquement à chaque exécution du pipeline et à chaque changement de mode,
# de scénario ou de topologie (voir app/common.py).
head = st.columns([4, 1])
head[0].caption("La conversation est vidée à chaque exécution du pipeline et à chaque changement de scénario ou de mode."
                if st.session_state["chat"] else "Aucun message. Cliquez sur une question rapide ou écrivez la vôtre.")
if head[1].button("Effacer la conversation", disabled=not st.session_state["chat"], **STRETCH):
    clear_chat()
    st.rerun()

for m in st.session_state["chat"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            mode = {"llm": "LLM local avec outils", "deterministic": "réponse déterministe (règles + graphe)"}.get(m["mode"], m["mode"])
            st.caption(f"Mode : {mode}" + (f" · {m['note']}" if m.get("note") else ""))
            if m.get("tool_calls"):
                with st.expander(f"Outils appelés ({len(m['tool_calls'])})"):
                    for call in m["tool_calls"]:
                        st.markdown(f"`{call['name']}`")
                        st.json({"arguments": call["arguments"], "resultat": call["result"]}, expanded=False)

if prompt := st.chat_input("Posez une question sur la chaîne d'approvisionnement"):
    ask(prompt)
    st.rerun()
