"""Inscription d'un client : topologie valide, données personnelles séparées, droits d'accès et d'effacement."""
import json

import pytest
from fastapi.testclient import TestClient

from src.api import routes_clients
from src.api.main import create_app
from src.onboarding import NOTICE_VERSION
from src.service import SupplyChainService

LIEUX = {"Lyon": (45.76, 4.84), "Hyderabad": (17.39, 78.49), "Mainz": (50.0, 8.27), "Anvers": (51.27, 4.34)}


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "topologies").mkdir(parents=True)
    (data / "replay_scenarios").mkdir()
    monkeypatch.setattr(routes_clients, "_geocoder", lambda ville, pays: dict(zip(("lat", "lon"), LIEUX[ville])))
    service = SupplyChainService()
    service.data_dir = data
    return TestClient(create_app(service)), data


def inscription(**chaine) -> dict:
    corps = {
        "entreprise": {"raison_sociale": "Orvane Santé", "secteur": "Pharmacie", "pays": "France", "taille": "PME"},
        "contact": {"prenom": "Camille", "nom": "Martin", "email": "c.martin@orvane-sante.fr", "fonction": "Achats"},
        "pseudonymiser_fournisseurs": True,
        "consentements": {"traitement": True, "habilitation": True, "version_notice": NOTICE_VERSION},
    }
    corps.update(chaine or {"chaine": {
        "sites": [{"nom": "Usine de Lyon", "ville": "Lyon", "pays": "France", "stock_jours": 20}],
        "points_logistiques": [{"nom": "Port d'Anvers", "ville": "Anvers", "pays": "Belgique", "type": "port"}],
        "fournisseurs": [
            {"nom": "Deccan Actives", "ville": "Hyderabad", "pays": "Inde", "categorie": "principe actif",
             "site": "Usine de Lyon", "part_pct": 70, "passage": "Port d'Anvers", "critique": True},
            {"nom": "Rheinglas", "ville": "Mainz", "pays": "Allemagne", "categorie": "principe actif",
             "site": "Usine de Lyon", "part_pct": 30},
            {"nom": "Verrerie du Rhin", "ville": "Mainz", "pays": "Allemagne", "categorie": "flacons",
             "site": "Usine de Lyon", "part_pct": 100}],
        "produits": [{"nom": "Antibiotique injectable", "site": "Usine de Lyon"}]}})
    return corps


def test_inscription_chaine_declaree(client):
    c, data = client
    r = c.post("/clients/inscription", json=inscription())
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["noeuds"] == 6 and res["topology_ref"].startswith("topologies/client_")
    topo = (data / res["topology_ref"]).read_text(encoding="utf-8")
    # séparation : ni nom, ni e-mail dans la topologie ; fournisseurs pseudonymisés
    assert "Martin" not in topo and "orvane-sante.fr" not in topo and "Deccan" not in topo
    assert "Fournisseur A (principe actif)" in topo
    fiche = json.loads((data / "clients" / f"{res['client_id']}.json").read_text(encoding="utf-8"))
    assert fiche["contact"]["email"] == "c.martin@orvane-sante.fr" and fiche["consentements"]["version_notice"] == NOTICE_VERSION
    scenario = json.loads((data / "replay_scenarios" / f"{res['scenario_id']}.json").read_text(encoding="utf-8"))
    assert set(scenario) == {"meta", "media", "weather", "finance"} and scenario["meta"]["topology"] == res["topology_ref"]
    assert any("Fournisseur C" in p for p in res["points_faibles"])     # flacons : source unique
    assert any(t["ref"] == res["topology_ref"] for t in c.get("/topologies").json())


def test_inscription_gabarit_et_droits(client):
    c, data = client
    res = c.post("/clients/inscription", json=inscription(gabarit="pharma")).json()
    export = c.get(f"/clients/{res['client_id']}/export").json()
    assert export["fiche"]["entreprise"]["raison_sociale"] == "Orvane Santé" and "Orvane" in export["topologie"]
    assert len(c.delete(f"/clients/{res['client_id']}").json()["supprimes"]) == 3
    assert not list((data / "clients").glob("*.json")) and not list((data / "topologies").glob("client_*"))
    assert c.get(f"/clients/{res['client_id']}/export").status_code == 404
    assert c.delete("/clients/../../etc").status_code in (404, 405)


@pytest.mark.parametrize("modif", [
    lambda d: d["contact"].update(email="camille@gmail.com"),                      # e-mail non professionnel
    lambda d: d["consentements"].update(traitement=False),                         # consentement absent
    lambda d: d["consentements"].update(version_notice="ancienne"),                # notice périmée
    lambda d: d.update(gabarit="pharma"),                                          # gabarit ET chaîne
    lambda d: d["chaine"]["fournisseurs"][0].update(site="Usine inconnue"),        # référence cassée
    lambda d: d.update(champ_inconnu=1),                                           # champ non prévu
])
def test_inscription_refusee(client, modif):
    c, data = client
    corps = inscription()
    modif(corps)
    assert c.post("/clients/inscription", json=corps).status_code == 422
    assert not (data / "clients").exists()
