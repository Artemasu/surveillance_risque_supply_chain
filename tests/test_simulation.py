"""Simulation what-if et plan de mitigation."""
import copy

import pytest

from tests.conftest import media_event


def test_simulation_does_not_alter_real_state(engine):
    engine.ingest([media_event("e1", "greve", "2026-09-18", "port_rotterdam", "Port of Rotterdam")], "2026-09-18")
    before = (copy.deepcopy(engine.current.risks), dict(engine.current.direct), engine.current.index,
              [e.event.id for e in engine.events], engine.state().model_dump())
    sim = engine.simulate_disruption("port_kaohsiung", 0.8)
    assert sim.simulated_index > sim.baseline_index
    after = (engine.current.risks, engine.current.direct, engine.current.index,
             [e.event.id for e in engine.events], engine.state().model_dump())
    assert before == after


def test_shock_wave_and_threatened_products(engine):
    sim = engine.simulate_disruption("port_kaohsiung", 0.8)
    touched = {i.node_id: i for i in sim.impacts}
    assert set(touched) == {"port_kaohsiung", "port_rotterdam", "plant_ecu_de", "plant_assembly_fr", "plant_assembly_de",
                            "prod_ev_compact", "prod_ev_suv", "prod_inverter"}
    assert touched["port_kaohsiung"].simulated == pytest.approx(0.8)
    assert sim.impacts[0].node_id == "port_kaohsiung", "impacts triés du plus fort au plus faible"
    assert {p.node_id for p in sim.threatened_products} == {"prod_ev_compact", "prod_ev_suv", "prod_inverter"}
    assert touched["prod_ev_compact"].path[0] == "port_kaohsiung"
    assert {n.id: n.risk for n in sim.nodes}["port_kaohsiung"] == pytest.approx(0.8)


def test_severity_is_monotonic(engine):
    indexes = [engine.simulate_disruption("port_rotterdam", s).simulated_index for s in (0.0, 0.3, 0.6, 1.0)]
    assert indexes == sorted(indexes) and indexes[0] == 0 and indexes[-1] > indexes[1]


def test_simulation_never_lowers_an_existing_risk(engine):
    engine.ingest([media_event("e1", "faillite", "2026-09-18", "sup_chip_tw", "Formoz Power Semi", n_sources=3)], "2026-09-18")
    sim = engine.simulate_disruption("sup_chip_tw", 0.1)
    assert sim.impacts == [] and sim.simulated_index == sim.baseline_index


def test_unknown_node_and_bad_severity(engine):
    with pytest.raises(KeyError):
        engine.simulate_disruption("port_atlantis", 0.5)
    with pytest.raises(ValueError):
        engine.simulate_disruption("port_rotterdam", 1.5)


def test_alternatives_exclude_sources_that_depend_on_the_failed_node(engine):
    rows = {(r["customer_id"], r["input"]): r for r in engine.alternative_suppliers("port_kaohsiung")}
    assert [a["node_id"] for a in rows[("port_rotterdam", "fret_puces")]["alternatives"]] == ["port_keelung"]
    plant = {a["node_id"]: a for a in rows[("plant_ecu_de", "puces_puissance")]["alternatives"]}
    assert set(plant) == {"sup_chip_nl", "hub_air_fra"}, "Hambourg dépend de Kaohsiung : il n'est pas proposé"
    assert plant["sup_chip_nl"]["kind"] == "actif" and plant["sup_chip_nl"]["spare_capacity"] == pytest.approx(0.2)
    assert plant["hub_air_fra"]["kind"] == "secours"


def test_mitigation_plan(engine):
    plan = engine.mitigation_plan("port_rotterdam")
    kinds = [a.kind for a in plan.actions]
    assert kinds == sorted(kinds, key=["reallocation", "route_secours", "stock", "surveillance"].index)
    targets = {a.target for a in plan.actions}
    assert {"Waal Semiconductors", "Port of Hamburg", "Fret aérien Francfort"} <= targets
    assert plan.coverage["Rhein Power Modules (Stuttgart) / puces_puissance"] == pytest.approx(1.0)
    assert "Citadine électrique E-City" in plan.threatened_products
    single = engine.mitigation_plan("sup_magnet_cn")              # source unique : rien à réallouer
    assert not [a for a in single.actions if a.kind in ("reallocation", "route_secours")]
    assert single.coverage["Kansai Drive / aimants"] == 0


def test_dependency_ranking(engine):
    ranking = engine.dependency_ranking("prod_ev_compact")
    assert ranking[0]["risk_if_down"] >= ranking[-1]["risk_if_down"]
    assert ranking[0]["node_id"] in {"plant_assembly_fr", "plant_ecu_de", "plant_pack_fr", "port_hamburg"}
    assert set(engine.downstream_products("plant_ecu_de")) == {"prod_ev_compact", "prod_ev_suv", "prod_inverter"}
