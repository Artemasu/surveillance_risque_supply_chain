"""Rattachement élargi en live, choix de la topologie en live, barre latérale persistante, remise à zéro du copilot."""
import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts import generate_sector_config as gen
from src.agents.finance_agent import FinanceAgent
from src.agents.media_agent import MediaAgent
from src.agents.media_sources import Article
from src.agents.weather_agent import WeatherAgent
from src.api.main import create_app
from src.config import settings
from src.graph.ontology_engine import ALERT_THRESHOLD, SOFT_LINK_CONFIDENCE
from src.schemas.events import PipelineRunRequest
from src.service import ScenarioNotFound, SupplyChainService
from tests.conftest import ROOT, SCENARIO, media_event, weather_event

NOW = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)


def article(n: int, title: str, text: str = "") -> Article:
    return Article(source_id=f"rss:test:{n:03d}", source_type="rss", url=f"https://example.org/{n}", title=title,
                   text=text, published_at=NOW)


LITHIUM = article(1, "Lithium miners begin an indefinite strike, supply disruption feared",
                  "Workers at several lithium mines in Chile walked off the job on Monday.")
CHIPS = article(2, "Earthquake forces semiconductor plants to halt production",
                "Several chipmakers evacuated their fabs after the earthquake.")
COUNTRY = article(3, "Dockworkers strike paralyses container terminals across the Netherlands")
EXACT = article(4, "Dockworkers strike closes the Port of Rotterdam container terminals")
NOTHING = article(5, "Ransomware attack hits a logistics group in Brazil")


def extract(service, arts, broad=True):
    return asyncio.run(service.agents["media"].extract_events(list(arts), use_llm=False, broad_linking=broad))


# ----------------------------------------------------------------------------- 4. rattachement élargi
def test_raw_material_links_article_with_moderate_confidence(service):
    (ev,) = extract(service, [LITHIUM])
    assert [(e.id, e.role) for e in ev.entities if e.role == "exposé"] == [("NODE:rm_lithium", "exposé")], "la matière passe avant le pays (Chili)"
    assert ev.meta.confidence == 0.40 and "rattachement élargi" in ev.meta.detail and "lithium" in ev.meta.detail
    assert "rattachement_exact" in ev.donnees_manquantes
    assert service.engine.link_weights(ev) == {"rm_lithium": SOFT_LINK_CONFIDENCE}


def test_sector_keyword_and_country_fallback(service):
    chips, country = extract(service, [CHIPS, COUNTRY])
    exposed = lambda ev: {e.id for e in ev.entities if e.role == "exposé"}  # noqa: E731
    assert exposed(chips) == {"NODE:sup_chip_tw", "NODE:sup_chip_nl"}
    assert "mot-clé sectoriel" in chips.meta.detail
    assert exposed(country) == {"NODE:sup_chip_nl", "NODE:port_rotterdam"}, "nœuds situés aux Pays-Bas"
    assert "pays « netherlands »" in country.meta.detail


def test_exact_mentions_are_never_broadened(service):
    exact, nothing = extract(service, [EXACT, NOTHING])
    assert exact.location.name == "Port of Rotterdam" and not [e for e in exact.entities if e.role == "exposé"]
    assert exact.meta.confidence != 0.40 and "rattachement_exact" not in exact.donnees_manquantes
    assert not [e for e in nothing.entities if e.role != "mentionné"], "aucun indice : l'événement reste hors graphe, rien n'est inventé"


def test_broad_linking_is_off_by_default_in_the_extractor(service):
    (ev,) = extract(service, [LITHIUM], broad=False)
    assert not [e for e in ev.entities if e.role == "exposé"] and service.engine.link_event(ev) == []


def test_soft_referential_of_each_topology(service):
    terms = {(t["term"], t["kind"]): t["node_ids"] for t in service.engine.soft_referential()}
    assert terms[("lithium", "matière première")] == ["rm_lithium"]
    assert terms[("taiwan", "pays")] == ["sup_wafer_tw", "sup_chip_tw", "port_kaohsiung", "port_keelung"]
    assert ("taiwan", "pays") in terms and ("taiwan", "pays") != ("taïwan", "pays"), "les alias de pays sont normalisés"
    pharma = SupplyChainService(topology_path=ROOT / "data" / "topologies" / "pharma_helvia.yaml")
    kinds = {t["kind"] for t in pharma.engine.soft_referential()}
    assert kinds == {"matière première", "mot-clé sectoriel", "pays"}
    (ev,) = extract(pharma, [article(9, "Antibiotic shortage worsens as plants halt production", "Hospitals report a drug shortage.")])
    assert {e.id for e in ev.entities if e.role == "exposé"} == {"NODE:sup_api_in", "NODE:sup_api_cn"}


def test_broad_link_weighs_less_and_cannot_alert_alone(service, engine):
    (weak,) = extract(service, [CHIPS])
    exact = media_event("x", "catastrophe", "2026-11-16", "sup_chip_tw", "Formoz Power Semi")
    e_weak, e_exact = engine.evaluate([weak], "2026-11-16"), engine.evaluate([exact], "2026-11-16")
    assert e_weak.direct["sup_chip_tw"] == pytest.approx(SOFT_LINK_CONFIDENCE * e_exact.direct["sup_chip_tw"], abs=1e-3)
    signal = next(s for s in e_weak.signals if s.node_id == "sup_chip_tw")
    assert signal.link == "elargi" and not signal.corroborated
    assert max(r["risk"] for r in e_weak.risks.values()) < ALERT_THRESHOLD, "un indice large seul ne déclenche pas d'alerte"
    assert next(s for s in e_exact.signals).link == "exact"


def test_broad_link_does_not_corroborate_an_exact_signal(service, engine):
    (weak,) = extract(service, [article(7, "Typhoon floods factories across Taiwan")])
    assert "NODE:port_kaohsiung" in {e.id for e in weak.entities}
    storm = weather_event("w", "2026-11-16", "port_kaohsiung", "Port of Kaohsiung")
    alone, both = engine.evaluate([storm], "2026-11-16"), engine.evaluate([storm, weak], "2026-11-16")
    sig = next(s for s in both.signals if s.node_id == "port_kaohsiung")
    assert sig.agents == ["weather"] and not sig.corroborated and sig.link == "exact"
    assert both.direct["port_kaohsiung"] == alone.direct["port_kaohsiung"]
    assert both.direct["port_keelung"] > 0, "les autres nœuds du pays reçoivent le signal faible"


def _fake_live(monkeypatch, articles):
    async def media(self, report=None, **k):
        report["rss"] = {"status": "ok"}
        return list(articles)
    async def empty_list(self, report=None, **k):
        report["open_meteo"] = {"status": "ok"}
        return []
    async def empty_dict(self, report=None, **k):
        report["yfinance"] = {"status": "ok"}
        return {}
    monkeypatch.setattr(MediaAgent, "collect_live", media)
    monkeypatch.setattr(WeatherAgent, "collect_live", empty_list)
    monkeypatch.setattr(FinanceAgent, "collect_live", empty_dict)


def test_live_pipeline_feeds_the_graph_without_llm(service, monkeypatch):
    _fake_live(monkeypatch, [LITHIUM, CHIPS, EXACT, NOTHING])
    res = asyncio.run(service.run_pipeline(PipelineRunRequest(mode="live", use_llm=False)))
    assert res.status == "success" and res.n_events == 4
    payload = service.events_payload()
    links = {e["event"]["media"][0]["source_id"]: e["link"] for e in payload["events"]}
    assert links == {"rss:test:001": "elargi", "rss:test:002": "elargi", "rss:test:004": "exact", "rss:test:005": None}
    nodes = {n.id: n for n in service.engine.state().nodes}
    assert 0 < nodes["rm_lithium"].direct < nodes["port_rotterdam"].direct
    assert {s.link for s in service.engine.current.signals} == {"exact", "elargi"}


def test_broad_linking_setting(service, monkeypatch):
    _fake_live(monkeypatch, [LITHIUM])
    monkeypatch.setattr(settings, "broad_linking", "never")
    asyncio.run(service.run_pipeline(PipelineRunRequest(mode="live")))
    assert service.engine.current.signals == []
    monkeypatch.setattr(settings, "broad_linking", "live")
    asyncio.run(service.run_pipeline(PipelineRunRequest(mode="live")))
    assert [s.node_id for s in service.engine.current.signals] == ["rm_lithium"]


def test_replay_scenarios_are_not_affected(service):
    res = asyncio.run(service.run_pipeline(PipelineRunRequest(mode="replay", scenario=SCENARIO, day=1)))
    assert res.global_risk_index == 6.0 and res.n_alerts == 0
    assert not any(e.role == "exposé" for ev in service.engine.events for e in ev.entities)
    assert all(s.link == "exact" for s in service.engine.current.signals)


# ----------------------------------------------------------------------------- 2. topologie en mode live
@pytest.fixture
def data_dir(tmp_path):
    """Dossier data/ de test : topologie par défaut, data/topology_pharma.yaml et un fichier invalide."""
    shutil.copy(ROOT / "data" / "topology.yaml", tmp_path / "topology.yaml")
    (tmp_path / "topology_pharma.yaml").write_text(gen.topology_yaml(gen.build_topology("pharma", "Labo Test")), encoding="utf-8")
    (tmp_path / "topologies").mkdir()
    (tmp_path / "topologies" / "cassee.yaml").write_text(
        "nodes:\n  - {id: a, name: A, type: usine, tier: 1, criticality: 0.5}\n"
        "edges:\n  - {source: a, target: zzz, input: x, dependency: 1.0}\n", encoding="utf-8")
    (tmp_path / "replay_scenarios").mkdir()
    return tmp_path


@pytest.fixture
def custom(data_dir):
    return SupplyChainService(topology_path=data_dir / "topology.yaml", scenario_dir=data_dir / "replay_scenarios")


def test_list_topologies(service, custom):
    shipped = service.list_topologies()
    assert [(t["ref"], t["default"], t["nodes"]) for t in shipped] == [(None, True, 30), ("topologies/pharma_helvia.yaml", False, 19)]
    assert shipped[1]["company"] == "Helvia Pharma" and shipped[0]["active"] and not shipped[1]["active"]
    found = {t["ref"]: t for t in custom.list_topologies()}
    assert set(found) == {None, "topology_pharma.yaml", "topologies/cassee.yaml"}, "data/topology_*.yaml est détecté"
    assert found["topology_pharma.yaml"]["company"] == "Labo Test"


def test_live_run_on_chosen_topology(custom, monkeypatch):
    _fake_live(monkeypatch, [article(1, "Antibiotic shortage worsens as plants halt production")])
    res = asyncio.run(custom.run_pipeline(PipelineRunRequest(mode="live", topology="topology_pharma.yaml")))
    assert res.status == "success" and res.topology == "topology_pharma.yaml" and "Labo Test" in res.topology_name
    assert len(custom.engine.nodes) == 19 and custom.engine.mode == "live"
    assert {s.node_id for s in custom.engine.current.signals} == {"sup_api_in", "sup_api_cn"}
    assert [t["ref"] for t in custom.list_topologies() if t["active"]] == ["topology_pharma.yaml"]
    back = asyncio.run(custom.run_pipeline(PipelineRunRequest(mode="live")))
    assert back.topology is None and len(custom.engine.nodes) == 30, "sans choix : topologie par défaut"


def test_live_outage_on_new_topology_says_so(custom, monkeypatch):
    for cls, key in ((MediaAgent, "rss"), (WeatherAgent, "open_meteo"), (FinanceAgent, "yfinance")):
        async def down(self, report=None, _key=key, **k):
            report[_key] = {"status": "failed"}
            return []
        monkeypatch.setattr(cls, "collect_live", down)
    res = asyncio.run(custom.run_pipeline(PipelineRunRequest(mode="live", topology="topology_pharma.yaml")))
    assert res.status == "error" and "nouvelle topologie est chargée" in res.message and len(custom.engine.nodes) == 19


def test_topology_errors(custom):
    with pytest.raises(ScenarioNotFound):
        asyncio.run(custom.run_pipeline(PipelineRunRequest(mode="live", topology="../ailleurs.yaml")))
    with pytest.raises(ValueError, match="inconnu"):
        asyncio.run(custom.run_pipeline(PipelineRunRequest(mode="live", topology="topologies/cassee.yaml")))
    assert len(custom.engine.nodes) == 30, "une topologie invalide ne remplace pas la topologie en place"


def test_api_topologies_and_live_topology(custom, monkeypatch):
    _fake_live(monkeypatch, [])
    client = TestClient(create_app(custom))
    refs = [t["ref"] for t in client.get("/topologies").json()]
    assert refs[0] is None and "topology_pharma.yaml" in refs
    body = client.post("/pipeline/run", json={"mode": "live", "topology": "topology_pharma.yaml"}).json()
    assert body["status"] == "success" and body["topology"] == "topology_pharma.yaml" and body["n_events"] == 0
    assert len(client.get("/graph/state").json()["nodes"]) == 19
    assert client.post("/pipeline/run", json={"mode": "live", "topology": "absente.yaml"}).status_code == 404
    bad = client.post("/pipeline/run", json={"mode": "live", "topology": "topologies/cassee.yaml"})
    assert bad.status_code == 400 and "topologie invalide" in bad.json()["detail"]


# ----------------------------------------------------------------------------- 1 et 3. interface
pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = ROOT / "app"
MAIN, COPILOT = APP / "Tour_de_controle.py", APP / "pages" / "3_Copilot.py"


@pytest.fixture
def embedded(monkeypatch):
    monkeypatch.setenv("SC_EMBEDDED", "1")
    from app import common
    common._embedded_service.clear()


def start(path: Path) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def press(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


def test_sidebar_values_survive_page_changes(embedded):
    at = start(MAIN)
    at.selectbox(key="scenario_id").set_value("crisis_pharma_api").run()
    at.slider(key="day").set_value(3).run()
    at.toggle(key="use_llm").set_value(True).run()
    for page in ("pages/1_Graphe_et_simulation.py", "pages/3_Copilot.py", "Tour_de_controle.py"):
        at.switch_page(page).run()
        assert not at.exception, at.exception
        assert at.radio(key="mode_label").value == "Replay scénario"
        assert at.selectbox(key="scenario_id").value == "crisis_pharma_api", page
        assert at.slider(key="day").value == 3 and at.toggle(key="use_llm").value is True, page
    at.radio(key="mode_label").set_value("Live").run()
    at.selectbox(key="topology_ref").set_value("topologies/pharma_helvia.yaml").run()
    at.switch_page("pages/2_Alertes_et_preuves.py").run()
    assert at.radio(key="mode_label").value == "Live"
    assert at.selectbox(key="topology_ref").value == "topologies/pharma_helvia.yaml"
    at.radio(key="mode_label").set_value("Replay scénario").run()
    assert at.selectbox(key="scenario_id").value == "crisis_pharma_api" and at.slider(key="day").value == 3, \
        "revenir en replay retrouve le scénario et le jour"


def test_what_if_panel_survives_page_changes(embedded):
    at = start(MAIN)
    at.switch_page("pages/1_Graphe_et_simulation.py").run()
    at.selectbox(key="sim_node").set_value("port_rotterdam").run()
    at.slider(key="sim_severity").set_value(55).run()
    at.switch_page("pages/3_Copilot.py").run()
    at.switch_page("pages/1_Graphe_et_simulation.py").run()
    assert not at.exception, at.exception
    assert at.selectbox(key="sim_node").value == "port_rotterdam" and at.slider(key="sim_severity").value == 55


def test_day_is_clamped_when_scenario_is_shorter(embedded):
    at = start(MAIN)
    assert at.slider(key="day").value == 7
    at.selectbox(key="scenario_id").set_value("crisis_pharma_api").run()
    assert not at.exception and at.slider(key="day").value == 6


def test_copilot_history_is_cleared_by_a_new_run(embedded):
    at = press(start(COPILOT), "Exécuter le pipeline")
    press(at, "Produits menacés")
    assert len(at.chat_message) == 2
    press(at, "Exécuter le pipeline")
    assert len(at.chat_message) == 0 and at.session_state["chat_context"] == {}


def test_copilot_history_is_cleared_by_scenario_or_mode_change(embedded):
    at = press(start(COPILOT), "Exécuter le pipeline")
    press(at, "Produits menacés")
    at.slider(key="day").set_value(2).run()
    assert len(at.chat_message) == 2, "changer de jour sans exécuter ne vide pas la conversation"
    at.selectbox(key="scenario_id").set_value("crisis_pharma_api").run()
    assert len(at.chat_message) == 0
    press(at, "Produits menacés")
    assert len(at.chat_message) == 2
    at.radio(key="mode_label").set_value("Live").run()
    assert len(at.chat_message) == 0
    press(at, "Produits menacés")
    at.selectbox(key="topology_ref").set_value("topologies/pharma_helvia.yaml").run()
    assert len(at.chat_message) == 0, "changer de topologie en live vide aussi la conversation"


def test_clear_button_in_copilot_page(embedded):
    at = start(COPILOT)
    clear = next(b for b in at.button if b.label == "Effacer la conversation")
    assert clear.disabled, "rien à effacer tant qu'il n'y a pas de message"
    press(at, "Produits menacés")
    press(at, "Expliquer les alertes")
    assert len(at.chat_message) == 4
    press(at, "Effacer la conversation")
    assert len(at.chat_message) == 0 and at.session_state["chat"] == []


def test_live_topology_selector_runs_on_chosen_chain(embedded, monkeypatch):
    _fake_live(monkeypatch, [article(1, "Antibiotic shortage worsens as plants halt production")])
    at = start(MAIN)
    at.radio(key="mode_label").set_value("Live").run()
    options = at.selectbox(key="topology_ref").options
    assert len(options) == 2 and any("Helvia Pharma" in o for o in options)
    at.selectbox(key="topology_ref").set_value("topologies/pharma_helvia.yaml").run()
    press(at, "Exécuter le pipeline")
    assert any("Helvia Pharma" in c.value and "Mode live" in c.value for c in at.caption)
    at.switch_page("pages/1_Graphe_et_simulation.py").run()
    assert not at.exception and at.selectbox(key="sim_node").value.startswith(("port_", "hub_"))
