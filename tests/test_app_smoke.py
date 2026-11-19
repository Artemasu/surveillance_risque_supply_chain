"""Les quatre pages Streamlit s'exécutent sans exception, sur le moteur embarqué (pas besoin de l'API)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pyvis")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app"
PAGES = [APP / "Tour_de_controle.py", APP / "pages" / "1_Graphe_et_simulation.py",
         APP / "pages" / "2_Alertes_et_preuves.py", APP / "pages" / "3_Copilot.py"]


@pytest.fixture(autouse=True)
def embedded(monkeypatch):
    monkeypatch.setenv("SC_EMBEDDED", "1")
    from app import common
    common._embedded_service.clear()


def launch(path: Path) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.stem)
def test_page_runs_before_and_after_pipeline(path):
    at = launch(path)
    assert any("Aucune donnée chargée" in i.value for i in at.info)
    click(at, "Exécuter le pipeline")
    assert not at.error and not any("Aucune donnée chargée" in i.value for i in at.info)


def test_dashboard_kpis():
    at = click(launch(PAGES[0]), "Exécuter le pipeline")
    metrics = {m.label: m.value for m in at.metric}
    assert float(metrics["Indice de risque global (sur 100)"]) > 30
    assert int(metrics["Alertes actives"]) > 0 and int(metrics["Signaux Météo"]) > 0
    assert any("Scénario fictif" in c.value for c in at.caption)


def test_what_if_panel():
    at = launch(PAGES[1])
    at.selectbox(key="sim_node").set_value("port_kaohsiung")
    at.slider(key="sim_severity").set_value(80)
    at.toggle(key="sim_on").set_value(True).run()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert float(metrics["Indice global simulé"].split()[0]) > 0 and int(metrics["Produits finis menacés"]) == 3
    assert any("Plan de contournement" in s.value for s in at.subheader)


def test_copilot_quick_question_and_free_text():
    at = click(launch(PAGES[3]), "Exécuter le pipeline")
    click(at, "Produits menacés")
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert "E-City" in at.chat_message[1].markdown[0].value
    at.chat_input[0].set_value("Simule une fermeture du port de Rotterdam").run()
    assert not at.exception and len(at.chat_message) == 4
    assert "Port of Rotterdam" in at.chat_message[3].markdown[0].value


def test_switching_to_pharma_scenario_in_the_ui():
    """Un scénario d'un autre secteur charge sa topologie : graphe, panneau what-if et questions rapides suivent."""
    at = launch(PAGES[1])
    assert at.selectbox(key="sim_node").value == "port_kaohsiung"
    at.selectbox(key="scenario_id").set_value("crisis_pharma_api").run()
    click(at, "Exécuter le pipeline")
    assert any("jour 6 / 6" in c.value for c in at.caption)
    node = at.selectbox(key="sim_node").value
    assert node != "port_kaohsiung" and node.startswith(("port_", "hub_"))
    at.toggle(key="sim_on").set_value(True).run()
    assert not at.exception, at.exception

    chat = launch(PAGES[3])
    at2 = click(chat, "Exécuter le pipeline")
    at2.selectbox(key="scenario_id").set_value("crisis_pharma_api").run()
    click(at2, "Exécuter le pipeline")
    labels = [b.label for b in at2.button]
    assert "Antwerp bloqué à 80 %" in labels and not any("Kaohsiung" in label for label in labels)
    click(at2, "Antwerp bloqué à 80 %")
    assert "Port of Antwerp" in at2.chat_message[1].markdown[0].value
