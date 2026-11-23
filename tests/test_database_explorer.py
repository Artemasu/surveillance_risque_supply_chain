"""Explorateur de la base unifiée : lecture seule, pagination, filtres, export CSV, graphe unifié."""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.routes_database import TABLES
from src.storage import db
from tests.conftest import SCENARIO


@pytest.fixture
def client():
    c = TestClient(create_app())
    assert c.post("/pipeline/run", json={"mode": "replay", "scenario": SCENARIO, "day": 7}).status_code == 200
    return c


def test_empty_database():
    c = TestClient(create_app())                       # le service crée la base (référentiel des liaisons)
    s = c.get("/database/summary").json()
    assert s["ready"] and s["domains"]["weather"]["indicateurs"] == 0 and s["domains"]["unified"]["liaisons_referentiel"] > 0
    assert c.get("/database/tables/weather_indicators").json()["total"] == 0
    assert c.get("/database/unified-graph").json()["run"] is None


def test_summary_counts_match_tables(client):
    s = client.get("/database/summary").json()
    assert s["ready"] and s["domains"]["unified"]["evenements"] == int(db.query("SELECT count(*) n FROM events")["n"].iloc[0])
    assert set(s["domains"]["unified"]["par_agent"]) == {"media", "weather", "finance"}
    assert s["domains"]["media"]["articles"] >= s["domains"]["media"]["evenements"]


def test_every_table_pages_and_filters(client):
    for name in TABLES:
        r = client.get(f"/database/tables/{name}", params={"limit": 3})
        if name == "finance_sanctions":
            continue                                   # absente tant que ingest-finance n'a pas tourné
        assert r.status_code == 200, name
        assert len(r.json()["rows"]) <= 3
    unified = client.get("/database/tables/unified", params={"agent": "weather", "limit": 500}).json()
    assert unified["total"] > 0 and {r["domaine"] for r in unified["rows"]} == {"weather"}
    assert all(0 < r["intensite"] <= 1 for r in unified["rows"]) and "payload" not in unified["columns"]
    page2 = client.get("/database/tables/unified", params={"limit": 2, "offset": 2}).json()
    page1 = client.get("/database/tables/unified", params={"limit": 2, "offset": 0}).json()
    assert page1["total"] == page2["total"] and page1["rows"] != page2["rows"]
    media = client.get("/database/tables/media", params={"q": "Kaohsiung"}).json()
    assert media["total"] > 0 and all("kaohsiung" in (r["titre"] + (r["entites"] or "") + (r["noeuds"] or "")).lower() for r in media["rows"])


def test_csv_export_and_unknown_table(client):
    r = client.get("/database/tables/unified", params={"format": "csv", "agent": "media"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("event_id,domaine") and len(lines) > 1
    assert client.get("/database/tables/users").status_code == 404
    assert client.get("/database/tables/unified/values", params={"column": "payload"}).status_code == 404


def test_queries_are_read_only(client):
    # l'injection dans un paramètre reste une valeur : rien n'est exécuté, la table existe toujours
    r = client.get("/database/tables/unified", params={"q": "x'; DROP TABLE events; --"})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert int(db.query("SELECT count(*) n FROM events")["n"].iloc[0]) > 0


def test_unified_graph(client):
    g = client.get("/database/unified-graph").json()
    assert len(g["nodes"]) == 30 and g["run"]["as_of"] == "2026-09-20"
    ids = {n["id"] for n in g["nodes"]}
    assert g["events"] and all(l["node_id"] in ids for e in g["events"] for l in e["links"])
    assert {e["agent"] for e in g["events"]} == {"media", "weather", "finance"}
