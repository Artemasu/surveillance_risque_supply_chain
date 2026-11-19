"""Topologie, corrélation multi-sources et propagation en cascade."""
import networkx as nx
import pytest

from src.graph.ontology_engine import DECAY, OntologyEngine, level_of
from tests.conftest import media_event, weather_event


def test_topology_is_rich_and_consistent(engine):
    assert len(engine.nodes) >= 25
    types = {n.type for n in engine.nodes.values()}
    assert types == {"matiere_premiere", "fournisseur", "port", "hub", "usine", "produit_fini"}
    assert nx.is_directed_acyclic_graph(engine.graph)
    for product in [n.id for n in engine.nodes.values() if n.type == "produit_fini"]:
        ancestors = nx.ancestors(engine.active, product)
        assert any(engine.nodes[a].type == "matiere_premiere" for a in ancestors), product


def test_topology_rejects_bad_shares_and_cycles():
    node = lambda i: {"id": i, "name": i, "type": "fournisseur", "tier": 2, "criticality": 0.5}
    edge = lambda s, t, d: {"source": s, "target": t, "input": "x", "dependency": d}
    with pytest.raises(ValueError, match="parts d'intrant"):
        OntologyEngine({"nodes": [node("a"), node("b"), node("c")], "edges": [edge("a", "c", 0.5), edge("b", "c", 0.3)]})
    with pytest.raises(ValueError, match="cycle"):
        OntologyEngine({"nodes": [node("a"), node("b")], "edges": [edge("a", "b", 1.0), edge("b", "a", 1.0)]})
    with pytest.raises(ValueError, match="inconnu"):
        OntologyEngine({"nodes": [node("a")], "edges": [edge("a", "z", 1.0)]})


def test_no_event_means_no_risk(engine):
    assert engine.current.index == 0
    assert all(r["risk"] == 0 for r in engine.current.risks.values())
    assert engine.alerts() == []


def test_cascade_reaches_finished_products(engine):
    engine.ingest([media_event("e1", "faillite", "2026-09-16", "sup_chip_tw", "Formoz Power Semi", n_sources=3)], "2026-09-16")
    r = engine.current.risks
    chain = ["sup_chip_tw", "port_kaohsiung", "port_rotterdam", "plant_ecu_de", "plant_assembly_fr", "prod_ev_compact"]
    assert r["sup_chip_tw"]["direct"] > 0.6
    risks = [r[n]["risk"] for n in chain]
    assert all(x > 0 for x in risks)
    assert risks == sorted(risks, reverse=True), "le risque s'atténue à chaque lien"
    assert r["prod_ev_compact"]["path"] == chain, "le chemin dominant explique l'alerte"
    assert r["rm_lithium"]["risk"] == 0, "une branche sans lien n'est pas touchée"
    assert r["sup_wafer_tw"]["risk"] == 0, "le risque ne remonte pas vers l'amont"


def test_redundancy_dilutes_and_stock_dampens(engine):
    """Source unique : transmission entière. Deux sources : seule la part de la source en panne passe."""
    out = engine.propagate({"sup_chip_nl": 1.0})
    plant = engine.nodes["plant_ecu_de"]
    expected = DECAY * (1 - plant.stock_days / 120) * 0.3          # Waal couvre 30 % des puces de Stuttgart
    assert out["plant_ecu_de"]["propagated"] == pytest.approx(expected, abs=1e-3)

    single = engine.propagate({"sup_magnet_cn": 1.0})              # aimants : source unique du fabricant de moteurs
    motor = engine.nodes["sup_motor_jp"]
    assert single["sup_motor_jp"]["propagated"] == pytest.approx(DECAY * (1 - motor.stock_days / 120), abs=1e-3)
    assert single["sup_motor_jp"]["propagated"] > out["plant_ecu_de"]["propagated"]


def test_backup_links_do_not_propagate(engine):
    out = engine.propagate({"hub_air_fra": 1.0, "port_keelung": 1.0})
    assert out["plant_ecu_de"]["risk"] == 0 and out["port_rotterdam"]["risk"] == 0


def test_weather_and_media_cross_validate_on_same_hub(engine):
    media = media_event("m1", "catastrophe", "2026-09-16", "port_kaohsiung", "Port of Kaohsiung")
    weather = weather_event("w1", "2026-09-15", "port_kaohsiung", "Port of Kaohsiung")
    alone = engine.evaluate([media], "2026-09-16")
    both = engine.evaluate([media, weather], "2026-09-16")
    assert len(alone.signals) == 1 and not alone.signals[0].corroborated
    assert len(both.signals) == 1, "même nœud, même famille d'aléa : un seul signal"
    sig = both.signals[0]
    assert sig.corroborated and sig.agents == ["media", "weather"] and len(sig.source_ids) == 2
    assert sig.confidence > alone.signals[0].confidence
    assert both.direct["port_kaohsiung"] > alone.direct["port_kaohsiung"]


def test_duplicates_are_merged_not_added(engine):
    one = engine.evaluate([media_event("a", "greve", "2026-09-18", "port_rotterdam", "Port of Rotterdam")], "2026-09-18")
    two = engine.evaluate([media_event("a", "greve", "2026-09-18", "port_rotterdam", "Port of Rotterdam"),
                           media_event("b", "logistique", "2026-09-19", "port_rotterdam", "Port of Rotterdam")], "2026-09-19",
                          dedupe=False)          # ici on teste le regroupement en signal, pas la fusion sémantique
    assert len(two.signals) == 1 and two.signals[0].event_ids == ["a", "b"]
    assert two.direct["port_rotterdam"] < 2 * one.direct["port_rotterdam"], "deux articles ne doublent pas le risque"


def test_distant_events_form_two_signals(engine):
    ev = engine.evaluate([media_event("a", "greve", "2026-09-01", "port_rotterdam", "Port of Rotterdam"),
                          media_event("b", "greve", "2026-09-18", "port_rotterdam", "Port of Rotterdam")], "2026-09-18")
    assert len(ev.signals) == 2
    old, new = sorted(ev.signals, key=lambda s: s.first_date)
    assert old.contribution < new.contribution, "un signal ancien pèse moins"


def test_event_linking_by_alias_and_place(engine):
    by_place = media_event("a", "logistique", "2026-09-15", "inconnu", "Entreprise inconnue", place="Port of Kaohsiung")
    assert engine.link_event(by_place) == ["port_kaohsiung"]
    by_alias = media_event("b", "penurie", "2026-09-19", "x", "Rhein Power Modules")
    assert engine.link_event(by_alias) == ["plant_ecu_de"]
    nowhere = media_event("c", "catastrophe", "2026-09-14", "x", "Entreprise inconnue", place="Taiwan")
    assert engine.link_event(nowhere) == []
    assert engine.evaluate([nowhere], "2026-09-14").index == 0, "un événement non rattaché ne crée pas de risque"


def test_alerts_are_explained_and_prioritised(engine):
    engine.ingest([media_event("m1", "catastrophe", "2026-09-16", "sup_chip_tw", "Formoz Power Semi", n_sources=2),
                   weather_event("w1", "2026-09-16", "sup_chip_tw", "Formoz Power Semi")], "2026-09-16")
    alerts = engine.alerts()
    assert alerts and [a.priority for a in alerts] == sorted((a.priority for a in alerts), reverse=True)
    origin = next(a for a in alerts if a.node_id == "sup_chip_tw")
    assert origin.level == "critical" and "corroboré" in origin.rule
    downstream = next(a for a in alerts if a.node_id == "plant_ecu_de")
    assert downstream.path[0] == "sup_chip_tw" and downstream.path_names[-1].startswith("Rhein")
    assert "Risque propagé" in downstream.rule
    assert {"test:m1:0", "test:meteo:w1"} <= set(downstream.source_ids), "l'alerte cite ses sources"
    assert downstream.agents == ["media", "weather"]


def test_levels_and_global_index(engine):
    assert [level_of(x) for x in (0.0, 0.2, 0.4, 0.7)] == ["ok", "info", "warning", "critical"]
    low = engine.global_index(engine.propagate({"rm_copper": 1.0}))
    high = engine.global_index(engine.propagate({"sup_chip_tw": 1.0}))
    assert 0 < low < high <= 100


def test_resolve_node_from_free_text(engine):
    assert engine.resolve_node("Simule une fermeture du port de Rotterdam") == "port_rotterdam"
    assert engine.resolve_node("que se passe-t-il si Kaohsiung est bloqué ?") == "port_kaohsiung"
    assert engine.resolve_node("une panne chez Formoz") == "sup_chip_tw"
    assert engine.resolve_node("le port de Roterdam") == "port_rotterdam"      # faute de frappe
    assert engine.resolve_node("bonjour, quel temps fait-il ?") is None


def test_referentials_for_media_agent(engine):
    companies = {c["id"]: c for c in engine.company_referential()}
    assert companies["plant_ecu_de"]["name"] == "Rhein Power Modules"
    places = {p["name"]: p for p in engine.place_referential()}
    assert places["Port of Kaohsiung"]["precision"] == 3 and places["Tainan"]["precision"] == 2
    assert places["Taiwan"]["precision"] == 1


# ----------------------------------------------------------------------------- déduplication sémantique
def _article_event(eid, etype, day, title, node="port_rotterdam", name="Port of Rotterdam"):
    ev = media_event(eid, etype, day, node, name)
    media = [m.model_copy(update={"titre": title}) for m in ev.media]
    return ev.model_copy(update={"media": media, "event": ev.event.model_copy(update={"label": title})})


def test_semantic_dedupe_merges_same_incident_before_severity(engine):
    """Deux articles sur la même grève, classés dans deux familles : sans fusion, l'incident compterait deux fois."""
    a = _article_event("a", "greve", "2026-09-18", "Strike halts container handling at Port of Rotterdam terminals")
    b = _article_event("b", "penurie", "2026-09-19", "Strike halts container handling at Rotterdam port terminals, shippers say")
    raw = engine.evaluate([a, b], "2026-09-19", dedupe=False)
    fused = engine.evaluate([a, b], "2026-09-19")
    assert len(raw.signals) == 2 and len(fused.signals) == 1
    assert fused.merged == {"a": ["b"]} and [e.event.id for e in fused.events] == ["a"]
    ev = fused.events[0]
    assert ev.event.type == "greve" and ev.date == "2026-09-18" and len(ev.media) == 2, "toutes les sources sont gardées"
    assert "fusion sémantique avec b" in ev.meta.detail
    assert fused.direct["port_rotterdam"] < raw.direct["port_rotterdam"], "l'incident ne compte qu'une fois"
    assert fused.signals[0].source_ids == ["test:a:0", "test:b:0"]


def test_semantic_dedupe_keeps_distinct_incidents(engine):
    rotterdam = _article_event("a", "greve", "2026-09-18", "Strike halts container handling at Port of Rotterdam terminals")
    hamburg = _article_event("b", "greve", "2026-09-18", "Strike halts container handling at Port of Hamburg terminals",
                             node="port_hamburg", name="Port of Hamburg")
    later = _article_event("c", "greve", "2026-09-28", "Strike halts container handling at Port of Rotterdam terminals again")
    other = _article_event("d", "cyberattaque", "2026-09-18", "Ransomware attack shuts down customs systems")
    out, merged = engine.semantic_dedupe([rotterdam, hamburg, later, other])
    assert merged == {} and len(out) == 4, "autre port, autre semaine ou autre sujet : pas de fusion"


def test_semantic_dedupe_ignores_weather_and_finance_events(engine):
    w1 = weather_event("w1", "2026-09-16", "port_kaohsiung", "Port of Kaohsiung")
    w2 = weather_event("w2", "2026-09-16", "port_kaohsiung", "Port of Kaohsiung")
    out, merged = engine.semantic_dedupe([w1, w2])
    assert out == [w1, w2] and merged == {}


def test_ingest_stores_deduplicated_events(engine):
    a = _article_event("a", "greve", "2026-09-18", "Dockworkers strike closes Port of Rotterdam container terminals")
    b = _article_event("b", "greve", "2026-09-18", "Dockworkers strike closes the Port of Rotterdam container terminals")
    engine.ingest([a, b], "2026-09-18")
    assert [e.event.id for e in engine.events] == ["a"] and engine.current.links == {"a": ["port_rotterdam"]}
