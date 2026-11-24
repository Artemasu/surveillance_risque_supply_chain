"""Comptes : routes protégées, connexion, droits limités au client connecté."""
import pytest
from fastapi.testclient import TestClient

from src import auth
from src.api import routes_clients
from src.api.main import create_app
from src.service import SupplyChainService
from tests.test_onboarding import LIEUX, inscription


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SC_AUTH", "1")
    auth._essais.clear()
    data = tmp_path / "data"
    (data / "topologies").mkdir(parents=True)
    (data / "replay_scenarios").mkdir()
    monkeypatch.setattr(routes_clients, "_geocoder", lambda ville, pays: dict(zip(("lat", "lon"), LIEUX[ville])))
    service = SupplyChainService()
    service.data_dir, service.scenario_dir = data, data / "replay_scenarios"
    return TestClient(create_app(service)), data


def entete(c, email, mdp):
    r = c.post("/auth/connexion", json={"email": email, "mot_de_passe": mdp})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['jeton']}"}, r.json()["profil"]


def test_routes_protegees_et_publiques(app):
    c, _ = app
    assert c.get("/health").status_code == 200 and c.get("/clients/parametres").status_code == 200
    for path in ("/graph/state", "/alerts", "/topologies", "/scenarios", "/auth/moi"):
        assert c.get(path).status_code == 401
    assert c.get("/alerts", headers={"Authorization": "Bearer faux.jeton"}).status_code == 401
    assert c.options("/alerts", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}).status_code == 200


def test_client_inscrit_se_connecte_et_ne_voit_que_ses_donnees(app):
    c, data = app
    a = c.post("/clients/inscription", json=inscription()).json()
    autre = inscription(gabarit="pharma")
    autre["contact"]["email"] = "j.doe@autre-societe.fr"
    b = c.post("/clients/inscription", json=autre).json()

    h, profil = entete(c, "C.Martin@orvane-sante.fr", "Chaine-2026-sure")      # casse de l'adresse ignorée
    assert profil["role"] == "client" and profil["topology_ref"] == a["topology_ref"] and profil["societe"] == "Orvane Santé"
    assert c.get("/graph/state", headers=h).status_code == 200
    assert c.get("/auth/moi", headers=h).json()["client_id"] == a["client_id"]
    assert c.get(f"/clients/{a['client_id']}/export", headers=h).status_code == 200
    assert c.get(f"/clients/{b['client_id']}/export", headers=h).status_code == 403
    assert c.delete(f"/clients/{b['client_id']}", headers=h).status_code == 403
    # périmètre : sa chaîne et les démonstrations, jamais celle d'un autre client
    refs = {t["ref"] for t in c.get("/topologies", headers=h).json()}
    assert a["topology_ref"] in refs and b["topology_ref"] not in refs
    ids = {s["id"] for s in c.get("/scenarios", headers=h).json()}
    assert a["scenario_id"] in ids and b["scenario_id"] not in ids
    assert c.post("/pipeline/run", headers=h, json={"mode": "live", "topology": b["topology_ref"]}).status_code == 403
    assert c.post("/pipeline/run", headers=h, json={"mode": "replay", "scenario": b["scenario_id"]}).status_code == 403
    assert c.get("/database/tables", headers=h).status_code == 403


def test_compte_equipe_et_mauvais_mots_de_passe(app):
    c, data = app
    auth.creer_compte_equipe("Equipe@aegis.fr", "Équipe projet", "Demo-Aegis-2027", data)
    assert "Demo-Aegis-2027" not in (data / "clients" / "comptes_equipe.json").read_text(encoding="utf-8")
    h, profil = entete(c, "equipe@aegis.fr", "Demo-Aegis-2027")
    assert profil["role"] == "equipe" and c.get("/topologies", headers=h).status_code == 200
    with pytest.raises(ValueError):
        auth.creer_compte_equipe("x@aegis.fr", "X", "court", data)
    for _ in range(auth.ESSAIS_MAX):
        assert c.post("/auth/connexion", json={"email": "equipe@aegis.fr", "mot_de_passe": "mauvais"}).status_code == 401
    r = c.post("/auth/connexion", json={"email": "equipe@aegis.fr", "mot_de_passe": "Demo-Aegis-2027"})
    assert r.status_code == 401 and "tentatives" in r.json()["detail"]          # blocage temporaire
    assert c.post("/auth/connexion", json={"email": "inconnu@x.fr", "mot_de_passe": "mauvais"}).json()["detail"] == \
        "adresse e-mail ou mot de passe incorrect"


def test_jeton_expire_ou_modifie(app, monkeypatch):
    _, data = app
    jeton = auth.creer_jeton({"role": "equipe"}, data)
    assert auth.lire_jeton(jeton, data)["role"] == "equipe"
    assert auth.lire_jeton(jeton[:-2] + "xx", data) is None
    monkeypatch.setattr(auth.time, "time", lambda: 10 ** 11)
    assert auth.lire_jeton(jeton, data) is None


def test_acces_developpement_seulement_avec_aegis_dev(app, monkeypatch):
    c, _ = app
    monkeypatch.delenv("AEGIS_DEV", raising=False)
    assert c.post("/auth/dev").status_code == 404
    monkeypatch.setenv("AEGIS_DEV", "1")
    r = c.post("/auth/dev")
    assert r.status_code == 200 and r.json()["profil"]["role"] == "equipe"
    assert c.get("/database/tables", headers={"Authorization": f"Bearer {r.json()['jeton']}"}).status_code != 401
