"""Endpoints FastAPI via TestClient."""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.service import SupplyChainService
from tests.conftest import SCENARIO


@pytest.fixture
def client():
    return TestClient(create_app(SupplyChainService()))


@pytest.fixture
def loaded(client):
    r = client.post("/pipeline/run", json={"mode": "replay", "scenario": SCENARIO, "day": 5})
    assert r.status_code == 200
    return client


def test_health_and_openapi(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["nodes"] >= 25 and h["last_run"] is None
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/pipeline/run", "/graph/state", "/graph/simulate", "/alerts", "/chat"} <= set(paths)
    assert client.get("/docs").status_code == 200


def test_empty_state_before_first_run(client):
    assert client.get("/graph/state").json()["global_risk_index"] == 0
    assert client.get("/alerts").json() == []
    assert client.get("/events").json()["events"] == []


def test_pipeline_run_replay(client):
    body = client.post("/pipeline/run", json={"mode": "replay", "scenario": SCENARIO, "day": 5}).json()
    assert body["status"] == "success" and body["day"] == 5 and body["days_total"] == 7 and body["as_of"] == "2026-09-18"
    assert body["fictional"] is True and len(body["timeline"]) == 5 and body["n_alerts"] > 0
    assert set(body["agents"]) == {"media", "weather", "finance"}
    assert client.get("/health").json()["last_run"]["as_of"] == "2026-09-18"
    default = client.post("/pipeline/run", json={}).json()
    assert default["mode"] == "replay" and default["day"] == 7


def test_pipeline_run_validation(client):
    assert client.post("/pipeline/run", json={"mode": "demo"}).status_code == 422
    assert client.post("/pipeline/run", json={"mode": "replay", "day": 0}).status_code == 422
    assert client.post("/pipeline/run", json={"mode": "replay", "inconnu": 1}).status_code == 422
    assert client.post("/pipeline/run", json={"mode": "replay", "scenario": "inconnu"}).status_code == 404


def test_graph_state(loaded):
    state = loaded.get("/graph/state").json()
    nodes = {n["id"]: n for n in state["nodes"]}
    assert state["as_of"] == "2026-09-18" and state["mode"] == f"replay:{SCENARIO}"
    assert "port_kaohsiung" in state["critical_nodes"] and nodes["port_kaohsiung"]["level"] == "critical"
    assert nodes["prod_ev_compact"]["path"][0] == "port_kaohsiung"
    assert all({"source", "target", "dependency", "backup"} <= set(e) for e in state["edges"])
    assert sum(e["backup"] for e in state["edges"]) >= 5


def test_graph_simulate(client):
    before = client.get("/graph/state").json()
    sim = client.post("/graph/simulate", json={"node_id": "port_rotterdam", "severity": 1.0}).json()
    assert sim["node_name"] == "Port of Rotterdam" and sim["simulated_index"] > sim["baseline_index"] == 0
    assert {p["node_id"] for p in sim["threatened_products"]} == {"prod_ev_compact", "prod_ev_suv", "prod_inverter"}
    assert any(a["kind"] == "route_secours" for a in sim["mitigation"]["actions"])
    assert len(sim["nodes"]) == len(before["nodes"])
    assert client.get("/graph/state").json() == before, "la simulation ne modifie pas l'état réel"


def test_graph_simulate_errors(client):
    assert client.post("/graph/simulate", json={"node_id": "port_atlantis", "severity": 0.5}).status_code == 404
    assert client.post("/graph/simulate", json={"node_id": "port_rotterdam", "severity": 1.5}).status_code == 422
    assert client.post("/graph/simulate", json={"node_id": "port_rotterdam"}).status_code == 422


def test_alerts_and_filters(loaded):
    alerts = loaded.get("/alerts").json()
    assert alerts and all({"rule", "path", "source_ids", "priority"} <= set(a) for a in alerts)
    assert [a["priority"] for a in alerts] == sorted((a["priority"] for a in alerts), reverse=True)
    critical = loaded.get("/alerts", params={"level": "critical"}).json()
    assert critical and all(a["level"] == "critical" for a in critical) and len(critical) < len(alerts)
    assert all("weather" in a["agents"] for a in loaded.get("/alerts", params={"agent": "weather"}).json())
    assert loaded.get("/alerts", params={"level": "enorme"}).status_code == 422


def test_events(loaded):
    body = loaded.get("/events").json()
    assert {e["agent"] for e in body["events"]} == {"media", "weather", "finance"}
    first = body["events"][0]["event"]
    assert list(first) == ["event", "date", "location", "entities", "weather", "finance", "media", "donnees_manquantes", "meta"]
    assert any(s["corroborated"] for s in body["signals"]) and all("node_name" in s for s in body["signals"])


def test_chat(loaded):
    r = loaded.post("/chat", json={"message": "Quels produits finis sont menacés aujourd'hui ?"}).json()
    assert r["mode"] == "deterministic" and r["tool_calls"][0]["name"] == "produits_menaces" and "E-City" in r["answer"]
    sim = loaded.post("/chat", json={"message": "Simule une fermeture du port de Rotterdam"}).json()
    plan = loaded.post("/chat", json={"message": "Propose un plan de contournement", "context": sim["context"],
                                      "history": [{"role": "user", "content": "Simule une fermeture du port de Rotterdam"},
                                                  {"role": "assistant", "content": sim["answer"]}]}).json()
    assert plan["tool_calls"][0]["arguments"] == {"noeud": "port_rotterdam"} and "Port of Hamburg" in plan["answer"]
    assert loaded.post("/chat", json={"message": ""}).status_code == 422
    assert loaded.post("/chat", json={}).status_code == 422
