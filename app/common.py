"""Éléments partagés par les pages Streamlit : accès au backend, barre latérale, couleurs.

L'interface parle à l'API FastAPI (variable API_URL). Si l'API ne répond pas, elle bascule sur un moteur
embarqué dans le processus Streamlit (même code, sans HTTP) : la démonstration ne dépend pas d'un second serveur.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
import streamlit as st  # noqa: E402

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

# Niveaux de risque : palette d'état (vert -> rouge), toujours accompagnée du libellé.
LEVEL_COLORS = {"ok": "#0ca30c", "info": "#fab219", "warning": "#ec835a", "critical": "#d03b3b"}
LEVEL_LABELS = {"ok": "Normal", "info": "À surveiller", "warning": "Alerte", "critical": "Critique"}
LEVEL_ORDER = ["ok", "info", "warning", "critical"]
# Agents : couleurs catégorielles fixes, jamais réutilisées pour un niveau de risque.
AGENT_COLORS = {"media": "#3987e5", "weather": "#199e70", "finance": "#d95926"}
AGENT_LABELS = {"media": "Médias", "weather": "Météo", "finance": "Finance"}
TYPE_LABELS = {"matiere_premiere": "Matière première", "fournisseur": "Fournisseur", "port": "Port", "hub": "Hub",
               "usine": "Usine", "produit_fini": "Produit fini"}


def _supports_width() -> bool:
    import inspect
    return "width" in inspect.signature(st.button).parameters


# Streamlit récent : width="stretch". Versions plus anciennes : **STRETCH.
STRETCH: dict = {"width": "stretch"} if _supports_width() else {"use_container_width": True}


def embed_html(html: str, height: int) -> None:
    """Affiche une page HTML autonome (graphe PyVis). Le contenu est produit par l'application, jamais par l'utilisateur."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height, scrolling=False)


def is_dark() -> bool:
    """Thème courant. Au tout premier affichage d'une session, le navigateur n'a pas encore indiqué son thème et
    Streamlit annonce « light » à tort : on se fie alors au thème de .streamlit/config.toml."""
    configured = st.get_option("theme.base")
    if st.session_state.get("_runs", 0) <= 1 and configured:
        return configured != "light"
    try:
        return st.context.theme.type != "light"
    except Exception:
        return configured != "light"


def ink() -> dict:
    """Encres et surfaces des graphiques selon le thème."""
    if is_dark():
        return {"surface": "#1a1a19", "text": "#f0efec", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835"}
    return {"surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7"}


@st.cache_resource(show_spinner=False)
def _embedded_service():
    from src.service import SupplyChainService
    return SupplyChainService()


class Backend:
    """Client du backend : HTTP vers l'API, ou appels directs au service embarqué."""

    def __init__(self) -> None:
        if "embedded" not in st.session_state:
            st.session_state["embedded"] = os.getenv("SC_EMBEDDED", "") == "1" or not self._api_alive()

    @staticmethod
    def _api_alive() -> bool:
        try:
            return requests.get(f"{API_URL}/health", timeout=1.5).status_code == 200
        except requests.RequestException:
            return False

    @property
    def embedded(self) -> bool:
        return bool(st.session_state["embedded"])

    def _http(self, method: str, path: str, payload: Optional[dict] = None, timeout: float = 300) -> Any:
        r = requests.request(method, f"{API_URL}{path}", json=payload, timeout=timeout)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:200]
            raise RuntimeError(f"API {r.status_code} : {detail}")
        return r.json()

    def scenarios(self) -> list[dict]:
        return _embedded_service().list_scenarios() if self.embedded else self._http("GET", "/scenarios")

    def topologies(self) -> list[dict]:
        return _embedded_service().list_topologies() if self.embedded else self._http("GET", "/topologies")

    def last_run(self) -> Optional[dict]:
        if self.embedded:
            run = _embedded_service().last_run
            return run.model_dump(mode="json") if run else None
        return self._http("GET", "/health").get("last_run")

    def run_pipeline(self, payload: dict) -> dict:
        if self.embedded:
            from src.schemas.events import PipelineRunRequest
            return asyncio.run(_embedded_service().run_pipeline(PipelineRunRequest(**payload))).model_dump(mode="json")
        return self._http("POST", "/pipeline/run", payload)

    def graph_state(self) -> dict:
        return _embedded_service().engine.state().model_dump(mode="json") if self.embedded else self._http("GET", "/graph/state")

    def simulate(self, node_id: str, severity: float) -> dict:
        if self.embedded:
            return _embedded_service().engine.simulate_disruption(node_id, severity).model_dump(mode="json")
        return self._http("POST", "/graph/simulate", {"node_id": node_id, "severity": severity})

    def alerts(self) -> list[dict]:
        if self.embedded:
            return [a.model_dump(mode="json") for a in _embedded_service().engine.alerts()]
        return self._http("GET", "/alerts")

    def events(self) -> dict:
        return _embedded_service().events_payload() if self.embedded else self._http("GET", "/events")

    def chat(self, message: str, history: list[dict], context: dict) -> dict:
        payload = {"message": message, "history": history, "context": context}
        if self.embedded:
            from src.schemas.events import ChatRequest
            return _embedded_service().chat(ChatRequest(**payload)).model_dump(mode="json")
        return self._http("POST", "/chat", payload)


def setup_page(title: str, icon: str) -> Backend:
    st.set_page_config(page_title=f"{title} · Alerte Supply Chain", page_icon=icon, layout="wide")
    st.markdown("""<style>
        .block-container {padding-top: 2.2rem;}
        div[data-testid="stMetric"] {border: 1px solid rgba(137,135,129,.35); border-radius: 10px; padding: .7rem .9rem;}
        .sc-badge {display:inline-block; padding:.1rem .55rem; border-radius:999px; font-size:.8rem; font-weight:600; color:#fff;}
        </style>""", unsafe_allow_html=True)
    st.session_state["_runs"] = st.session_state.get("_runs", 0) + 1
    backend = Backend()
    render_sidebar(backend)
    return backend


def badge(level: str) -> str:
    fg = "#0b0b0b" if level == "info" else "#ffffff"
    return f'<span class="sc-badge" style="background:{LEVEL_COLORS[level]};color:{fg}">{LEVEL_LABELS[level]}</span>'


def restore(key: str, default: Any, valid: Optional[Callable[[Any], bool]] = None) -> None:
    """Prépare un widget dont la valeur doit survivre au changement de page. À appeler juste avant le widget.

    Streamlit ne garde pas l'état d'un widget d'une page à l'autre. La valeur de référence vit donc dans
    `keep_<key>` : elle est recopiée dans la clé du widget à chaque affichage, et mise à jour par `remember`
    (appelé par le widget quand l'utilisateur le modifie, puis en fin de barre latérale).
    `valid` écarte une valeur devenue impossible (scénario supprimé, jour hors période, nœud d'une autre topologie).
    """
    kept = st.session_state.get(f"keep_{key}", default)
    if valid is not None and not valid(kept):
        kept = default
    st.session_state[f"keep_{key}"] = kept
    st.session_state[key] = kept


def remember(*keys: str) -> None:
    for key in keys:
        if key in st.session_state:
            st.session_state[f"keep_{key}"] = st.session_state[key]


def clear_chat() -> None:
    st.session_state["chat"], st.session_state["chat_context"] = [], {}


def render_sidebar(backend: Backend) -> None:
    """Barre latérale commune : mode, scénario ou topologie, jour, LLM, bouton d'exécution du pipeline."""
    with st.sidebar:
        st.markdown("### Pipeline")
        modes = ["Replay scénario", "Live"]
        restore("mode_label", modes[0], lambda v: v in modes)
        mode_label = st.radio("Mode", modes, key="mode_label", on_change=remember, args=("mode_label",),
                              help="Replay : scénario hors ligne. Live : GDELT, RSS, Open-Meteo, Yahoo Finance.")
        payload: dict = {"mode": "replay" if mode_label.startswith("Replay") else "live"}
        topologies = backend.topologies()
        topo_name = {t["ref"] or "": (t["company"] or t["name"]) for t in topologies}
        if payload["mode"] == "replay":
            scenarios = backend.scenarios()
            if not scenarios:
                st.error("Aucun scénario dans data/replay_scenarios.")
                return
            ids = [s["id"] for s in scenarios]
            restore("scenario_id", ids[0], lambda v: v in ids)
            sid = st.selectbox("Scénario", ids, format_func=lambda i: next(s["title"] for s in scenarios if s["id"] == i), key="scenario_id", on_change=remember, args=("scenario_id",))
            sc = next(s for s in scenarios if s["id"] == sid)
            days = int(sc.get("days") or 1)
            restore("day", days, lambda v: isinstance(v, int) and 1 <= v <= days)
            day = st.slider("Jour du scénario", 1, days, key="day", on_change=remember, args=("day",),
                            help="Le pipeline ne voit que ce qui était connu ce jour-là.") if days > 1 else 1
            payload.update(scenario=sid, day=day)
            ref = "" if sc.get("topology") in (None, "topology.yaml") else sc["topology"]
            st.caption(f"Chaîne du scénario : {topo_name.get(ref, sc.get('topology'))}")
            if sc.get("storyline", {}).get(str(day)):
                st.caption(f"Jour {day} : {sc['storyline'][str(day)]}")
            scope = ("replay", sid)
        else:
            refs = [t["ref"] or "" for t in topologies] or [""]
            restore("topology_ref", "", lambda v: v in refs)
            ref = st.selectbox("Topologie (entreprise cible)", refs, key="topology_ref", on_change=remember, args=("topology_ref",),
                               format_func=lambda r: next((f"{t['company'] or t['name']} · {t['nodes']} nœuds" for t in topologies
                                                           if (t["ref"] or "") == r), "Topologie par défaut"),
                               help="Chaîne d'approvisionnement surveillée en direct. Les fichiers viennent de data/topology*.yaml "
                                    "et data/topologies/. Elle est chargée à la prochaine exécution.")
            payload["topology"] = ref or None
            st.caption("Le mode live demande un accès Internet. Une panne de collecte est signalée comme telle, "
                       "jamais remplacée par des données de scénario.")
            scope = ("live", ref)
        restore("use_llm", False)
        payload["use_llm"] = st.toggle("Extraction par LLM local (Ollama)", key="use_llm", on_change=remember, args=("use_llm",),
                                       help="qwen2.5:7b. Si le serveur ne répond pas, la baseline NLP prend le relais.")
        remember("mode_label", "scenario_id", "day", "topology_ref", "use_llm")

        # Les réponses du copilot décrivent un état précis : changer de mode, de scénario ou de topologie les périme.
        if st.session_state.get("_chat_scope", scope) != scope:
            clear_chat()
        st.session_state["_chat_scope"] = scope

        if st.button("Exécuter le pipeline", type="primary", **STRETCH):
            with st.spinner("Collecte, corrélation et propagation en cours..."):
                try:
                    st.session_state["last_run"] = backend.run_pipeline(payload)
                    clear_chat()                         # nouvel état du graphe : l'ancienne conversation ne vaut plus
                except Exception as e:
                    st.error(f"Échec du pipeline : {e}")
        st.divider()
        if backend.embedded:
            st.caption(f"Moteur embarqué (API injoignable à {API_URL}).")
            if st.button("Réessayer l'API", **STRETCH):
                st.session_state.pop("embedded")
                st.rerun()
        else:
            st.caption(f"Connecté à l'API : {API_URL}")


def current_run(backend: Backend) -> Optional[dict]:
    """Dernière exécution connue : celle de la session, sinon celle du backend."""
    if "last_run" not in st.session_state:
        try:
            st.session_state["last_run"] = backend.last_run()
        except Exception:
            st.session_state["last_run"] = None
    return st.session_state["last_run"]


def run_banner(run: Optional[dict]) -> bool:
    """Affiche l'état de la dernière exécution. Renvoie False s'il n'y a rien à afficher sur la page."""
    if not run:
        st.info("Aucune donnée chargée. Choisissez un mode dans la barre latérale puis cliquez sur « Exécuter le pipeline ».")
        return False
    if run["status"] == "error":
        st.error(run["message"])
    elif run["degraded"]:
        st.warning(run["message"])
    chain = f" · chaîne : {run['topology_name']}" if run.get("topology_name") else ""
    if run.get("fictional"):
        st.caption(f"Scénario fictif · jour {run['day']} / {run['days_total']} · données au {run['as_of']}{chain}")
    else:
        st.caption(f"Mode {run['mode']} · données au {run['as_of']}{chain}")
    return True
