"""Registres publics du volet Finance (familles 3 à 5) — repris de `finance_collecte.py`.

    federal_register()  textes officiels US (Entity List, droits de douane) : publication et entrée en vigueur
    REGLES_UE           règles UE suivies à la main (EUR-Lex n'a pas d'API simple), sourcées
    csl(), sanctions_ue() listes de sanctions US (Consolidated Screening List) et UE (liste consolidée)
    gleif_*()           identifiant LEI et maisons mères déclarées
    bodacc()            procédures collectives des entreprises françaises
"""
from __future__ import annotations

import io
import json
import logging
import re
import xml.etree.ElementTree as ET

import pandas as pd

from src.connectors.http_cache import SourceError, fetch_bytes
from src.connectors.markets import NS, manual_dir

log = logging.getLogger("supplychain.connectors")

URL_FEDREG = "https://www.federalregister.gov/api/v1/documents.json"
URL_SANCTIONS_UE = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
JETON_SANCTIONS_UE = "dG9rZW4tMjAxNw"   # jeton public de téléchargement publié par la Commission (sans inscription)
URL_CSL = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv"
URL_GLEIF = "https://api.gleif.org/api/v1"
URL_BODACC = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

# Fournisseurs réels du cas d'étude. ticker = action cotée ; siren = entreprise française (BODACC).
FOURNISSEURS = pd.DataFrame([
    ("wolfspeed", "Wolfspeed", "Wolfspeed, Inc.", "WOLF", "US", None, "Carbure de silicium (puces de puissance)"),
    ("wingtech", "Wingtech (maison mère de Nexperia)", "Wingtech Technology Co., Ltd.", "600745.SS", "CN", None, "Puces (via Nexperia)"),
    ("nexperia", "Nexperia", "Nexperia B.V.", None, "NL", None, "Puces discrètes et logiques"),
    ("infineon", "Infineon", "Infineon Technologies AG", "IFX.DE", "DE", None, "Semi-conducteurs"),
    ("stmicro", "STMicroelectronics", "STMicroelectronics N.V.", "STMPA.PA", "FR", None, "Semi-conducteurs"),
    ("valeo", "Valeo", "Valeo SE", "FR.PA", "FR", "552030967", "Équipements automobiles"),
    ("forvia", "Forvia", "Forvia SE", "FRVIA.PA", "FR", "542005376", "Équipements automobiles"),
    ("nyrstar", "Nyrstar", "Nyrstar NV", None, "BE", None, "Zinc"),
], columns=["cle", "nom", "nom_legal", "ticker", "pays", "siren", "produit"])

REGLES_UE = pd.DataFrame([
    ("2023-05-16", "2026-01-01", "UE", "CBAM : taxe carbone aux frontières, phase définitive",
     "Surcoût sur acier, aluminium, ciment, engrais, électricité, hydrogène importés",
     "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en"),
    ("2024-07-04", "2024-07-05", "UE", "Droits provisoires sur les voitures électriques importées de Chine",
     "Véhicules et sous-ensembles chinois plus chers",
     "https://policy.trade.ec.europa.eu/news/commission-imposes-provisional-countervailing-duties-imports-battery-electric-vehicles-china-while-discussions-china-continue-2024-07-04_en"),
    ("2022-02-25", "2022-02-25", "UE", "Sanctions contre la Russie (premiers paquets après l'invasion)",
     "Ruptures d'approvisionnement en provenance de Russie",
     "https://www.consilium.europa.eu/fr/policies/sanctions-against-russia/"),
], columns=["publication", "entree_en_vigueur", "zone", "regle", "effet", "url"])

# Liens de propriété connus mais absents de GLEIF
PROPRIETE_MANUELLE = pd.DataFrame([
    ("Nexperia B.V.", "Wingtech Technology Co., Ltd.", "ultime", "Rachat de Nexperia par Wingtech (2019)"),
], columns=["enfant", "parent", "type", "source"])

SUFFIXES = r"\b(co|ltd|limited|inc|corp|corporation|company|b ?v|n ?v|ag|se|sa|s ?a|gmbh|plc|llc|holding|holdings|group|ab|spa|nv)\b"


def normaliser(nom: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(nom or "").lower())
    s = re.sub(SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fournisseur(cle: str) -> dict:
    rows = FOURNISSEURS[FOURNISSEURS["cle"] == cle]
    if rows.empty:
        raise KeyError(f"fournisseur inconnu : {cle}")
    return {k: (None if pd.isna(v) else v) for k, v in rows.iloc[0].to_dict().items()}


def supplier_tickers() -> dict[str, str]:
    """{"bourse_<clé>": ticker} pour les fournisseurs cotés."""
    return {f"bourse_{r.cle}": r.ticker for r in FOURNISSEURS.itertuples() if isinstance(r.ticker, str)}


# --------------------------------------------------------------------------- règles
def federal_register(terme: str, agence: str | None = None, types: tuple = ("RULE",),
                     debut: str = "2018-01-01", max_pages: int = 5) -> pd.DataFrame:
    params = {"conditions[term]": terme, "conditions[publication_date][gte]": debut, "per_page": 100, "order": "oldest",
              "fields[]": ["title", "publication_date", "effective_on", "html_url", "document_number", "type", "agencies"]}
    if agence:
        params["conditions[agencies][]"] = agence
    if types:
        params["conditions[type][]"] = list(types)
    lignes, page = [], 1
    while page <= max_pages:
        params["page"] = page
        try:
            data = json.loads(fetch_bytes(URL_FEDREG, params, namespace=NS, ext="json", ttl_days=1))
        except ValueError as e:
            raise SourceError("réponse du Federal Register illisible") from e
        for d in data.get("results", []):
            lignes.append({"publication": d.get("publication_date"), "entree_en_vigueur": d.get("effective_on"),
                           "titre": d.get("title"), "type": d.get("type"), "url": d.get("html_url"),
                           "document": d.get("document_number"),
                           "agences": ", ".join(a.get("name", "") for a in (d.get("agencies") or []))})
        if not data.get("next_page_url"):
            break
        page += 1
    df = pd.DataFrame(lignes, columns=["publication", "entree_en_vigueur", "titre", "type", "url", "document", "agences"])
    for c in ("publication", "entree_en_vigueur"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["terme"] = terme
    df["delai_jours"] = (df["entree_en_vigueur"] - df["publication"]).dt.days
    return df


def regles(debut: str = "2018-01-01") -> pd.DataFrame:
    """Règles US (Entity List, droits de douane) et UE au même format : zone, publication, entrée en vigueur, titre."""
    morceaux = []
    for terme, agence in (("entity list", "industry-and-security-bureau"), ("tariff", None)):
        try:
            df = federal_register(terme, agence, debut=debut)
            morceaux.append(df.assign(zone="US", famille="Entity List" if agence else "Droits de douane"))
        except SourceError as e:
            log.warning("Federal Register indisponible : %s", e)
    ue = REGLES_UE.rename(columns={"regle": "titre"}).assign(
        publication=lambda d: pd.to_datetime(d["publication"]), entree_en_vigueur=lambda d: pd.to_datetime(d["entree_en_vigueur"]),
        type="Règle UE (suivi manuel)", document=None, agences="Union européenne", terme=None, famille="UE")
    ue["delai_jours"] = (ue["entree_en_vigueur"] - ue["publication"]).dt.days
    morceaux.append(ue)
    return pd.concat(morceaux, ignore_index=True)


# --------------------------------------------------------------------------- sanctions
def csl() -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(fetch_bytes(URL_CSL, namespace=NS, ext="csv", ttl_days=1)), dtype=str).fillna("")
    df.columns = [c.strip().lower() for c in df.columns]
    if "name" not in df:
        raise SourceError(f"format CSL inattendu : {list(df.columns)[:8]}")
    if "type" in df:
        df = df[df["type"].str.lower() != "individual"]
    vide = pd.Series("", index=df.index)
    return pd.DataFrame({"nom": df["name"], "autres_noms": df.get("alt_names", vide), "liste": "US : " + df.get("source", vide),
                         "programme": df.get("programs", vide),
                         "date_inscription": pd.to_datetime(df.get("start_date", vide), errors="coerce"),
                         "source_id": "csl:" + df.get("_id", df.get("entity_number", vide))}).reset_index(drop=True)


def sanctions_ue() -> pd.DataFrame:
    manuel = manual_dir() / "sanctions_ue.xml"
    try:
        contenu = fetch_bytes(URL_SANCTIONS_UE, {"token": JETON_SANCTIONS_UE}, namespace=NS, ext="xml", ttl_days=1)
    except SourceError:
        if not manuel.exists():
            raise
        contenu = manuel.read_bytes()
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as e:
        raise SourceError("sanctions UE : fichier XML illisible") from e
    local = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731
    lignes = []
    for ent in racine.iter():
        if local(ent) != "sanctionEntity":
            continue
        type_ = next((c.get("code") for c in ent if local(c) == "subjectType"), "")
        if type_ and type_.lower() == "person":
            continue
        noms = [c.get("wholeName") for c in ent if local(c) == "nameAlias" and c.get("wholeName")]
        reg = next((c for c in ent if local(c) == "regulation"), None)
        if noms:
            lignes.append({"nom": noms[0], "autres_noms": "; ".join(noms[1:]), "liste": "UE : sanctions financières",
                           "programme": reg.get("programme", "") if reg is not None else "",
                           "date_inscription": pd.to_datetime(reg.get("publicationDate") if reg is not None else None, errors="coerce"),
                           "source_id": f"ue_fsf:{ent.get('logicalId', '')}"})
    if not lignes:
        raise SourceError("sanctions UE : aucune entité trouvée dans le fichier")
    return pd.DataFrame(lignes)


def listes_sanctions() -> tuple[pd.DataFrame, dict]:
    """CSL américaine + sanctions UE ; une liste indisponible est omise et signalée dans l'état."""
    morceaux, etat = [], {}
    for nom, f in (("csl_us", csl), ("sanctions_ue", sanctions_ue)):
        try:
            df = f()
            morceaux.append(df)
            etat[nom] = {"status": "ok", "entites": len(df)}
        except SourceError as e:
            etat[nom] = {"status": "failed", "detail": str(e)[:160]}
    vide = pd.DataFrame(columns=["nom", "autres_noms", "liste", "programme", "date_inscription", "source_id"])
    return (pd.concat(morceaux, ignore_index=True) if morceaux else vide), etat


def correspondances(nom: str, listes: pd.DataFrame, seuil_score: int = 92) -> pd.DataFrame:
    """Entrées des listes dont un nom ressemble fortement à `nom` (token_sort_ratio, strict)."""
    from rapidfuzz import fuzz
    cible = normaliser(nom)
    if len(cible) < 4 or listes.empty:
        return listes.iloc[0:0].assign(score=[])

    def score(ligne):
        noms = [ligne["nom"]] + [n for n in str(ligne["autres_noms"]).split(";") if n.strip()]
        return max(fuzz.token_sort_ratio(cible, normaliser(n)) for n in noms)
    sc = listes.apply(score, axis=1)
    return listes[sc >= seuil_score].assign(score=sc[sc >= seuil_score])


# --------------------------------------------------------------------------- propriété
def gleif_lei(nom_legal: str) -> dict | None:
    """Meilleure fiche GLEIF ; None si aucune ne correspond ; SourceError si GLEIF est injoignable."""
    from rapidfuzz import fuzz
    res, reached = None, False
    for filtre in ("filter[fulltext]", "filter[entity.legalName]"):
        try:
            res = json.loads(fetch_bytes(f"{URL_GLEIF}/lei-records", {filtre: nom_legal, "page[size]": 10},
                                         namespace=NS, ext="json", ttl_days=30))
            reached = True
        except (SourceError, ValueError):
            res = None
        if res and res.get("data"):
            break
    if not reached:
        raise SourceError("GLEIF injoignable")
    if not res or not res.get("data"):
        return None
    cible = normaliser(nom_legal)
    meilleur = max(res["data"], key=lambda r: (fuzz.token_sort_ratio(cible, normaliser(r["attributes"]["entity"]["legalName"]["name"])),
                                               r["attributes"]["entity"].get("status") == "ACTIVE"))
    trouve = meilleur["attributes"]["entity"]["legalName"]["name"]
    return meilleur if fuzz.token_sort_ratio(cible, normaliser(trouve)) >= 85 else None


def gleif_parents(lei: str) -> list[dict]:
    parents = []
    for kind in ("direct", "ultimate"):
        try:
            res = json.loads(fetch_bytes(f"{URL_GLEIF}/lei-records/{lei}/{kind}-parent", None, namespace=NS, ext="json", ttl_days=30))
        except (SourceError, ValueError):
            continue
        d = res.get("data") if res else None
        if d and d["attributes"]["lei"] != lei:
            parents.append({"type": "directe" if kind == "direct" else "ultime", "lei": d["attributes"]["lei"],
                            "nom": d["attributes"]["entity"]["legalName"]["name"]})
    return parents


def proprietaires(nom_legal: str) -> tuple[list[dict], str | None, bool]:
    """Maisons mères (GLEIF puis liens manuels sourcés), LEI de l'entité, et si GLEIF a répondu."""
    out, lei, reached = [], None, True
    try:
        fiche = gleif_lei(nom_legal)
    except SourceError:
        fiche, reached = None, False
    if fiche:
        lei = fiche["attributes"]["lei"]
        out = gleif_parents(lei)
    for m in PROPRIETE_MANUELLE[PROPRIETE_MANUELLE["enfant"].map(normaliser) == normaliser(nom_legal)].itertuples():
        if not any(normaliser(p["nom"]) == normaliser(m.parent) for p in out):
            out.append({"type": m.type, "lei": None, "nom": m.parent, "source": m.source})
    return out, lei, reached


# --------------------------------------------------------------------------- procédures collectives
def bodacc(siren: str, debut: str = "2015-01-01") -> pd.DataFrame:
    siren = re.sub(r"\D", "", str(siren))
    params = {"where": f"familleavis='collective' AND '{siren}' AND dateparution>=date'{debut}'",
              "order_by": "dateparution", "limit": 100}
    try:
        data = json.loads(fetch_bytes(URL_BODACC, params, namespace=NS, ext="json", ttl_days=1))
    except ValueError as e:
        raise SourceError("réponse BODACC illisible") from e
    if "results" not in data:
        raise SourceError(f"BODACC : réponse inattendue ({str(data)[:150]})")
    lignes = [{"date": r.get("dateparution"), "type": r.get("familleavis_lib"), "entreprise": r.get("commercant"),
               "tribunal": r.get("tribunal"), "detail": str(r.get("jugement") or "")[:200],
               "source_id": f"bodacc:{r.get('id', '')}"} for r in data["results"]]
    df = pd.DataFrame(lignes, columns=["date", "type", "entreprise", "tribunal", "detail", "source_id"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df
