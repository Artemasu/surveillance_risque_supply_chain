"""Génère les scénarios de replay livrés avec le projet (FICTIFS, déterministes).

    python scripts/build_scenario.py            # les deux scénarios
    python scripts/build_scenario.py pharma     # un seul

  crisis_asia_semiconductors.json   électronique : typhon à Taïwan, grève à Rotterdam, flambée du fret (7 jours)
  crisis_pharma_api.json            pharmacie : contrôle des exportations, inondations à Hyderabad, cyberattaque
                                    au port d'Anvers (6 jours), sur la topologie data/topologies/pharma_helvia.yaml

Les articles sont rédigés pour la démonstration : ce ne sont pas de vrais articles. Les séries météo et
finance sont fabriquées (graine fixe). Le préfixe `replay:` et le domaine replay.local les rendent
reconnaissables partout dans la chaîne.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_sector_config import build_topology, topology_yaml  # noqa: E402
from scripts.scenario_tools import build_finance, build_media, build_weather, day_map  # noqa: E402
from src.graph.ontology_engine import OntologyEngine  # noqa: E402

# ============================================================================ scénario 1 : électronique
ASIA_ARTICLES = [
    (1, "06:30", "English", "Typhoon Meilin strengthens over the Philippine Sea, forecasters warn southern Taiwan",
     "Forecasters upgraded Typhoon Meilin to a severe storm on Monday. The typhoon is expected to approach Taiwan by "
     "Wednesday. Shipping lines say they are reviewing their schedules."),
    (2, "08:00", "English", "Port of Kaohsiung to suspend vessel operations ahead of Typhoon Meilin",
     "Kaohsiung, 15 September. The Port of Kaohsiung announced a port closure from Tuesday evening as Typhoon Meilin "
     "approaches. Container ship departures are cancelled and carriers warn of port congestion once operations resume."),
    (2, "11:20", "French", "Typhon Meilin : fermeture du port de Kaohsiung, les navires déroutés",
     "Le port de Kaohsiung ferme ses terminaux à partir de mardi soir à l'approche du typhon Meilin. "
     "Plusieurs porte-conteneurs sont déroutés et les armateurs annoncent des retards."),
    (3, "05:45", "English", "Typhoon Meilin makes landfall near Kaohsiung, flooding industrial zones",
     "Typhoon Meilin made landfall on Wednesday near Kaohsiung with violent gusts and torrential rain. Severe floods "
     "submerged industrial parks across southern Taiwan and factories suspended operations."),
    (3, "09:10", "English", "Formoz Power Semi halts production at Tainan fab after typhoon flooding",
     "Tainan, 16 September. Chipmaker Formoz Power Semi halted production at its Tainan fab after flood water from "
     "Typhoon Meilin reached the site. The company could not say when output would resume."),
    (3, "12:30", "English", "Typhoon flooding: Formoz Power Semi halts production at its Tainan chip fab",
     "Formoz Power Semi has stopped its production lines in Tainan because of typhoon flooding, the company said."),
    (4, "07:15", "English", "Kaohsiung port congestion builds as terminals reopen slowly after typhoon",
     "Kaohsiung, 17 September. Port congestion is building at the Port of Kaohsiung, where damaged cranes keep "
     "several berths closed. Dozens of container ship calls are delayed and cargo is piling up on the quays."),
    (4, "10:00", "English", "Novalys unveils refreshed E-Trail electric SUV at motor show",
     "The carmaker presented a new version of its electric SUV with a longer range and a redesigned interior."),
    (4, "15:40", "English", "Rotterdam dockworkers union calls 72-hour strike from Friday over automation plan",
     "Rotterdam, 17 September. Dockworkers at the Port of Rotterdam voted for a 72-hour strike starting on Friday "
     "after talks over terminal automation failed. Unions expect container handling to stop."),
    (5, "06:50", "English", "Strike halts container handling at Port of Rotterdam terminals",
     "Rotterdam, 18 September. Dockworkers began a 72-hour strike on Friday at the Port of Rotterdam. Port workers "
     "walked off the job at the main container terminals and cargo handling has stopped."),
    (5, "09:30", "French", "Grève au port de Rotterdam : les terminaux à l'arrêt",
     "Les dockers du port de Rotterdam ont entamé vendredi une grève de 72 heures. La manutention des conteneurs est "
     "à l'arrêt et les chargeurs redoutent des retards de livraison."),
    (6, "08:20", "English", "Rhein Power Modules warns of power-chip shortage, cuts output at Stuttgart plant",
     "Stuttgart, 19 September. Rhein Power Modules said a chip shortage forces it to cut output at its Stuttgart "
     "plant. Deliveries from Formoz Power Semi have stopped since the typhoon and stocks are running low."),
    (7, "07:00", "English", "Chip shortage: Novalys Valenciennes halts production of the E-City line for a week",
     "Valenciennes, 20 September. The Novalys Valenciennes plant halts production of its E-City line for one week "
     "because of a shortage of power modules. The carmaker blames missing components from its supplier."),
    (7, "09:45", "French", "Pénurie de puces : l'usine Novalys Valenciennes à l'arrêt pendant une semaine",
     "Faute de calculateurs, l'usine Novalys Valenciennes annonce un arrêt de production d'une semaine sur la ligne "
     "E-City. La pénurie de composants touche toute la filière."),
]

# (nœud, jour d'émission, jour concerné) -> vent moyen, rafales (km/h), pluie (mm)
ASIA = {
    "id": "crisis_asia_semiconductors", "prefix": "crisis_asia", "seed": 20260914, "topology": None,
    "start": date(2026, 9, 14), "days": 7,
    "title": "Crise en cascade : typhon à Taïwan, grève à Rotterdam, flambée du fret",
    "articles": ASIA_ARTICLES,
    "weather": {
        ("port_kaohsiung", 1, 3): (85, 120, 150), ("port_kaohsiung", 2, 3): (120, 175, 280),
        ("port_kaohsiung", 2, 2): (50, 70, 45),   ("port_kaohsiung", 3, 3): (130, 185, 320),
        ("port_kaohsiung", 4, 4): (60, 95, 110),  ("port_kaohsiung", 5, 5): (30, 45, 20),
        ("sup_chip_tw", 2, 3): (90, 130, 220),    ("sup_chip_tw", 3, 3): (105, 150, 290),
        ("sup_chip_tw", 4, 4): (45, 70, 90),
        ("port_keelung", 3, 3): (60, 95, 70),     ("sup_wafer_tw", 3, 3): (55, 85, 55),
    },
    # variations quotidiennes (%) pendant le scénario ; les autres instruments ne font que du bruit
    "finance": {"FRET_ASIE_EUROPE": [0.5, 2.0, 5.0, 7.0, 9.0, 8.0, 5.0],
                "PUCES_PUISSANCE":  [0.0, 0.3, 1.0, 3.0, 6.0, 6.0, 4.0]},
    "storyline": {
        "1": "Signal faible : un typhon se renforce, la prévision annonce des rafales à Kaohsiung dans 2 jours.",
        "2": "Le port de Kaohsiung annonce sa fermeture ; la prévision s'aggrave.",
        "3": "Le typhon touche terre : port fermé, usine de puces de Tainan inondée.",
        "4": "Congestion à Kaohsiung ; préavis de grève à Rotterdam ; le fret commence à monter.",
        "5": "Grève à Rotterdam : les deux bouts de la route des puces sont bloqués ; le fret s'envole.",
        "6": "Premier client touché : l'usine de calculateurs de Stuttgart réduit sa production.",
        "7": "L'usine d'assemblage de Valenciennes s'arrête une semaine."},
}

# ============================================================================ scénario 2 : pharmacie
PHARMA_TOPOLOGY = "topologies/pharma_helvia.yaml"       # générée par generate_sector_config (gabarit « pharma »)
PHARMA = {
    "id": "crisis_pharma_api", "prefix": "crisis_pharma", "seed": 20260706, "topology": PHARMA_TOPOLOGY,
    "start": date(2026, 7, 6), "days": 6,
    "title": "Pharmacie : contrôle des exportations, inondations à Hyderabad, cyberattaque à Anvers",
    "articles": [
        (1, "07:10", "English", "China tightens export controls on antibiotic intermediates, Jiangnan BioChem needs licences",
         "Beijing, 6 July. China's Ministry of Commerce announced new export controls on key antibiotic intermediates. "
         "Exporters such as Jiangnan BioChem will need a licence for each shipment, an export restriction that could "
         "delay deliveries to European drug makers."),
        (2, "06:40", "English", "Monsoon: severe floods feared in Hyderabad industrial areas within two days",
         "Hyderabad, 7 July. Forecasters expect torrential monsoon rain over Hyderabad from Wednesday. Authorities warn "
         "of a flood risk in the industrial areas where several pharmaceutical plants operate."),
        (3, "08:30", "English", "Deccan Actives halts production at Hyderabad plant after severe floods",
         "Hyderabad, 8 July. Severe floods submerged the Hyderabad pharma cluster on Wednesday. Deccan Actives halted "
         "production of antibiotic ingredients at its plant and could not say when output would resume."),
        (3, "11:15", "English", "Severe floods: Deccan Actives halts production at its Hyderabad plant",
         "Deccan Actives has stopped its production lines in Hyderabad because of the floods, the company said."),
        (4, "05:50", "English", "Ransomware attack forces Port of Antwerp terminal operator to shut down IT systems",
         "Antwerp, 9 July. A ransomware attack hit a container terminal operator at the Port of Antwerp overnight. "
         "The cyberattack forced it to shut down its IT systems and cargo release is suspended."),
        (4, "09:20", "French", "Cyberattaque au port d'Anvers : un rançongiciel paralyse des terminaux à conteneurs",
         "Une cyberattaque par rançongiciel touche depuis la nuit un opérateur de terminaux du port d'Anvers. "
         "Les systèmes informatiques sont coupés et la sortie des conteneurs est suspendue."),
        (5, "10:00", "English", "Helvia Pharma appoints new chief financial officer",
         "The drug maker named a new chief financial officer, who will take up the post in September."),
        (6, "07:30", "English", "Helvia Tours plant warns of antibiotic ingredient shortage, cuts output of injectables",
         "Tours, 11 July. The Helvia Tours plant cuts output of its injectable antibiotic because of a shortage of "
         "active ingredient. Deliveries from Deccan Actives have stopped since the floods and stocks are running low."),
        (6, "10:10", "French", "Pénurie de principe actif : l'usine Helvia Tours réduit sa production d'antibiotiques",
         "Faute de principe actif, l'usine Helvia Tours annonce une baisse de production de son antibiotique injectable. "
         "La pénurie de composants pourrait durer plusieurs semaines."),
    ],
    "weather": {
        ("sup_api_in", 1, 3): (35, 55, 160), ("sup_api_in", 2, 3): (45, 70, 240),
        ("sup_api_in", 3, 3): (50, 80, 290), ("sup_api_in", 4, 4): (30, 50, 110),
        ("port_nhava_sheva", 3, 3): (40, 65, 75),
    },
    "finance": {"API_ANTIBIOTIQUES": [0.0, 0.5, 3.0, 5.0, 6.0, 4.0],
                "FRET_INDE_EUROPE":  [0.0, 0.0, 1.0, 4.0, 6.0, 5.0]},
    "storyline": {
        "1": "Premier signal : la Chine soumet à licence l'exportation d'intermédiaires ; forte pluie prévue à Hyderabad.",
        "2": "La presse annonce un risque d'inondation à Hyderabad ; la prévision s'aggrave.",
        "3": "Inondations : le fournisseur indien de principe actif arrête sa production.",
        "4": "Cyberattaque au port d'Anvers : la route d'arrivée du principe actif indien est bloquée à son tour.",
        "5": "Le prix des principes actifs et le fret Inde-Europe décrochent.",
        "6": "L'usine de Tours réduit sa production d'antibiotique injectable."},
}

SPECS = {"asia": ASIA, "pharma": PHARMA}


def ensure_pharma_topology() -> None:
    """La topologie pharma est produite par le gabarit du générateur, pour l'entreprise fictive Helvia Pharma."""
    path = ROOT / "data" / PHARMA_TOPOLOGY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(topology_yaml(build_topology("pharma", "Helvia Pharma")), encoding="utf-8")


def build(spec: dict = ASIA) -> dict:
    rng = random.Random(spec["seed"])
    engine = OntologyEngine.from_yaml(ROOT / "data" / (spec["topology"] or "topology.yaml"))
    days = day_map(spec["start"], spec["days"])
    meta = {"id": spec["id"], "title": spec["title"], "fictional": True,
            "notice": "Scénario FICTIF écrit pour la démonstration. Ni les articles, ni les mesures, ni les "
                      "entreprises ne sont réels.",
            "start_date": days[1], "days": spec["days"], "storyline": spec["storyline"]}
    if spec["topology"]:
        meta["topology"] = spec["topology"]
    return {"meta": meta, "media": build_media(spec["prefix"], days, spec["articles"]),
            "weather": build_weather(engine, days, rng, spec["weather"]),
            "finance": build_finance(engine, spec["start"], spec["days"], rng, spec["finance"])}


if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SPECS)
    unknown = [w for w in wanted if w not in SPECS]
    if unknown:
        sys.exit(f"scénario inconnu : {unknown} (attendu : {', '.join(SPECS)})")
    for key in wanted:
        if key == "pharma":
            ensure_pharma_topology()
        spec = SPECS[key]
        out = ROOT / "data" / "replay_scenarios" / f"{spec['id']}.json"
        out.write_text(json.dumps(build(spec), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"écrit : {out} ({out.stat().st_size} octets)")
