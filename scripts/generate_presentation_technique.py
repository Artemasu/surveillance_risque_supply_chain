#!/usr/bin/env python3
"""Génère architecture_technique_complete.pptx : dossier technique d'A.E.G.I.S. en 25 slides.

Usage (depuis la racine du dépôt) :
    pip install python-pptx            # Pillow est installé avec python-pptx
    python scripts/generate_presentation_technique.py

Le corps des slides décrit le code réellement implémenté. Les briques prévues mais absentes du code (BERT/XLM-R,
zero-shot NLI, Globe.gl, agent ontologie LLM...) sont isolées dans des encadrés « Architecture cible / perspectives ».
Les notes du présentateur de chaque slide contiennent un cours complet pour réviser le projet.

Les chiffres d'exemple (indice 6,0 -> 40,6, chemin Kaohsiung -> Rotterdam -> Stuttgart, simulation 6,0 -> 20,9)
ont été obtenus en exécutant le moteur sur le scénario crisis_asia_semiconductors (20/11/2026).
"""
from __future__ import annotations

import io
import re
import textwrap
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "architecture_technique_complete.pptx"
SPRITES = ROOT / "frontend" / "public" / "copilot"
FIGURES = ROOT / "docs" / "figures"

# --------------------------------------------------------------------------- charte (reprise du deck non technique)
NIGHT = "0B1F3A"
NAVY = "13294B"
NAVY2 = "2A4A72"
CYAN = "00B4D8"
CYAN_D = "0284A8"
ICE = "E6F7FB"
WHITE = "FFFFFF"
TEXT = "334155"
MUTED = "64748B"
MUTED_DARK = "8FA3BF"
LINE = "D5DEE8"
SOFT = "F2F5F9"
CODE_BG = "0F172A"
CODE_FG = "E2E8F0"
CODE_NOTE = "FBBF24"
# domaines (mêmes teintes que le front-end : médias jaune, météo vert, finance bleu)
MEDIA, MEDIA_BG = "B7791F", "FDF3D7"
WEATHER, WEATHER_BG = "2F855A", "E3F4EA"
FIN, FIN_BG = "2B6CB0", "E2EEF9"
# niveaux de risque
OK = "5FA777"
WATCH = "F2C14E"
ALERT = "F08A4B"
CRIT = "D64545"
# encadrés « architecture cible »
PERSP, PERSP_BG = "6D4BB8", "F3EEFC"

FONT = "Calibri"
MONO = "Courier New"
MATH = "Cambria"
W, H = 13.333, 7.5
TOTAL = 25

BLOCS = {
    1: "Architecture & flux de données",
    2: "Stack technique",
    3: "Ingestion, nettoyage & NLP",
    4: "Données, ontologie & graphe",
    5: "Agents, risque & orchestration",
    6: "Frontend & mécanismes transverses",
}

prs = Presentation()
prs.slide_width = Inches(W)
prs.slide_height = Inches(H)
BLANK = prs.slide_layouts[6]
_counter = {"n": 0}


# =========================================================================== utilitaires de dessin
def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


TOKEN = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def _runs(p, text: str, size: float, color: str, font: str, bold: bool, italic: bool, code_color: str) -> None:
    """Texte avec un balisage minimal : **gras** et `code` (police à chasse fixe)."""
    for part in TOKEN.split(text):
        if not part:
            continue
        r = p.add_run()
        f_name, f_bold, f_color, f_size = font, bold, color, size
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            part, f_bold = part[2:-2], True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            part, f_name, f_color, f_size = part[1:-1], MONO, code_color, size - 1
        r.text = part
        r.font.size = Pt(f_size)
        r.font.bold = f_bold
        r.font.italic = italic
        r.font.name = f_name
        r.font.color.rgb = rgb(f_color)


def _bullet(p, level: int, color: str, char: str = "•") -> None:
    pPr = p._p.get_or_add_pPr()
    step = Inches(0.2)
    pPr.set("marL", str(int(step * (level + 1))))
    pPr.set("indent", str(-int(step)))
    buClr = etree.SubElement(pPr, qn("a:buClr"))
    etree.SubElement(buClr, qn("a:srgbClr")).set("val", color)
    buFont = etree.SubElement(pPr, qn("a:buFont"))
    buFont.set("typeface", "Arial")
    etree.SubElement(pPr, qn("a:buChar")).set("char", char)


def write(tf, paras, size=14, color=TEXT, font=FONT, bold=False, italic=False, align=PP_ALIGN.LEFT,
          space_after=4, code_color=CYAN_D, bullet_color=CYAN_D, line_spacing=None) -> None:
    """Écrit une liste de paragraphes dans un cadre de texte.

    Chaque élément : une chaîne (« - » en tête = puce, « -- » = puce de niveau 2) ou un dict
    {t, s (taille), c (couleur), b (gras), i (italique), al (alignement), f (police), sa (espace après)}."""
    if isinstance(paras, str):
        paras = [paras]
    first = True
    for item in paras:
        spec = item if isinstance(item, dict) else {"t": item}
        text = spec["t"]
        level = None
        if text.startswith("-- "):
            level, text = 1, text[3:]
        elif text.startswith("- "):
            level, text = 0, text[2:]
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = spec.get("al", align)
        p.space_after = Pt(spec.get("sa", space_after))
        if line_spacing:
            p.line_spacing = line_spacing
        if level is not None:
            _bullet(p, level, bullet_color)
        _runs(p, text, spec.get("s", size), spec.get("c", color), spec.get("f", font), spec.get("b", bold),
              spec.get("i", italic), spec.get("cc", code_color))


def _frame(tf, margin=0.08, anchor=MSO_ANCHOR.TOP):
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(margin * 0.6)
    tf.vertical_anchor = anchor


def text(slide, x, y, w, h, paras, margin=0.04, anchor=MSO_ANCHOR.TOP, **kw):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    _frame(tb.text_frame, margin, anchor)
    write(tb.text_frame, paras, **kw)
    return tb


def _drop_style(shp) -> None:
    """Retire le style de thème (ombre portée, couleurs implicites) : tout est réglé explicitement."""
    style = shp._element.find(qn("p:style"))
    if style is not None:
        shp._element.remove(style)


def box(slide, x, y, w, h, fill=WHITE, line=LINE, paras=None, radius=0.08, dash=False, lw=1.0,
        anchor=MSO_ANCHOR.TOP, margin=0.12, shape=MSO_SHAPE.ROUNDED_RECTANGLE, **kw):
    shp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    _drop_style(shp)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        shp.adjustments[0] = min(0.5, radius / max(0.01, min(w, h)))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = rgb(line)
        shp.line.width = Pt(lw)
        if dash:
            shp.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    _frame(shp.text_frame, margin, anchor)
    if paras is not None:
        write(shp.text_frame, paras, **kw)
    return shp


def arrow(slide, x1, y1, x2, y2, color=MUTED, width=1.5, dash=False, head=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    _drop_style(c)
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(width)
    if dash:
        c.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    if head:
        ln = c.line._get_or_add_ln()
        tail = etree.SubElement(ln, qn("a:tailEnd"))
        tail.set("type", "triangle")
        tail.set("w", "med")
        tail.set("len", "med")
    return c


def num(slide, x, y, n, d=0.42, fill=CYAN_D, color=WHITE, size=14):
    return box(slide, x, y, d, d, fill=fill, line=None, paras=[{"t": str(n), "al": PP_ALIGN.CENTER}], size=size,
               color=color, bold=True, shape=MSO_SHAPE.OVAL, margin=0, anchor=MSO_ANCHOR.MIDDLE)


def code(slide, x, y, w, h, lines, size=11, title=None):
    """Bloc de code sombre. Un commentaire « # ... » en fin de ligne est affiché en ambre (annotation)."""
    shp = box(slide, x, y, w, h, fill=CODE_BG, line=None, margin=0.16, radius=0.1)
    tf = shp.text_frame
    first = True
    if title:
        p = tf.paragraphs[0]
        first = False
        p.alignment = PP_ALIGN.LEFT
        _runs(p, title, size - 1, MUTED_DARK, FONT, True, False, MUTED_DARK)
        p.space_after = Pt(4)
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(0)
        main, note = line, ""
        m = re.search(r"\s{2,}#\s?(.*)$", line)
        if m:
            main, note = line[:m.start()], m.group(1)
        if line.lstrip().startswith("#"):
            main, note = "", line.lstrip()[1:].strip()
        r = p.add_run()
        r.text = main if main else " "
        r.font.name, r.font.size = MONO, Pt(size)
        r.font.color.rgb = rgb(CODE_FG)
        if note:
            r2 = p.add_run()
            r2.text = ("   # " if main else "# ") + note
            r2.font.name, r2.font.size = MONO, Pt(size)
            r2.font.color.rgb = rgb(CODE_NOTE)
    return shp


def formula(slide, x, y, w, h, lines, size=16, fill=ICE, line=None, label=None):
    """Encadré de formules (police Cambria, italique)."""
    paras = []
    if label:
        paras.append({"t": label, "s": 12, "b": True, "c": CYAN_D, "f": FONT, "i": False, "sa": 6})
    for ln in lines:
        if isinstance(ln, dict):
            paras.append(ln)
        else:
            paras.append({"t": ln, "s": size, "f": MATH, "i": True, "c": NIGHT, "sa": 6})
    return box(slide, x, y, w, h, fill=fill, line=line, paras=paras, margin=0.16, anchor=MSO_ANCHOR.MIDDLE)


def perspective(slide, x, y, w, h, paras, size=12):
    shp = box(slide, x, y, w, h, fill=PERSP_BG, line=PERSP, dash=True, lw=1.25, margin=0.14)
    tf = shp.text_frame
    write(tf, [{"t": "ARCHITECTURE CIBLE / PERSPECTIVES (non implémenté)", "s": 11, "b": True, "c": PERSP, "sa": 3}]
          + paras, size=size, color=TEXT, bullet_color=PERSP, code_color=PERSP)
    return shp


def chip(slide, x, y, label, fill=ICE, color=CYAN_D, size=11, h=0.3, w=None):
    w = w or (0.13 + 0.082 * len(label) * size / 11)
    return box(slide, x, y, w, h, fill=fill, line=None, paras=[{"t": label, "al": PP_ALIGN.CENTER}], size=size,
               color=color, bold=True, margin=0.03, anchor=MSO_ANCHOR.MIDDLE, radius=h / 2)


def table(slide, x, y, col_w, rows, row_h=0.4, size=12, header_fill=NIGHT, header_color=WHITE, zebra=SOFT,
          first_col_bold=False, mono_cols=()):
    n_rows, n_cols = len(rows), len(col_w)
    gf = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y), Inches(sum(col_w)), Inches(row_h * n_rows))
    tbl = gf.table
    tblPr = tbl._tbl.tblPr
    for attr in ("bandRow", "firstRow"):
        tblPr.set(attr, "0")
    style = tblPr.find(qn("a:tableStyleId"))
    if style is not None:
        style.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"     # « No Style, No Grid » : aucun style imposé
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = Inches(cw)
    for i in range(n_rows):
        tbl.rows[i].height = Inches(row_h)
        for j in range(n_cols):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if i == 0:
                cell.fill.fore_color.rgb = rgb(header_fill)
            else:
                cell.fill.fore_color.rgb = rgb(zebra if i % 2 == 0 else WHITE)
            val = rows[i][j]
            tf = cell.text_frame
            tf.word_wrap = True
            if i == 0:
                write(tf, [{"t": val}], size=size, color=header_color, bold=True, space_after=0)
            else:
                f = MONO if j in mono_cols else FONT
                write(tf, [{"t": val, "f": f, "s": size - 1 if j in mono_cols else size}], size=size, color=TEXT,
                      bold=(first_col_bold and j == 0), space_after=0)
    return gf


def pixel_image(path: Path, scale: int = 6) -> io.BytesIO:
    """Agrandit un sprite pixel art au plus proche voisin : PowerPoint ne le lissera pas."""
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return buf


def notes(slide, body: str) -> None:
    slide.notes_slide.notes_text_frame.text = textwrap.dedent(body).strip()


def frame(title: str, bloc: int, files: str, note: str):
    """Slide de contenu : pastille de bloc, titre, pied de page « Fichiers », numéro, notes."""
    _counter["n"] += 1
    n = _counter["n"]
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(WHITE)
    chip(s, 0.5, 0.3, f"BLOC {bloc} · {BLOCS[bloc].upper()}", size=10.5)
    text(s, 0.5, 0.62, 12.33, 0.8, [{"t": title}], size=30, color=NIGHT, bold=True, margin=0)
    text(s, 0.5, 6.86, 11.4, 0.5, [{"t": "Fichiers : " + files}], size=10.5, color=MUTED, font=MONO, margin=0)
    text(s, 12.0, 6.86, 0.83, 0.3, [{"t": f"{n} / {TOTAL}", "al": PP_ALIGN.RIGHT}], size=10.5, color=MUTED, margin=0)
    notes(s, note)
    return s


# =========================================================================== slide 1 : titre
def slide_01():
    _counter["n"] += 1
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(NIGHT)
    text(s, 0.6, 0.6, 7, 0.4, "MASTER PROJECT INGE3 N°6 · DOSSIER TECHNIQUE", size=14, color=CYAN, bold=True)
    text(s, 0.6, 1.05, 7.2, 1.3, "A.E.G.I.S.", size=66, color=WHITE, bold=True)
    text(s, 0.6, 2.35, 7.2, 0.5, "Automated Early-warning & Graph Intelligence for Supply-chain", size=18,
         color=MUTED_DARK, italic=True)
    text(s, 0.6, 3.0, 6.9, 1.1, "Architecture technique complète : de la collecte d'actualités à l'interface",
         size=24, color=WHITE)
    stats = [("3", "agents de collecte"), ("30 / 40", "nœuds / liens du graphe"), ("9", "endpoints REST"),
             ("155", "tests pytest (verts)")]
    for k, (big, small) in enumerate(stats):
        x = 0.6 + k * 1.75
        text(s, x, 4.45, 1.7, 0.7, big, size=30, color=CYAN, bold=True)
        text(s, x, 5.1, 1.6, 0.6, small, size=12, color=MUTED_DARK)
    ranges = {1: "slides 2–5", 2: "slides 6–7", 3: "slides 8–13", 4: "slides 14–18", 5: "slides 19–21",
              6: "slides 22–25"}
    for k in range(1, 7):
        y = 0.75 + (k - 1) * 0.93
        box(s, 7.95, y, 4.88, 0.8, fill=NAVY, line=None, radius=0.1)
        num(s, 8.12, y + 0.19, k, fill=CYAN, color=NIGHT)
        text(s, 8.72, y + 0.1, 4.0, 0.36, BLOCS[k], size=15, color=WHITE, bold=True)
        text(s, 8.72, y + 0.43, 4.0, 0.3, ranges[k], size=11, color=MUTED_DARK)
    text(s, 0.6, 6.55, 12.0, 0.5,
         "Persona de démonstration : Claire, acheteuse chez Novalys (entreprise fictive). Fournisseurs et scénarios "
         "simulés ; ports et villes réels. Encadrés violets = architecture cible, non implémentée.",
         size=12, color=MUTED_DARK)
    notes(s, """
    OBJECTIF DE CE DOSSIER
    Ce deck est un support de révision : chaque slide isole une brique technique d'A.E.G.I.S. et cite les fichiers
    exacts du dépôt alerte-supply-chain. Le corps des slides décrit uniquement ce qui est réellement implémenté.
    Tout ce qui est prévu dans le sujet ou dans le PDF d'architecture mais absent du code (BERT/XLM-R, zero-shot NLI,
    Globe.gl, agent ontologie piloté par LLM, base de données) est rangé dans des encadrés violets « Architecture
    cible / perspectives ». En soutenance, c'est la distinction à tenir : ce que le prototype fait, et ce qui reste
    la cible.

    LE PROBLÈME MÉTIER
    Les chaînes d'approvisionnement sont mondiales et interdépendantes. Une grève dans un port, un typhon ou une
    sanction contre un fournisseur de rang 2 peut arrêter une usine en Europe, mais les signaux précurseurs sont
    noyés dans un flux massif et multilingue d'actualités. Les entreprises réagissent donc tard. A.E.G.I.S. est un
    outil d'aide à la décision pour les acheteurs et responsables risques de PME industrielles : il détecte les
    événements perturbateurs, les rattache à un graphe de fournisseurs (rangs 1 à 3), calcule un risque, le propage
    dans le réseau et émet des alertes priorisées et expliquées (article source, règle, chemin dans le graphe).

    LA PROMESSE TECHNIQUE EN UNE PHRASE
    Trois agents de collecte (médias, météo, finance) produisent des événements au même format JSON ; un moteur
    d'ontologie NetworkX les rattache aux nœuds du graphe, les corrèle, calcule un risque direct puis propagé ; une
    API FastAPI expose l'état, les alertes, la simulation what-if et un Copilot ; un front-end React affiche le tout.

    LES CHIFFRES DE LA PAGE DE TITRE
    - 3 agents : MediaAgent, WeatherAgent, FinanceAgent (src/agents).
    - 30 nœuds et 40 liens dans la topologie par défaut data/topology.yaml (33 liens actifs + 7 liens de secours).
    - 9 endpoints REST dans src/api/main.py.
    - 155 tests pytest : 136 fonctions de test, certaines paramétrées. Vérifié le 20/11/2026 : les 155 passent
      (exécution fichier par fichier, sans Internet ni Ollama, les réponses externes étant simulées).

    COMMENT LIRE LA SUITE
    Bloc 1 : le flux de bout en bout et les contrats de données. Bloc 2 : la stack et la justification des choix.
    Bloc 3 : collecte, nettoyage et NLP. Bloc 4 : persistance, ontologie et algorithmes du graphe. Bloc 5 : agents,
    alertes, Copilot. Bloc 6 : front-end, visualisation, mécanismes transverses et limites.

    QUESTION DE JURY PROBABLE
    « Pourquoi un moteur à règles et pas un modèle appris ? » Réponse : il n'existe pas de jeu étiqueté de crises
    supply chain pour entraîner un modèle de risque ; des règles d'experts explicites sont explicables, testables et
    calibrables ensuite par backtesting (Nexperia, ouragan Helene, grève des ports, terres rares). Toutes les
    constantes sont regroupées dans src/graph/ontology_engine.py pour pouvoir être justifiées une par une.
    """)


# =========================================================================== bloc 1
def slide_02():
    s = frame("Vue d'ensemble : du signal brut à l'alerte expliquée", 1,
              "README.md · src/service.py · src/api/main.py · src/graph/ontology_engine.py · src/agents/*.py",
              """
    LE FLUX DE BOUT EN BOUT
    Le schéma se lit de gauche à droite. À gauche, les sources : GDELT DOC 2.0 et 12 flux RSS (avec Google News RSS
    en repli), Open-Meteo, Yahoo Finance, et en mode replay un scénario JSON daté. Chaque source alimente un agent
    spécialisé. Les trois agents ne se parlent pas entre eux : ils produisent tous des objets NormalizedEvent,
    le contrat Pydantic défini dans src/schemas/events.py. Ce contrat est le point de découplage du système :
    on peut remplacer un agent (par exemple brancher une autre source météo) sans toucher au moteur.

    Le moteur d'ontologie (OntologyEngine, src/graph/ontology_engine.py) reçoit la liste d'événements et la topologie
    YAML de l'entreprise surveillée. Il enchaîne six étapes : déduplication sémantique des événements médias,
    rattachement aux nœuds, corrélation en signaux (même nœud, même famille d'aléa, moins de 3 jours), risque direct,
    propagation dans le graphe, puis production des alertes et de la simulation what-if.

    SupplyChainService (src/service.py) est l'orchestrateur : il choisit la topologie, lance les agents en parallèle,
    croise les blocs météo et finance dans les événements médias, appelle le moteur et construit la courbe de
    l'indice. L'API FastAPI (src/api/main.py) n'a aucune logique métier : elle valide les requêtes et délègue au
    service. Deux interfaces la consomment : React (frontend/, recommandée) et Streamlit (app/, repli historique,
    capable de tourner sans API grâce à un moteur embarqué).

    LE COPILOT ET OLLAMA
    Le Copilot (src/copilot/assistant.py) n'accède à rien d'autre qu'au moteur, via 8 outils. Ollama est optionnel
    et sert à deux endroits : extraction des événements médias et Copilot. S'il est absent, tout fonctionne avec la
    baseline NLP et le routeur déterministe du Copilot.

    POURQUOI CETTE DÉCOUPE
    1. Séparer la collecte (code planifiable, sans LLM, testable) de l'interprétation (moteur) : c'est un principe
       du PDF d'architecture (« la collecte est du code planifié, sans LLM »).
    2. Un contrat unique entre agents et moteur évite N formats ad hoc.
    3. Les agents ne calculent aucun score : décision d'équipe, la gravité appartient au Bloc 4 (moteur), qui seul
       voit le graphe, les stocks et les autres sources.
    4. Le moteur est pur et déterministe : mêmes événements, même date de référence, même résultat. C'est ce qui rend
       le replay et le backtesting possibles.

    ÉCART AVEC L'ARCHITECTURE CIBLE
    Le PDF d'architecture décrit un « agent ontologie » qui fusionne les sources dans un graphe de connaissances
    (Simple Event Model), un « agent de veille » qui explique chaque alerte en deux phrases, et une finance fondée
    sur GLEIF et SEC EDGAR (identifiants LEI, structure de propriété). Dans le code, la fusion est faite par le
    moteur déterministe, l'explication est une règle textuelle générée par alerts(), et la finance suit des prix de
    marché via yfinance. Les codes LEI sont prévus dans le schéma (EntityRef.id = "LEI:...") mais aucun n'est
    renseigné, car les fournisseurs sont fictifs.
    """)
    # sources
    srcs = [("GDELT DOC + 12 flux RSS", "repli Google News RSS", MEDIA_BG, MEDIA, False),
            ("Open-Meteo", "1 requête, tous les hubs", WEATHER_BG, WEATHER, False),
            ("Yahoo Finance", "yfinance, 6 mois", FIN_BG, FIN, False),
            ("Scénario JSON", "mode replay, daté", SOFT, MUTED, True)]
    for k, (a, b, bg, ln, dash) in enumerate(srcs):
        y = 1.6 + k * 0.74
        box(s, 0.5, y, 2.25, 0.62, fill=bg, line=ln, dash=dash,
            paras=[{"t": a, "b": True, "s": 13}, {"t": b, "s": 11, "c": MUTED}], space_after=0, margin=0.08)
    agents = [("MediaAgent", "baseline NLP ou LLM", MEDIA_BG, MEDIA),
              ("WeatherAgent", "seuils vent / pluie", WEATHER_BG, WEATHER),
              ("FinanceAgent", "variation 5 j, z-score", FIN_BG, FIN)]
    for k, (a, b, bg, ln) in enumerate(agents):
        y = 1.6 + k * 1.0
        box(s, 3.2, y, 2.05, 0.8, fill=bg, line=ln, lw=1.5,
            paras=[{"t": a, "b": True, "s": 14}, {"t": b, "s": 11, "c": MUTED}], space_after=0,
            anchor=MSO_ANCHOR.MIDDLE)
    for k in range(3):
        arrow(s, 2.75, 1.91 + k * 0.74, 3.2, 2.0 + k * 1.0, color=[MEDIA, WEATHER, FIN][k])
        arrow(s, 2.75, 4.13, 3.2, 2.05 + k * 1.0, color=MUTED, dash=True, width=1)
    box(s, 5.7, 1.6, 1.85, 2.8, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "NormalizedEvent", "b": True, "s": 14, "c": WHITE, "al": PP_ALIGN.CENTER},
        {"t": "contrat Pydantic", "s": 11, "c": MUTED_DARK, "al": PP_ALIGN.CENTER, "sa": 8},
        {"t": "event · date · location · entities · weather · finance · media · meta", "s": 11, "c": CYAN,
         "al": PP_ALIGN.CENTER}])
    for k in range(3):
        arrow(s, 5.25, 2.0 + k * 1.0, 5.7, 2.0 + k * 1.0, color=MUTED)
    box(s, 8.0, 1.6, 2.4, 2.8, fill=ICE, line=CYAN_D, lw=1.5, paras=[
        {"t": "OntologyEngine", "b": True, "s": 14, "c": NIGHT},
        {"t": "NetworkX · déterministe", "s": 11, "c": MUTED, "sa": 6},
        "- déduplication sémantique", "- rattachement aux nœuds", "- corrélation en signaux",
        "- risque direct", "- propagation", "- alertes · what-if"], size=12, space_after=1)
    arrow(s, 7.55, 3.0, 8.0, 3.0, color=NIGHT, width=2)
    box(s, 10.85, 1.6, 1.98, 2.8, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "SupplyChainService", "b": True, "s": 13, "c": WHITE, "al": PP_ALIGN.CENTER},
        {"t": "orchestrateur", "s": 11, "c": MUTED_DARK, "al": PP_ALIGN.CENTER, "sa": 12},
        {"t": "API FastAPI", "b": True, "s": 13, "c": CYAN, "al": PP_ALIGN.CENTER},
        {"t": "9 endpoints", "s": 11, "c": MUTED_DARK, "al": PP_ALIGN.CENTER}])
    arrow(s, 10.4, 3.0, 10.85, 3.0, color=NIGHT, width=2)
    # deuxième rangée
    box(s, 3.2, 4.75, 2.05, 0.85, fill=WHITE, line=MUTED, dash=True, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "Ollama qwen2.5", "b": True, "s": 13}, {"t": "optionnel", "s": 11, "c": MUTED}], space_after=0)
    arrow(s, 4.22, 4.75, 4.22, 4.4, color=MUTED, dash=True, width=1)
    box(s, 5.7, 4.75, 1.85, 0.85, fill=WHITE, line=CYAN_D, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "Copilot", "b": True, "s": 13}, {"t": "8 outils sur le moteur", "s": 11, "c": MUTED}],
        space_after=0)
    arrow(s, 5.25, 5.17, 5.7, 5.17, color=MUTED, dash=True, width=1)
    arrow(s, 7.55, 5.0, 8.3, 4.4, color=CYAN_D, width=1.25)
    box(s, 8.0, 4.75, 2.4, 0.85, fill=SOFT, line=LINE, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "Topologie YAML", "b": True, "s": 13}, {"t": "une par entreprise / secteur", "s": 11,
                                                            "c": MUTED}], space_after=0)
    arrow(s, 9.6, 4.75, 9.6, 4.4, color=MUTED)
    box(s, 10.85, 4.75, 1.98, 0.5, fill=ICE, line=CYAN_D, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "React + Vite (:5173)", "b": True, "s": 12, "al": PP_ALIGN.CENTER}])
    box(s, 10.85, 5.33, 1.98, 0.42, fill=SOFT, line=LINE, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "Streamlit (repli)", "s": 12, "al": PP_ALIGN.CENTER}])
    arrow(s, 11.84, 4.4, 11.84, 4.75, color=NIGHT)
    text(s, 0.5, 4.8, 2.4, 0.8, ["→ flux de données", "⇢ optionnel / replay"], size=11, color=MUTED, space_after=2)
    perspective(s, 0.5, 5.92, 12.33, 0.82, [
        "Agent ontologie LLM fusionnant les sources dans un graphe de connaissances (Simple Event Model), agent de "
        "veille qui rédige l'explication de chaque alerte, finance GLEIF / SEC EDGAR (LEI, propriété). Aujourd'hui : "
        "moteur déterministe, règles textuelles, prix de marché yfinance."], size=12)


def slide_03():
    s = frame("Séquence d'un POST /pipeline/run", 1,
              "src/service.py (run_pipeline, use_topology, _cross_fill) · src/agents/base.py · src/schemas/events.py",
              """
    CE QUE FAIT run_pipeline, PAS À PAS (src/service.py)
    1. Verrou. Tout le corps est sous `async with self._lock` (asyncio.Lock). Deux clics simultanés sur « Lancer
       l'analyse » ne peuvent pas entrelacer deux calculs et produire un état incohérent : le second attend.
    2. Topologie. En replay, le scénario porte sa propre chaîne (meta.topology) ; en live, l'utilisateur choisit la
       topologie (req.topology), sinon c'est la topologie par défaut. use_topology() charge le YAML, et si le chemin
       a changé, reconstruit le moteur, les trois agents (référentiels entreprises, lieux, hubs météo, instruments
       financiers tirés de la topologie) et le Copilot. C'est ce qui rend l'outil multi-secteur sans code spécifique.
    3. Date de référence as_of. En replay : start_date + (jour − 1). En live : aujourd'hui, avec une fenêtre de
       7 jours (settings.lookback_days).
    4. Courbe sans fuite du futur. En replay, les jours 1 à J−1 sont rejoués un par un : chaque agent ne voit que ce
       qui était publié ou émis ce jour-là (articles_as_of, champ issued des prévisions, cours jusqu'à as_of). Seule la
       baseline est utilisée pour ces jours passés : le LLM, coûteux, ne sert qu'au jour affiché. Chaque point de la
       courbe est donc ce qu'un analyste aurait vu à cette date, pas une reconstruction a posteriori.
    5. Collecte parallèle. asyncio.gather lance les trois agent.run() en même temps. Les appels bloquants (requests,
       gdeltdoc, yfinance, spaCy) tournent dans des threads via asyncio.to_thread : l'API reste réactive.
    6. Fusion. _cross_fill fait la validation croisée : un événement médias reçoit le bloc weather ou finance observé
       sur le même nœud (lien exact) à moins de 3 jours ; les blocs remplis sortent de donnees_manquantes. Puis
       engine.ingest(events, as_of) remplace l'état courant par une nouvelle Evaluation.
    7. Résultat. PipelineRunResult : status success / partial (un agent en panne ou une source dégradée) / error
       (aucun agent n'a réussi), résumé par agent, nombre d'événements, de signaux et d'alertes, indice global,
       timeline.

    LA RÈGLE « PANNE ≠ ABSENCE D'ALERTE »
    Si aucun agent ne réussit, le service ne calcule rien et conserve l'état précédent. Le message le dit
    explicitement : « Ce n'est pas une absence d'alerte ». Afficher un graphe vert après une coupure réseau serait la
    pire erreur possible pour un outil d'alerte : l'utilisateur conclurait que tout va bien. Exception : si la
    topologie vient de changer, le graphe est neuf et vide, et le message le précise.

    EN LIVE, LA COURBE
    Elle est reconstruite à partir de la date des événements : pour chaque jour de la fenêtre, on évalue le moteur sur
    les événements datés jusqu'à ce jour.

    LA FIGURE À DROITE
    Indice global du scénario crisis_asia_semiconductors, recalculé jour par jour par le moteur (aucun chiffre écrit
    en dur) : 6,0 / 21,9 / 31,1 / 31,7 / 31,7 / 38,7 / 40,6. Elle est produite par scripts/export_soutenance.py.
    """)
    steps = [
        ("Verrou `asyncio.Lock`", "un seul pipeline à la fois : pas d'état incohérent"),
        ("Topologie", "`meta.topology` ou `req.topology` → `use_topology()` reconstruit moteur et agents"),
        ("Date de référence `as_of`", "replay : start_date + (J − 1) · live : aujourd'hui, fenêtre de 7 jours"),
        ("Courbe sans fuite du futur", "jours 1…J−1 rejoués avec ce qui était connu ce jour-là (baseline seule)"),
        ("Collecte parallèle", "`asyncio.gather` sur les 3 `agent.run()` ; I/O bloquantes dans `asyncio.to_thread`"),
        ("Fusion puis moteur", "`_cross_fill` (météo/finance → médias) puis `engine.ingest(events, as_of)`"),
        ("`PipelineRunResult`", "success / partial / error · résumés agents · indice · timeline"),
    ]
    for k, (a, b) in enumerate(steps):
        y = 1.58 + k * 0.72
        num(s, 0.5, y + 0.08, k + 1)
        text(s, 1.08, y, 6.9, 0.36, a, size=15, color=NIGHT, bold=True, margin=0)
        text(s, 1.08, y + 0.32, 6.9, 0.4, b, size=12, color=MUTED, margin=0)
    s.shapes.add_picture(str(FIGURES / "indice_global_crisis_asia_semiconductors.png"), Inches(8.35), Inches(1.6),
                         width=Inches(4.48))
    text(s, 8.35, 4.15, 4.48, 0.6, "Indice global recalculé jour par jour : 6,0 → 40,6 (scénario "
         "crisis_asia_semiconductors)", size=11, color=MUTED, italic=True)
    box(s, 8.35, 4.85, 4.48, 1.85, fill=SOFT, line=None, paras=[
        {"t": "Règle « panne ≠ absence d'alerte »", "b": True, "s": 14, "c": NIGHT},
        "- aucun agent OK → état précédent conservé, status `error`",
        "- un agent KO → résultat `partial`, jamais silencieux",
        "- le LLM ne sert qu'au jour affiché"], size=12, space_after=2)


def slide_04():
    s = frame("Le contrat d'échange NormalizedEvent", 1,
              "src/schemas/events.py (NormalizedEvent, Strict, _no_fact_without_source) · tests/test_schemas.py",
              """
    POURQUOI UN CONTRAT UNIQUE
    Trois agents très différents (texte libre, mesures météo, séries de prix) doivent alimenter un seul moteur. Le
    contrat NormalizedEvent impose à tous la même forme : un événement (type dans une liste fermée), une date, un
    lieu, des entités, des preuves. Les blocs weather et finance sont optionnels et portent les mesures brutes. Le
    moteur n'a jamais besoin de savoir d'où vient un événement pour le rattacher au graphe.

    L'EXEMPLE AFFICHÉ EST RÉEL
    Il sort du moteur sur le scénario crisis_asia_semiconductors au jour 3 : l'article replay:crisis_asia:002
    annonce la suspension des opérations au port de Kaohsiung. La baseline l'a classé « logistique » par mots-clés
    (confiance conventionnelle 0,5). Le lieu « Port of Kaohsiung » a été reconnu par l'EntityRuler et ses
    coordonnées viennent du référentiel (jamais du LLM). Les blocs weather et finance ne viennent PAS de l'agent
    médias : ils ont été ajoutés par _cross_fill dans le service, parce que l'agent météo a mesuré des rafales de
    185 km/h sur le même nœud et que l'agent finance voit le fret Asie-Europe à +7,97 % (z-score 7,9) à moins de
    3 jours. C'est la validation croisée : l'article est corroboré par des mesures indépendantes.

    LES GARDE-FOUS DE VALIDATION (Pydantic v2)
    1. Classe Strict : ConfigDict(extra="forbid", validate_assignment=True). Une clé inattendue (par exemple
       inventée par un LLM : "severity", "confidence_score") fait échouer la validation au lieu d'être ignorée.
    2. Types fermés : EventType est un Literal (greve, catastrophe, sanction, faillite, cyberattaque, penurie,
       logistique, meteo_extreme, tension_marche, aucun) ; Role = touché | mentionné | exposé.
    3. Bornes : lat dans [−90, 90], lon dans [−180, 180], confidence dans [0, 1], mesures ≥ 0.
    4. Date : validateur _iso_date, format AAAA-MM-JJ strict.
    5. « Aucun fait sans source » (model_validator _no_fact_without_source) : un événement médias doit citer au moins
       un article, un événement météo doit porter un bloc weather, un événement finance un bloc finance. Un fait non
       sourcé ne peut pas exister dans le système.
    6. La propriété source_ids rassemble les identifiants des articles, du relevé météo et de la cotation : c'est
       elle qui alimente la traçabilité des alertes.

    LES TROIS RÔLES D'ENTITÉ
    touché : l'entreprise ou le site subit l'événement (lien de poids 1 dans le moteur). mentionné : simplement
    cité (non rattaché). exposé : rattachement élargi, par une matière première, un mot-clé sectoriel ou un pays
    (lien de poids 0,40). Les identifiants : "LEI:..." si un code LEI est connu, "SUP:<id>" pour un fournisseur du
    référentiel, "NODE:<id>" pour un nœud désigné par un agent, None sinon. Jamais inventés.

    donnees_manquantes
    Liste explicite de ce qui manque (weather, finance, location, entities, entities.lei, rattachement_exact). Dire ce
    qu'on ne sait pas est une exigence de l'outil : l'analyste voit la qualité de chaque événement.

    À RETENIR POUR LE JURY
    La date, les coordonnées, les identifiants et la liste media sont TOUJOURS calculés par le code (MediaNLP._assemble),
    même quand le LLM est actif. Le LLM qualifie ; il ne fabrique pas les faits vérifiables.
    """)
    lines = [
        '{',
        '  "event": {"id": "evt_0002",',
        '            "type": "logistique",                 #1',
        '            "label": "Port of Kaohsiung to suspend ..."},',
        '  "date": "2026-09-15",                           #2',
        '  "location": {"name": "Port of Kaohsiung",',
        '               "lat": 22.61, "lon": 120.28},      #3',
        '  "entities": [],                                 #4',
        '  "weather": {"hub": "port_kaohsiung",            #5',
        '              "gust_max_kmh": 185.0,',
        '              "precip_mm": 320.0, "forecast": false,',
        '              "source_id": "replay:meteo:port_kaohsiung:..."},',
        '  "finance": {"instrument": "FRET_ASIE_EUROPE",',
        '              "change_5d_pct": 7.97, "zscore": 7.9,',
        '              "source_id": "replay:FRET_ASIE_EUROPE:2026-09-16"},',
        '  "media": [{"titre": "Port of Kaohsiung to suspend ...",',
        '             "date": "2026-09-15T08:00:00Z",',
        '             "source_id": "replay:crisis_asia:002"}],  #6',
        '  "donnees_manquantes": ["entities"],             #7',
        '  "meta": {"agent": "media", "confidence": 0.5,',
        '           "extractor": "baseline",',
        '           "detail": "type : mots-cles"}          #8',
        '}',
    ]
    code(s, 0.5, 1.55, 7.35, 5.15, lines, size=11,
         title="Événement réel · jour 3 du scénario crisis_asia_semiconductors (extrait)")
    notes_ = [
        ("1", "`type` : liste fermée `EventType` (Literal) ; tout autre libellé est rejeté"),
        ("2", "date du plus ancien article, calculée par le code (format AAAA-MM-JJ validé)"),
        ("3", "coordonnées issues du référentiel de la topologie, jamais du LLM"),
        ("4", "rôles touché / mentionné / exposé ; identifiants `LEI:` `SUP:` `NODE:`, jamais inventés"),
        ("5", "blocs `weather` et `finance` ajoutés par `_cross_fill` : validation croisée"),
        ("6", "`source_id` = preuve traçable jusqu'à l'article"),
        ("7", "ce qui manque est dit explicitement"),
        ("8", "`meta` : agent, confiance de qualification (pas une gravité), extracteur"),
    ]
    for k, (n, t) in enumerate(notes_):
        y = 1.55 + k * 0.58
        num(s, 8.15, y + 0.04, n, d=0.36, fill=CODE_NOTE, color=NIGHT, size=12)
        text(s, 8.62, y, 4.21, 0.58, t, size=12, color=TEXT, margin=0)
    box(s, 8.15, 6.2, 4.68, 0.5, fill=ICE, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "`extra=\"forbid\"` + validateur « aucun fait sans source »"], size=12, color=NIGHT)


def slide_05():
    s = frame("API REST et schémas échangés en aval", 1,
              "src/api/main.py · src/schemas/events.py · frontend/src/api.ts · frontend/src/types.ts · tests/test_api.py",
              """
    UNE API MINCE
    src/api/main.py ne contient aucune règle métier. create_app(service) construit l'application FastAPI autour d'un
    SupplyChainService ; chaque route valide l'entrée avec un modèle Pydantic, appelle le service ou le moteur, et
    renvoie un modèle Pydantic (response_model). FastAPI en déduit la documentation OpenAPI interactive
    (http://localhost:8000/docs) et la sérialisation JSON.

    LES 9 ENDPOINTS
    - POST /pipeline/run : corps PipelineRunRequest {mode: live|replay, scenario, day ≥ 1, use_llm, topology}.
      Renvoie PipelineRunResult. 404 si le scénario ou la topologie est introuvable, 400 si la topologie est
      invalide (nœud inconnu, parts ≠ 1, cycle).
    - GET /graph/state : GraphState = as_of, mode, indice global, nœuds critiques, NodeState[] (attributs du nœud +
      direct, propagated, risk, level, path, signal_ids) et GraphEdge[].
    - POST /graph/simulate : {node_id, severity ∈ [0,1]} → SimulationResult. 404 si le nœud est inconnu.
    - GET /alerts : filtres level (warning|critical, validé par regex) et agent. Alert[] triées par priorité.
    - GET /events : événements normalisés enrichis (agent, nœuds rattachés, type de lien exact/élargi, journal
      d'extraction) et signaux corrélés.
    - POST /chat : ChatRequest {message, history, context} → ChatResponse {answer, mode llm|deterministic,
      tool_calls, context, note}.
    - GET /scenarios, GET /topologies, GET /health (nombre de nœuds et liens, LLM activé, modèle configuré et modèle
      réellement actif, dernier run).

    LA CHAÎNE DES SCHÉMAS
    AgentResult (sortie brute d'un agent : status, error_type, degraded, sources, events, journal) est résumé en
    AgentSummary dans PipelineRunResult. Les NormalizedEvent deviennent des CorrelatedSignal (regroupement par nœud
    et famille), qui déterminent les NodeState, dont on dérive les Alert. SimulationResult réutilise NodeState et
    NodeImpact. Chaque objet est un modèle Strict : le front-end peut compter sur la forme exacte.

    CÔTÉ FRONT
    frontend/src/types.ts recopie ces modèles en interfaces TypeScript, et api.ts expose un client typé : une seule
    fonction http<T>() qui distingue l'API injoignable (ApiError statut 0, avec la commande uvicorn à lancer) d'une
    erreur HTTP (on remonte le champ detail de FastAPI). La vérification TypeScript stricte (npm run build) détecte
    les écarts de forme.

    CORS ET TESTS
    Le middleware CORS n'autorise que http://localhost:5173 et http://127.0.0.1:5173 (serveur Vite). L'injection du
    service dans create_app permet aux tests (tests/test_api.py, 10 tests) d'utiliser le TestClient de FastAPI sur un
    service préparé, sans réseau.

    LES CODES D'ERREUR À CONNAÎTRE
    422 = la requête ne respecte pas le schéma (Pydantic) ; 404 = ressource inconnue ; 400 = topologie invalide.
    Un status "error" dans le corps de /pipeline/run n'est pas une erreur HTTP : c'est une panne de collecte,
    renvoyée en 200 avec l'explication.
    """)
    rows = [["Verbe", "Chemin", "Rôle", "Réponse"],
            ["POST", "/pipeline/run", "agents puis moteur (replay ou live)", "PipelineRunResult"],
            ["GET", "/graph/state", "nœuds : direct, propagé, total, chemin", "GraphState"],
            ["POST", "/graph/simulate", "what-if, état réel intact", "SimulationResult"],
            ["GET", "/alerts?level&agent", "alertes priorisées et expliquées", "list[Alert]"],
            ["GET", "/events", "événements normalisés + signaux", "EventsResponse"],
            ["POST", "/chat", "Copilot (LLM ou règles)", "ChatResponse"],
            ["GET", "/scenarios", "scénarios de replay", "list[dict]"],
            ["GET", "/topologies", "topologies disponibles", "list[dict]"],
            ["GET", "/health", "état, modèle LLM, dernier run", "Health"]]
    table(s, 0.5, 1.55, [0.8, 2.15, 3.0, 1.75], rows, row_h=0.42, size=12, mono_cols=(1, 3))
    box(s, 0.5, 5.95, 7.7, 0.75, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "**Codes :** 422 schéma invalide · 404 scénario, topologie ou nœud inconnu · 400 topologie invalide · "
        "CORS limité à `localhost:5173` · `create_app(service)` injectable pour les tests"], size=12)
    chain = [("NormalizedEvent", "sortie des agents", MEDIA_BG),
             ("CorrelatedSignal", "nœud × famille × 3 jours", ICE),
             ("NodeState · GraphState", "direct, propagé, total, chemin", ICE),
             ("Alert", "règle, chemin, source_ids, priorité", "FDE8E8")]
    for k, (a, b, bg) in enumerate(chain):
        y = 1.55 + k * 1.0
        box(s, 8.6, y, 4.23, 0.72, fill=bg, line=None, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": a, "b": True, "s": 14, "c": NIGHT}, {"t": b, "s": 12, "c": MUTED}], space_after=0)
        if k < 3:
            arrow(s, 10.7, y + 0.72, 10.7, y + 1.0, color=NIGHT)
    box(s, 8.6, 5.55, 4.23, 1.15, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "Miroir TypeScript", "b": True, "s": 14, "c": WHITE},
        {"t": "`types.ts` recopie les modèles ; `api.ts` = client typé + `ApiError` (0 = API injoignable)",
         "s": 12, "c": MUTED_DARK, "cc": CYAN}], space_after=2)


# =========================================================================== bloc 2
def slide_06():
    s = frame("Stack backend, données et déploiement", 2,
              "requirements.txt · Dockerfile · docker-compose.yml · pytest.ini · .streamlit/config.toml · src/config.py",
              """
    LE PRINCIPE DE SÉLECTION
    Des bibliothèques standard, gratuites, qui tournent sur un poste Windows d'étudiant sans GPU, et dont chaque
    dépendance « exotique » (collecte, NLP, LLM) est facultative avec un repli. Le socle obligatoire est petit :
    pydantic, networkx, PyYAML, requests, scikit-learn.

    BIBLIOTHÈQUE PAR BIBLIOTHÈQUE
    - Python 3.12 (image Docker python:3.12-slim) : écosystème data / NLP, async natif.
    - Pydantic v2 : le contrat de données. Validation stricte (extra="forbid"), validateurs métier, sérialisation
      JSON, et c'est le langage natif de FastAPI. Un seul fichier (src/schemas/events.py) décrit tout ce qui circule.
    - FastAPI + uvicorn : API asynchrone (les agents sont async), documentation OpenAPI générée, validation des
      requêtes gratuite, TestClient pour les tests. Alternative écartée : Flask (pas de validation ni d'async natifs).
    - NetworkX : graphe orienté (DiGraph), test d'acyclicité, tri topologique, descendants. Suffisant pour quelques
      dizaines à quelques milliers de nœuds, en mémoire, sans serveur. Neo4j aurait ajouté une infrastructure pour un
      graphe de 30 nœuds.
    - scikit-learn : TF-IDF, régression logistique, similarité cosinus. La baseline exigée par le sujet, rapide sur
      CPU, sans téléchargement de modèle.
    - PyYAML + JSON : topologies lisibles et éditables à la main par un acheteur (commentaires possibles en YAML),
      scénarios JSON versionnables.
    - requests + asyncio : http_get tolérant aux pannes ; asyncio.to_thread pour ne pas bloquer la boucle.
    - pytest + httpx : 155 tests, configurés dans pytest.ini (testpaths = tests, -q, DeprecationWarning ignorés).

    DÉPLOIEMENT DOCKER
    Une seule image pour deux services (docker-compose.yml) : « api » lance uvicorn sur le port 8000, « ui » lance
    Streamlit sur 8501. Le service ui attend que l'api soit « healthy » : un healthcheck Python appelle /health toutes
    les 10 s. Le dossier ./data est monté en volume (topologies, scénarios, cache modifiables sans reconstruire). Le
    LLM tourne sur la machine hôte : l'api l'atteint par host.docker.internal:11434 (extra_hosts host-gateway). Le
    Dockerfile télécharge le modèle spaCy xx_ent_wiki_sm et, s'il échoue, continue (repli sur les référentiels). Le
    conteneur tourne sous un utilisateur non root (appuser). Note : le front-end React n'est pas dans Docker ; il se
    lance avec npm run dev (Vite, port 5173) ou se construit avec npm run build.

    CONFIGURATION
    src/config.py centralise tous les réglages dans une dataclass Settings alimentée par des variables
    d'environnement : USE_LLM, LLM_BACKEND, LLM_BASE_URL, OLLAMA_MODEL / LLM_MODEL, budgets LLM, BROAD_LINKING,
    SC_DATA_DIR, SC_TOPOLOGY, SC_CACHE_DIR, seuils de déduplication. Aucune clé d'API n'est écrite dans le code
    (LLM_API_KEY vient de l'environnement). Les en-têtes HTTP « navigateur » y sont aussi : certains sites de presse
    renvoient 403 à un client qui s'annonce comme un script.

    STREAMLIT (REPLI)
    Streamlit, Plotly, pyvis et pandas servent l'interface historique app/ ; matplotlib sert les figures de
    soutenance (scripts/export_soutenance.py). Le thème sombre est fixé dans .streamlit/config.toml.
    """)
    cards = [("Python 3.12", "langage, async natif", "écosystème data / NLP"),
             ("Pydantic v2", "contrat de données", "validation stricte, JSON"),
             ("FastAPI + uvicorn", "API asynchrone", "OpenAPI et validation gratuites"),
             ("NetworkX", "graphe orienté", "DAG, tri topologique, en mémoire"),
             ("scikit-learn", "TF-IDF, régression logistique", "baseline rapide sur CPU"),
             ("PyYAML + JSON", "topologies, scénarios", "éditables à la main"),
             ("requests + asyncio", "HTTP tolérant, threads", "API jamais bloquée"),
             ("pytest + httpx", "155 tests", "sans réseau ni LLM")]
    for k, (a, b, c) in enumerate(cards):
        x = 0.5 + (k % 4) * 3.12
        y = 1.55 + (k // 4) * 1.5
        box(s, x, y, 2.97, 1.32, fill=SOFT, line=None, paras=[
            {"t": a, "b": True, "s": 16, "c": NIGHT, "sa": 3}, {"t": b, "s": 13},
            {"t": "→ " + c, "s": 12, "c": CYAN_D, "i": True}], space_after=2)
    # déploiement
    text(s, 0.5, 4.62, 6, 0.35, "Déploiement : docker compose up --build", size=14, color=NIGHT, bold=True)
    box(s, 0.5, 5.05, 2.3, 1.55, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "Image unique", "b": True, "s": 14, "c": WHITE}, {"t": "python:3.12-slim", "s": 12, "c": CYAN},
        {"t": "+ spaCy xx_ent_wiki_sm · utilisateur non root", "s": 11, "c": MUTED_DARK}], space_after=2)
    box(s, 3.25, 5.05, 2.4, 0.7, fill=ICE, line=CYAN_D, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "api · uvicorn :8000", "b": True, "s": 13}, {"t": "healthcheck /health (10 s)", "s": 11, "c": MUTED}],
        space_after=0)
    box(s, 3.25, 5.9, 2.4, 0.7, fill=SOFT, line=LINE, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "ui · Streamlit :8501", "b": True, "s": 13}, {"t": "depends_on : api healthy", "s": 11, "c": MUTED}],
        space_after=0)
    arrow(s, 2.8, 5.6, 3.25, 5.4)
    arrow(s, 2.8, 5.95, 3.25, 6.25)
    box(s, 6.1, 5.05, 2.55, 0.7, fill=WHITE, line=MUTED, dash=True, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "Ollama sur l'hôte", "b": True, "s": 13}, {"t": "host.docker.internal:11434", "s": 11, "c": MUTED}],
        space_after=0)
    arrow(s, 6.1, 5.4, 5.65, 5.4, dash=True, width=1)
    box(s, 6.1, 5.9, 2.55, 0.7, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "volume ./data", "b": True, "s": 13}, {"t": "topologies, scénarios, cache", "s": 11, "c": MUTED}],
        space_after=0)
    box(s, 9.0, 4.62, 3.83, 1.98, fill=ICE, line=None, paras=[
        {"t": "Configuration : src/config.py", "b": True, "s": 14, "c": NIGHT},
        "- dataclass `Settings` ← variables d'environnement",
        "- `USE_LLM`, `OLLAMA_MODEL`, `BROAD_LINKING`, `SC_TOPOLOGY`…",
        "- aucune clé d'API dans le code",
        "- React hors Docker : `npm run dev` (:5173)"], size=12, space_after=2)


def slide_07():
    s = frame("Collecte, NLP et LLM : bibliothèques et replis", 2,
              "requirements.txt · src/config.py · src/utils/llm.py · scripts/benchmark_ollama.py · "
              "data/cache/llm_benchmark.json",
              """
    LE PRINCIPE : CHAQUE DÉPENDANCE AVANCÉE EST FACULTATIVE
    Le requirements.txt le dit en commentaire : « chacun a un repli, signalé dans l'état des sources ». Le code teste
    la présence d'un paquet avant de l'importer (fonction _has dans media_sources.py, try/except import ailleurs). Si
    gdeltdoc manque, la source GDELT est « unavailable » et le rapport le dit ; si spaCy manque, l'extraction
    d'entités passe aux expressions régulières sur les alias ; si Ollama ne répond pas, la baseline prend le relais.
    Rien ne plante, et rien n'est caché : chaque repli est visible dans AgentResult.sources ou dans le journal
    d'extraction.

    LE TABLEAU
    - gdeltdoc : client de l'API GDELT DOC 2.0 (articles de presse mondiaux, 65 langues traduites). Une seule requête
      par collecte.
    - feedparser : lecture des flux RSS et du flux Google News RSS.
    - yfinance : historiques de cours Yahoo Finance (6 mois, quotidien) pour les instruments de market_watch.
    - spaCy, modèle xx_ent_wiki_sm (multilingue, entraîné sur Wikipédia) : NER ORG / LOC, plus un EntityRuler
      alimenté par la topologie. Choisi parce qu'il est léger (quelques dizaines de Mo) et multilingue.
    - rapidfuzz : correspondance floue (token_sort_ratio) pour relier « Formoz Power Semiconductor Co » à l'alias
      connu. Très rapide (C++).
    - scikit-learn : TF-IDF + régression logistique, cosinus pour la déduplication.
    - Ollama : serveur local de LLM open source, gratuit, sous Windows. Appel HTTP /api/chat avec format:"json" et
      keep_alive:"15m" (le modèle reste en mémoire entre deux articles). Le client accepte aussi un backend compatible
      OpenAI (/v1/chat/completions, response_format json_object) : LLM_BACKEND=openai.

    LE CHOIX DU MODÈLE (src/config.py, _configured_llm_model, puis src/utils/llm.py, active_model)
    Ordre de priorité : OLLAMA_MODEL, puis LLM_MODEL (ancien nom), puis la recommandation écrite par le dernier
    benchmark local dans data/cache/llm_benchmark.json, puis qwen2.5:3b par défaut. Sans variable d'environnement le
    modèle est « auto » : s'il n'est pas installé, le client interroge /api/tags et prend le premier disponible parmi
    qwen2.5:3b, qwen2.5:1.5b, qwen2.5:7b. Pourquoi Qwen 2.5 : bon suivi d'instructions JSON, multilingue (français,
    anglais, chinois : utile pour la presse asiatique), licence ouverte, tailles 1,5b / 3b / 7b.

    LE BENCHMARK (scripts/benchmark_ollama.py)
    Il mesure chaque qwen2.5 installé avec le même prompt que l'agent Médias : démarrage à froid, latence par
    article, tokens/s, validité du JSON, exactitude du type, du lieu et de l'entité. Mesure du 19/11/2026 sur le poste
    de développement (CPU) : qwen2.5:3b met 40 à 47 s par article (3,7 à 4,1 tokens/s), chargement à froid ≈ 16 s.
    Aucun modèle ne passe sous 10 s : le script recommande « le plus rapide au JSON fiable ». Conséquence importante :
    avec un délai de 15 s par article (LLM_ARTICLE_TIMEOUT_S), sur ce poste l'extraction LLM bascule presque toujours
    sur la baseline. Le LLM devient réellement utile avec un GPU ou un modèle plus petit. C'est une limite à assumer en
    soutenance, pas à cacher.

    ARCHITECTURE CIBLE (encadré violet)
    Le PDF d'architecture recommande un zero-shot multilingue (mDeBERTa-v3-base-xnli, licence MIT, version ONNX
    quantifiée ≈ 339 Mo), un fine-tuning XLM-R sur un jeu annoté, GLiNER multilingue pour les entités, et des
    embeddings de phrases multilingues pour la déduplication. Aucun n'est implémenté : ils supposent un échantillon
    annoté pour mesurer précision, rappel et F1, et une comparaison mots-clés / deep learning / zero-shot exigée par le
    sujet.
    """)
    rows = [["Bibliothèque", "Rôle", "Si absente"],
            ["gdeltdoc", "requête GDELT DOC 2.0", "source « unavailable »"],
            ["feedparser", "12 flux RSS + Google News", "source « unavailable »"],
            ["yfinance", "cours 6 mois par instrument", "agent finance en erreur"],
            ["spaCy xx_ent_wiki_sm", "NER + EntityRuler", "regex sur les alias"],
            ["rapidfuzz", "correspondance floue ≥ 90", "alias exacts seulement"],
            ["scikit-learn", "TF-IDF, régression log., cosinus", "pas de fusion sémantique"],
            ["Ollama /api/chat", "extraction + Copilot", "baseline + règles"],
            ["backend OpenAI", "`LLM_BACKEND=openai`", "—"]]
    table(s, 0.5, 1.55, [2.45, 3.05, 2.4], rows, row_h=0.45, size=12, first_col_bold=True)
    text(s, 8.75, 1.5, 4.1, 0.35, "Choix du modèle LLM", size=15, color=NIGHT, bold=True)
    chain = ["`OLLAMA_MODEL`", "`LLM_MODEL` (ancien nom)", "benchmark : `recommended`", "défaut : `qwen2.5:3b`",
             "non installé → `/api/tags`"]
    for k, t in enumerate(chain):
        y = 1.95 + k * 0.62
        box(s, 8.75, y, 4.08, 0.46, fill=ICE if k < 4 else SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE,
            paras=[f"{k + 1}. {t}"], size=12, color=NIGHT)
        if k < 4:
            arrow(s, 10.79, y + 0.46, 10.79, y + 0.62, color=CYAN_D, width=1.25)
    box(s, 8.75, 5.1, 4.08, 0.62, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "Mesure CPU : **qwen2.5:3b ≈ 40–47 s / article** > délai de 15 s → repli fréquent"], size=12)
    perspective(s, 0.5, 5.85, 12.33, 0.85, [
        "Zero-shot `mDeBERTa-v3-base-xnli` (NLI, 100 langues), fine-tuning XLM-R sur un jeu annoté, GLiNER multilingue "
        "pour les entités, embeddings de phrases multilingues pour le dédoublonnage, puis comparaison F1 mots-clés / "
        "deep learning / zero-shot."])


# =========================================================================== bloc 3
def slide_08():
    s = frame("Collecte médias multi-sources et HTTP tolérant", 3,
              "src/agents/media_sources.py · src/agents/media_agent.py · src/utils/http.py · src/config.py · "
              "scripts/check_feeds.py · tests/test_live_sources.py",
              """
    LA COLLECTE LIVE (MediaAgent.collect_live)
    Fenêtre : les 7 derniers jours. Deux collectes indépendantes lancées en parallèle dans des threads : GDELT
    (avec son repli) et les flux RSS. Les résultats sont fusionnés puis passés à finalize_articles.

    GDELT DOC 2.0 : UNE SEULE REQUÊTE
    La limite de débit de GDELT s'applique par adresse IP. Le notebook v2 faisait une requête par catégorie et se
    faisait bloquer ; la version actuelle fait une requête globale : (strike OR shortage OR bankruptcy OR
    cyberattack OR sanction) ET (« supply chain » OR factory OR port), en anglais car GDELT traduit 65 langues, avec
    100 articles au plus (gdelt_max, plafond API 250). Le classifieur aval répartit ensuite les articles par type.
    Mécanismes autour de la requête :
    1. Cache disque de 15 minutes (data/cache/gdelt/<hash>.json, clé = mots-clés, ancres, pays, plafond, durée) :
       des clics répétés pendant une démo ne renvoient pas la requête. Le rapport indique cache: true.
    2. Si GDELT a répondu « limite de débit » il y a moins de 5 minutes (data/cache/gdelt_cooldown/), on ne le rappelle
       pas : status failed, rate_limited true.
    3. gdeltdoc n'a pas de délai maximal : la requête tourne dans un ThreadPoolExecutor avec un délai de garde (60 s).
    4. Sur limite de débit : une pause (30 s), un seul nouvel essai. Échec : rate_limited, période de repos.
    5. Repli Google News RSS sur les mêmes mots-clés (articles réels, identifiants gnews:). Le résultat est marqué
       degraded (Google News ne couvre pas les 65 langues) et GDELT reste failed dans le rapport : le repli ne masque
       pas la panne.

    LES 12 FLUX RSS
    Presse économique européenne et presse supply chain (Supply Chain Dive, FreightWaves, Le Monde, BFM, Tagesschau,
    DW, NOS, BBC, Guardian, Euractiv, The Loadstar, Splash247). Chaque article est filtré par is_supply_related : il
    doit contenir un mot-clé d'événement ET une ancre supply chain (supplier, factory, port, semiconductor...). Cela
    écarte « grève des enseignants » ou « faillite d'un club de foot ». Un refus du site (403, 404) fait passer au flux
    suivant ; trois pannes réseau de suite arrêtent la collecte RSS (le réseau est probablement coupé). Une valeur du
    dictionnaire peut être une liste d'adresses de rechange. scripts/check_feeds.py teste chaque source depuis le
    poste avant une démo.

    http_get (src/utils/http.py) : NE LÈVE JAMAIS D'EXCEPTION
    200 : on renvoie la réponse. 429 ou 5xx : erreur transitoire, pause croissante (3 s × numéro d'essai) puis nouvel
    essai. 403, 404 et autres 4xx : abandon immédiat, réessayer ne sert à rien. Exception réseau : pause 1,5 s × essai.
    Après N essais (http_retries = 2) : None. Le dictionnaire info reçoit la cause (status ou nom de l'exception), ce
    qui permet au rapport de distinguer « le site refuse » de « le réseau est coupé ».

    LE SCHÉMA Article
    Une dataclass commune à toutes les sources : source_id unique de la forme <source>:<identifiant>, titre, texte,
    url, published_at en UTC (parse_dt accepte datetime, struct_time RSS, ISO, dates RFC 822), domaine, langue, pays.
    Deux champs sont remplis plus tard par la chaîne NLP : content et cluster_id.

    GKG 2.1 POUR LE BACKTESTING
    ingest_gkg_replay rejoue une période passée réelle à partir des fichiers bruts GKG (un toutes les 15 minutes,
    traductions incluses), filtrés par motifs (organisations, noms). C'est la brique prévue pour mesurer l'avance réelle
    sur Nexperia ou Helene ; elle existe dans le code mais n'est pas encore branchée à un scénario.
    """)
    a = [("Cache disque", "15 min"), ("Repos GDELT", "5 min après 429"), ("GDELT DOC 2.0", "1 requête · 100 art."),
         ("Google News RSS", "repli · degraded")]
    for k, (t1, t2) in enumerate(a):
        x = 0.5 + k * 1.93
        box(s, x, 1.6, 1.75, 0.9, fill=MEDIA_BG if k != 3 else SOFT, line=MEDIA if k != 3 else MUTED,
            dash=(k == 3), anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": t1, "b": True, "s": 13}, {"t": t2, "s": 11, "c": MUTED}], space_after=0)
        if k < 3:
            arrow(s, x + 1.75, 2.05, x + 1.93, 2.05, color=MEDIA)
    text(s, 0.5, 2.55, 7.4, 0.3, "manqué → manqué → limite de débit : pause 30 s + 1 essai → repli",
         size=11, color=MUTED, italic=True)
    b = [("12 flux RSS", "presse éco. + supply chain"), ("Filtre supply chain", "mot-clé ∧ ancre"),
         ("Refus ≠ panne", "stop après 3 pannes")]
    for k, (t1, t2) in enumerate(b):
        x = 0.5 + k * 1.93
        box(s, x, 3.0, 1.75, 0.9, fill=MEDIA_BG, line=MEDIA, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": t1, "b": True, "s": 13}, {"t": t2, "s": 11, "c": MUTED}], space_after=0)
        if k < 2:
            arrow(s, x + 1.75, 3.45, x + 1.93, 3.45, color=MEDIA)
    box(s, 6.29, 3.0, 1.75, 0.9, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE, margin=0.06,
        paras=[{"t": "finalize_articles", "b": True, "s": 10.5, "c": WHITE, "f": MONO},
               {"t": "→ list[Article]", "s": 10.5, "c": CYAN, "f": MONO}], space_after=0)
    arrow(s, 6.11, 3.45, 6.29, 3.45, color=NIGHT)
    arrow(s, 7.16, 2.5, 7.16, 3.0, color=NIGHT)
    code(s, 0.5, 4.15, 7.4, 1.25, [
        "(strike OR shortage OR bankruptcy OR cyberattack OR sanction)",
        "AND (\"supply chain\" OR factory OR port)  # GDELT traduit 65 langues"],
        size=11, title="Requête GDELT unique (mots-clés × ancres)")
    box(s, 0.5, 5.55, 7.4, 1.15, fill=SOFT, line=None, paras=[
        {"t": "GKG 2.1 (backtesting)", "b": True, "s": 13, "c": NIGHT},
        "`ingest_gkg_replay` : fichiers bruts toutes les 15 min, traductions incluses, filtrés par motifs. "
        "Prêt pour Nexperia / Helene, pas encore branché à un scénario."], size=12, space_after=2)
    text(s, 8.3, 1.5, 4.5, 0.35, "Politique de http_get", size=15, color=NIGHT, bold=True)
    rows = [["Réponse", "Action"], ["200", "réponse renvoyée"], ["429, 5xx", "pause 3 s × essai, nouvel essai"],
            ["403, 404…", "abandon immédiat"], ["exception réseau", "pause 1,5 s × essai"],
            ["après 2 essais", "None : jamais d'exception"]]
    table(s, 8.3, 1.9, [1.7, 2.83], rows, row_h=0.4, size=12, first_col_bold=True)
    code(s, 8.3, 4.5, 4.53, 2.2, [
        "@dataclass",
        "class Article:",
        "  source_id: str   # <source>:<id>",
        "  title: str",
        "  url, text: str",
        "  published_at: datetime  # UTC",
        "  domain, language, source_country",
        "  content, cluster_id  # remplis par NLP"], size=11)


def slide_09():
    s = frame("Collecte météo et finance : seuils et anomalies", 3,
              "src/agents/weather_agent.py · src/agents/finance_agent.py · data/topology.yaml (market_watch, "
              "weather_watch) · src/graph/ontology_engine.py (event_intensity)",
              """
    PRINCIPE COMMUN
    Les agents météo et finance détectent un dépassement de seuil et transmettent les mesures brutes. Ils ne
    calculent pas de gravité : c'est le moteur qui transforme ces mesures en intensité (event_intensity). Leurs seuils
    sont des conventions à calibrer, écrites en constantes en tête de fichier.

    AGENT MÉTÉO (WeatherAgent)
    Hubs surveillés : les nœuds de la topologie avec weather_watch: true et des coordonnées (22 dans la topologie par
    défaut : fournisseurs, ports, usines). En live, UNE requête Open-Meteo pour tous les hubs (latitudes et longitudes
    séparées par des virgules) avec les variables quotidiennes wind_speed_10m_max, wind_gusts_10m_max,
    precipitation_sum et weather_code, sur 2 jours passés et 4 jours de prévision. Une seule requête : moins de risque
    de limite de débit et une collecte en une seconde.
    Seuils (is_extreme) : rafales ≥ 90 km/h, ou vent moyen ≥ 75 km/h, ou pluie ≥ 60 mm sur 24 h.
    Extraction (extract_events), pas à pas :
    1. Pour un même hub et un même jour, la prévision la plus récente (champ issued) remplace l'ancienne.
    2. On mémorise la PREMIÈRE émission en dépassement : c'est la date de l'événement. Une prévision de typhon émise
       au jour 1 pour le jour 3 date l'événement au jour 1 : c'est précisément le signal faible recherché.
    3. Un événement par hub en dépassement, de type meteo_extreme, avec le pic (rafales et pluie rapportées aux seuils)
       comme mesure, l'entité NODE:<hub> en rôle touché et les coordonnées du hub.
    4. Confiance : 0,9 pour un relevé, 0,7 pour une prévision (conventions).
    En replay, les observations du scénario ne sont visibles que si issued ≤ as_of : pas de fuite du futur.

    AGENT FINANCE (FinanceAgent)
    Instruments : le bloc market_watch de la topologie (fret Asie-Europe via l'ETF BDRY, puces via SOXX, lithium LIT,
    cuivre HG=F, terres rares REMX), chacun relié aux nœuds qu'il touche. Ce sont des indicateurs approchés : un ETF de
    fret sec n'est pas un indice de fret conteneur. En live : 6 mois de clôtures quotidiennes par instrument.
    Calcul :
    - variation sur 5 séances Δ5(t) = 100 × (c_t / c_{t−5} − 1) ;
    - z-score de cette variation par rapport à l'historique qui précède, en excluant les 5 dernières séances (qui se
      recouvrent avec la fenêtre courante), avec au moins 20 points d'historique ;
    - plancher σ ≥ 1 point : un historique très calme ne doit pas transformer une petite variation en « 10 sigma » ;
    - anomalie si |Δ5| ≥ 8 %, ou si |z| ≥ 2,5 avec |Δ5| ≥ 3 % (un z-score élevé sur une variation minuscule n'est
      pas une alerte).
    Un événement tension_marche est émis si l'une des 3 dernières séances est en anomalie ; sa date est le DÉBUT de
    l'épisode (on remonte les séances consécutives en anomalie). Confiance 0,8.

    DE LA MESURE À L'INTENSITÉ (dans le moteur)
    Météo : intensité = clip(max((rafale − 70) / 110, (pluie − 40) / 210), 0,3, 1). Une rafale de 180 km/h ou 250 mm de
    pluie donnent l'intensité maximale 1. Finance : intensité = clip(max(|z| / 4, |Δ5| / 30), 0,3, 1). Un article a une
    intensité de 1 (il décrit un événement déjà qualifié). Le plancher 0,3 évite qu'un dépassement de seuil compte pour
    presque rien.
    """)
    # météo
    box(s, 0.5, 1.55, 5.95, 5.15, fill=WEATHER_BG, line=None)
    text(s, 0.75, 1.68, 5.5, 0.4, "WeatherAgent · Open-Meteo", size=17, color=WEATHER, bold=True)
    for k, (v, l) in enumerate([("90", "km/h rafales"), ("75", "km/h vent moyen"), ("60", "mm pluie / 24 h")]):
        x = 0.75 + k * 1.85
        text(s, x, 2.15, 1.8, 0.7, v, size=34, color=WEATHER, bold=True, margin=0)
        text(s, x, 2.85, 1.8, 0.35, l, size=12, color=TEXT, margin=0)
    text(s, 0.75, 3.35, 5.5, 2.3, [
        "- 1 requête pour les 22 hubs `weather_watch`",
        "- 2 jours passés + 4 jours de prévision",
        "- la prévision la plus récente remplace l'ancienne",
        "- date = **première émission** en dépassement (signal précoce)",
        "- confiance 0,9 relevé · 0,7 prévision"], size=13, space_after=3, bullet_color=WEATHER)
    formula(s, 0.75, 5.6, 5.45, 0.95, ["I = clip( max( (rafale − 70)/110 , (pluie − 40)/210 ), 0,3 ; 1 )"], size=14,
            fill=WHITE, label="Intensité dans le moteur")
    # finance
    box(s, 6.88, 1.55, 5.95, 5.15, fill=FIN_BG, line=None)
    text(s, 7.13, 1.68, 5.5, 0.4, "FinanceAgent · yfinance", size=17, color=FIN, bold=True)
    for k, (v, l) in enumerate([("8 %", "sur 5 séances"), ("2,5 σ", "si |Δ5| ≥ 3 %"), ("20", "points d'historique")]):
        x = 7.13 + k * 1.85
        text(s, x, 2.15, 1.8, 0.7, v, size=34, color=FIN, bold=True, margin=0)
        text(s, x, 2.85, 1.8, 0.35, l, size=12, color=TEXT, margin=0)
    formula(s, 7.13, 3.35, 5.45, 1.25, [
        "Δ5(t) = 100 · ( c_t / c_{t−5} − 1 )",
        "z(t) = ( Δ5(t) − μ ) / max( σ ; 1 )"], size=15, fill=WHITE,
        label="μ, σ : historique hors 5 dernières séances")
    text(s, 7.13, 4.75, 5.5, 1.0, [
        "- anomalie sur l'une des 3 dernières séances",
        "- date = **début de l'épisode** · confiance 0,8",
        "- 5 instruments `market_watch` (BDRY, SOXX, LIT, HG=F, REMX)"], size=13, space_after=3, bullet_color=FIN)
    formula(s, 7.13, 5.75, 5.45, 0.8, ["I = clip( max( |z|/4 , |Δ5|/30 ), 0,3 ; 1 )"], size=14, fill=WHITE)


def slide_10():
    s = frame("Nettoyage et déduplication des articles", 3,
              "src/agents/media_nlp.py (preprocess, deduplicate, clean_title) · src/agents/media_sources.py "
              "(finalize_articles, articles_as_of) · src/utils/text.py · src/config.py",
              """
    POURQUOI DÉDUPLIQUER
    Un même incident est couvert par des dizaines d'articles (agences, reprises, traductions). Sans déduplication, le
    moteur compterait dix fois le même typhon et le risque exploserait artificiellement. Mais on ne veut pas jeter
    l'information : le nombre d'articles est un indice de couverture, et chaque source_id est une preuve. La solution :
    REGROUPER sans supprimer. Un groupe = un événement ; tous ses articles restent dans media[].

    ÉTAPE 1 : finalize_articles (media_sources.py)
    Force le schéma commun : titre et texte en chaînes nettoyées, lignes sans titre ou sans source_id retirées,
    source_id unique (le premier gagne).

    ÉTAPE 2 : preprocess (MediaNLP)
    Les articles sont triés du plus ancien au plus récent (les articles sans date à la fin). clean_title décode les
    entités HTML, normalise les espaces et retire le suffixe « - Reuters » des titres longs. On construit content =
    titre + ". " + texte. Doublons EXACTS : même URL normalisée (sans protocole, sans www, sans paramètres de suivi,
    sans slash final : normalize_url) ou même titre normalisé (norm_key : minuscules, sans accents, espaces
    réduits). On garde le plus ancien, car la date du premier signal fait autorité pour mesurer l'avance.

    ÉTAPE 3 : deduplicate (MediaNLP), doublons PROCHES
    1. TF-IDF sur les titres normalisés, analyseur char_wb, n-grammes de caractères de 3 à 5, sublinear_tf. Pourquoi
       des n-grammes de caractères et pas des mots : robustesse aux flexions (strike / strikes), aux fautes, aux noms
       propres translittérés, et un même vocabulaire de base fonctionne en plusieurs langues latines.
    2. Similarité cosinus entre toutes les paires : cos(u, v) = u·v / (‖u‖ ‖v‖), entre 0 et 1 pour des vecteurs TF-IDF.
    3. Deux articles sont reliés si cos ≥ 0,45 (settings.sim_threshold) ET s'ils sont à moins de 72 h
       (settings.window_hours). Comme les articles sont triés par date, la boucle interne s'arrête dès que l'écart
       dépasse 72 h (break) : c'est une optimisation simple du O(n²).
    4. Union-find (avec compression de chemin) : les groupes sont les composantes connexes du graphe des liens. La
       relation est donc transitive : si A ressemble à B et B à C, A, B et C forment un seul événement même si A et C
       sont peu similaires. C'est voulu (chaînes de reprises), avec le risque d'agréger deux incidents voisins ; le
       seuil et la fenêtre limitent ce risque.
    5. Chaque article reçoit un cluster_id evt_0001, evt_0002… dans l'ordre d'apparition.

    LA VUE « JOUR J » (articles_as_of)
    En replay, on ne garde que les articles publiés strictement avant as_of + 1 jour. C'est la garantie qu'aucun
    article du futur ne se glisse dans un calcul passé : condition indispensable pour mesurer honnêtement l'avance.

    UNE DEUXIÈME DÉDUPLICATION, PLUS LOIN
    Le moteur refait une passe au niveau des ÉVÉNEMENTS (semantic_dedupe, seuil 0,50, slide 16) : deux groupes
    d'articles classés différemment (« logistique » et « catastrophe ») mais décrivant le même incident sur le même
    nœud sont fusionnés avant le calcul de gravité. Limite commune aux deux passes : le TF-IDF ne rapproche pas deux
    langues différentes ; l'architecture cible prévoit des embeddings multilingues pour cela.

    LE SCHÉMA DE GAUCHE
    Illustration du principe (cinq articles fictifs) : A1–A2–A3 forment un groupe par transitivité ; A4–A5 un autre ;
    le lien A3–A4 (cos 0,21) est sous le seuil.
    """)
    steps = [("finalize_articles", "schéma commun, source_id unique"),
             ("preprocess", "titre nettoyé, URL / titre en double → le plus ancien"),
             ("TF-IDF char 3–5", "titres normalisés (`norm_key`)"),
             ("cos ≥ 0,45 et ≤ 72 h", "boucle coupée dès que l'écart > 72 h"),
             ("union-find", "composantes connexes → `cluster_id`")]
    for k, (a, b) in enumerate(steps):
        x = 0.5 + k * 2.52
        box(s, x, 1.55, 2.25, 1.15, fill=MEDIA_BG if k > 0 else SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": a, "b": True, "s": 14, "c": NIGHT}, {"t": b, "s": 11, "c": MUTED}], space_after=2)
        if k < 4:
            arrow(s, x + 2.25, 2.12, x + 2.52, 2.12, color=MEDIA, width=1.75)
    # schéma union-find
    box(s, 0.5, 3.0, 6.1, 3.7, fill=SOFT, line=None)
    text(s, 0.7, 3.08, 5.8, 0.35, "Union-find : un groupe = une composante connexe", size=14, color=NIGHT, bold=True)
    pts = {"A1": (1.0, 4.0), "A2": (2.3, 3.75), "A3": (2.0, 5.2), "A4": (4.3, 4.6), "A5": (5.4, 5.55)}
    g1 = box(s, 0.75, 3.55, 2.65, 2.35, fill=None, line=MEDIA, dash=True, lw=1.25)
    g2 = box(s, 3.95, 4.25, 2.4, 1.95, fill=None, line=CYAN_D, dash=True, lw=1.25)
    edges = [("A1", "A2", "0,71", False), ("A2", "A3", "0,52", False), ("A4", "A5", "0,63", False),
             ("A3", "A4", "0,21", True)]
    for a, b, lab, dash in edges:
        (x1, y1), (x2, y2) = pts[a], pts[b]
        arrow(s, x1 + 0.25, y1 + 0.25, x2 + 0.25, y2 + 0.25, color=MUTED if dash else NIGHT, width=1.25,
              dash=dash, head=False)
        text(s, (x1 + x2) / 2 + 0.3, (y1 + y2) / 2 + 0.02, 0.6, 0.3, lab, size=11,
             color=CRIT if dash else NIGHT, bold=True, margin=0)
    for name, (x, y) in pts.items():
        box(s, x, y, 0.5, 0.5, fill=WHITE, line=NIGHT, paras=[{"t": name, "al": PP_ALIGN.CENTER}], size=11,
            bold=True, color=NIGHT, shape=MSO_SHAPE.OVAL, margin=0, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 0.8, 5.95, 2.6, 0.3, "evt_0001", size=12, color=MEDIA, bold=True, font=MONO)
    text(s, 4.0, 6.25, 2.4, 0.3, "evt_0002", size=12, color=CYAN_D, bold=True, font=MONO)
    # formules
    formula(s, 6.9, 3.0, 5.93, 1.95, [
        "cos(u, v) = u · v / ( ‖u‖ · ‖v‖ )",
        "lien(i, j)  ⇔  cos ≥ 0,45  ∧  |t_i − t_j| ≤ 72 h",
        "visible(a, J)  ⇔  published_at < J + 1 jour"], size=15, label="Règles")
    box(s, 6.9, 5.1, 5.93, 1.6, fill=WHITE, line=LINE, paras=[
        {"t": "Pourquoi ces choix", "b": True, "s": 14, "c": NIGHT},
        "- n-grammes de caractères : flexions, fautes, noms propres",
        "- regrouper sans supprimer : chaque article reste une preuve",
        "- garder le plus ancien : la date du premier signal fait foi"], size=12, space_after=2)


def slide_11():
    s = frame("Extraction d'entités et rattachement au référentiel", 3,
              "src/agents/media_nlp.py (_load_nlp, _patterns, extract_entities, link_company, _pick_location, "
              "broad_links) · src/graph/ontology_engine.py (company/place/soft_referential)",
              """
    LES RÉFÉRENTIELS VIENNENT DU GRAPHE
    L'agent médias ne connaît pas les entreprises « en dur ». Au chargement d'une topologie, le moteur produit trois
    référentiels : company_referential (nœuds company: true, avec leurs alias), place_referential (ports et hubs en
    précision 3, villes des sites en précision 2, pays du gazetteer en précision 1, avec coordonnées) et
    soft_referential (indices larges : matières premières, mots-clés sectoriels, pays). C'est la consigne « brancher
    les référentiels du Bloc 4 » du notebook : changer de topologie change ce que l'agent sait reconnaître.

    NER : TROIS NIVEAUX DE DÉGRADATION (_load_nlp)
    1. spaCy xx_ent_wiki_sm + EntityRuler. L'EntityRuler est placé AVANT le NER statistique ; ses motifs viennent des
       référentiels (label ORG avec l'identifiant du fournisseur, LOC ou PORT pour les lieux) plus des motifs génériques
       « port of <Nom> », « port de / du <Nom> », « Hafen von <Nom> ». La comparaison se fait sur LOWER, donc
       insensible à la casse. Le NER statistique trouve en plus des organisations et lieux hors référentiel.
    2. Modèle absent : spacy.blank("xx") + EntityRuler. On ne reconnaît plus que le référentiel, mais on le reconnaît.
       Le modèle n'est jamais téléchargé au vol (comportement prévisible en démo et en Docker).
    3. spaCy absent : expressions régulières sur les alias normalisés (_fallback_entities).
    Le pipeline construit est mis en cache (_NLP_CACHE) par référentiel : le recharger à chaque requête coûterait
    plusieurs secondes.

    ENTITY LINKING (link_company)
    Une organisation trouvée par le NER est reliée au référentiel : d'abord par l'index d'alias exact après
    normalisation (norm_key), puis, pour un nom d'au moins 5 caractères, par correspondance floue rapidfuzz
    token_sort_ratio ≥ 90. token_sort_ratio trie les mots avant de comparer : « Semiconductor Formoz Power » et
    « Formoz Power Semiconductor » sont identiques. Seuil 90 : on préfère rater un lien qu'en créer un faux.
    Identifiant attribué : LEI:<code> si la topologie en fournit un, sinon SUP:<id> ; une organisation non reliée garde
    id = None et le rôle « mentionné ». Aucun identifiant n'est inventé. Un petit stop-list retire des faux positifs
    ORG classiques (« Entity List », « Ministry of Commerce »).

    LE LIEU (_pick_location)
    Parmi les lieux reconnus du référentiel : le plus précis d'abord (port/hub > ville > pays), puis celui cité dans un
    titre, puis le plus cité ; ordre alphabétique pour départager. Les coordonnées viennent du référentiel.

    LE RATTACHEMENT ÉLARGI (broad_links), MODE LIVE
    Problème réel : un article de presse cite rarement un fournisseur fictif de la base. Sans rattachement, presque
    tout l'actualité réelle resterait hors graphe. Règle : si l'événement n'a ni entreprise « touché » ni lieu de
    précision ≥ 2, on cherche dans le texte, dans cet ordre : (1) le nom d'une matière première de la topologie (début
    de mot, pour accepter les pluriels), (2) un mot-clé sectoriel d'un nœud (champ keywords), (3) à défaut seulement,
    un pays (mot entier). Le premier niveau qui trouve quelque chose l'emporte ; au plus 8 nœuds. Ces nœuds sont
    ajoutés avec le rôle « exposé », l'identifiant NODE:<id>, et la confiance de l'événement tombe à 0,40 ;
    donnees_manquantes contient rattachement_exact.
    Garde-fous dans le moteur : un lien élargi pèse 0,40 fois un lien exact, et ne corrobore jamais un signal exact.
    Un article seul rattaché ainsi ne peut pas déclencher d'alerte : il fait au mieux passer des nœuds « à surveiller ».
    Réglage BROAD_LINKING : live (défaut), always, never. Les scénarios de replay ne l'utilisent pas, et le chemin LLM
    non plus.

    L'EXEMPLE DU BAS
    Titre illustratif : aucune entreprise du référentiel n'y figure, mais « chip shortage » est un mot-clé des deux
    fournisseurs de puces. Ils sont rattachés en « exposé », poids 0,40.
    """)
    lvls = [("Niveau 1", "spaCy `xx_ent_wiki_sm` + EntityRuler (motifs de la topologie, « port of X »)"),
            ("Niveau 2", "modèle absent : `spacy.blank(\"xx\")` + EntityRuler"),
            ("Niveau 3", "spaCy absent : regex sur les alias normalisés")]
    text(s, 0.5, 1.5, 3.9, 0.35, "NER : dégradation progressive", size=15, color=NIGHT, bold=True)
    for k, (a, b) in enumerate(lvls):
        y = 1.95 + k * 1.15
        box(s, 0.5, y, 3.9, 0.92, fill=MEDIA_BG if k == 0 else SOFT, line=None,
            paras=[{"t": a, "b": True, "s": 13, "c": NIGHT}, {"t": b, "s": 12}], space_after=1)
        if k < 2:
            arrow(s, 2.45, y + 0.92, 2.45, y + 1.15, color=MUTED)
    text(s, 4.75, 1.5, 4.0, 0.35, "Entity linking", size=15, color=NIGHT, bold=True)
    link = [("Mention ORG", MEDIA_BG), ("alias exact (`norm_key`)", ICE),
            ("rapidfuzz `token_sort_ratio` ≥ 90", ICE), ("`LEI:` › `SUP:<id>` › None", NIGHT)]
    for k, (t, bg) in enumerate(link):
        y = 1.95 + k * 0.8
        box(s, 4.75, y, 3.95, 0.58, fill=bg, line=None, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": t, "al": PP_ALIGN.CENTER, "c": WHITE if bg == NIGHT else NIGHT,
                    "cc": CYAN if bg == NIGHT else CYAN_D}], size=13, bold=(k == 0))
        if k < 3:
            arrow(s, 6.72, y + 0.58, 6.72, y + 0.8, color=CYAN_D)
    text(s, 4.75, 5.15, 3.95, 0.4, "Lieu : port/hub (3) › ville (2) › pays (1), puis titre, puis fréquence",
         size=12, color=MUTED, italic=True)
    text(s, 9.05, 1.5, 3.8, 0.35, "Rattachement élargi (live)", size=15, color=NIGHT, bold=True)
    ladder = [("1", "matière première", "« lithium », « terres rares »"),
              ("2", "mot-clé sectoriel", "champ `keywords` d'un nœud"),
              ("3", "pays (à défaut)", "tous les nœuds du pays")]
    for k, (n, a, b) in enumerate(ladder):
        y = 1.95 + k * 0.85
        num(s, 9.05, y + 0.1, n, fill=MEDIA, color=WHITE)
        text(s, 9.6, y, 3.25, 0.35, a, size=13, color=NIGHT, bold=True, margin=0)
        text(s, 9.6, y + 0.33, 3.25, 0.4, b, size=12, color=MUTED, margin=0)
    box(s, 9.05, 4.55, 3.78, 1.0, fill=SOFT, line=None, paras=[
        "- rôle `exposé`, ≤ 8 nœuds",
        "- confiance 0,40 · poids 0,40 dans le moteur",
        "- ne corrobore jamais un lien exact"], size=12, space_after=1)
    code(s, 0.5, 5.75, 12.33, 0.95, [
        "« Chip shortage hits carmakers in Europe »   # exemple illustratif : aucune entreprise du référentiel",
        "→ mot-clé « chip shortage » → sup_chip_tw, sup_chip_nl (rôle exposé, poids 0,40, rattachement_exact manquant)"],
        size=11)


def slide_12():
    s = frame("Classification des événements : la baseline", 3,
              "src/agents/media_nlp.py (keyword_classify, get_classifier, tfidf_classify, classify, baseline_event, "
              "SEED_EXAMPLES) · src/agents/media_sources.py (EVENT_KEYWORDS)",
              """
    LES CLASSES
    Sept types de perturbation + « aucun » : greve, catastrophe, sanction, faillite, cyberattaque, penurie,
    logistique, aucun. Les agents météo et finance ajoutent leurs propres types (meteo_extreme, tension_marche) ; ils
    ne passent pas par ce classifieur. « aucun » est essentiel : la majorité des articles économiques ne décrit aucune
    perturbation, et un groupe classé « aucun » ne produit pas d'événement.

    DEUX CLASSIFIEURS COMPLÉMENTAIRES
    1. Mots-clés (keyword_classify). Un dictionnaire EVENT_KEYWORDS par type, multilingue (anglais, français,
       allemand, néerlandais : strike, grève, Streik, staking...). Comparaison sur texte normalisé, en début de mot.
       Le type gagnant est celui qui a le plus de mots trouvés ; les mots trouvés servent d'explication.
       Avantages : transparent, multilingue, aucun entraînement. Limites : pas de contexte (« strike a deal »),
       pas de probabilité.
    2. TF-IDF + régression logistique (get_classifier). TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
       sublinear_tf=True) puis LogisticRegression(C=10, max_iter=2000, class_weight="balanced"), dans un Pipeline
       scikit-learn entraîné une seule fois (variable globale). C=10 : régularisation faible, car le jeu est petit et
       propre. class_weight="balanced" : chaque classe pèse pareil même si elle a moins d'exemples.

    LE JEU D'ENTRAÎNEMENT : HONNÊTETÉ SUR SA NATURE
    Par défaut, 64 phrases écrites à la main (8 par classe, 8 classes) : SEED_EXAMPLES, repris du notebook v2. Le code
    le dit lui-même : « il sert à faire tourner la chaîne, pas à mesurer une performance ». Il ne contient aucune phrase
    des crises rejouées (pas de fuite entre entraînement et démonstration). Dès que l'équipe dépose un échantillon
    annoté data/annotated/articles_annotes.csv (colonnes text, label) d'au moins 20 lignes et 2 classes, il est utilisé
    à la place. Sinon, retour au jeu d'amorçage avec un avertissement dans les journaux.

    LA RÈGLE DE DÉCISION (classify), PAR ARTICLE
    - si la probabilité maximale de la régression ≥ 0,35 (settings.min_confidence) : type de la régression,
      confiance = cette probabilité, méthode tfidf_lr ;
    - sinon, si au moins un mot-clé est trouvé : type des mots-clés, confiance conventionnelle 0,5, méthode mots-cles ;
    - sinon : « aucun ».
    Le désaccord entre les deux classifieurs est enregistré (champ desaccord) : utile pour constituer le jeu annoté
    (les cas de désaccord sont les plus informatifs à annoter).

    DU GROUPE À L'ÉVÉNEMENT (baseline_event)
    Vote majoritaire des articles du groupe ; égalité départagée par ordre alphabétique (déterministe). Confiance = la
    meilleure confiance parmi les articles du type gagnant. Le libellé est le titre du premier article. Puis lieu,
    entités et, si besoin, rattachement élargi (slide précédente).

    CE QUI MANQUE POUR UNE ÉVALUATION SÉRIEUSE (encadré violet)
    Le sujet demande une comparaison mots-clés / deep learning / zero-shot avec précision, rappel, F1 et matrice de
    confusion. Elle n'est pas faite : il faut d'abord un échantillon annoté (quelques centaines d'articles). L'étape
    suivante logique : annoter les cas de désaccord, entraîner la baseline dessus, puis tester mDeBERTa zero-shot
    (aucun entraînement nécessaire) et un fine-tuning XLM-R, sur le même jeu de test.
    """)
    box(s, 0.5, 1.55, 3.2, 0.62, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "content = titre + texte", "al": PP_ALIGN.CENTER}], size=13, bold=True, color=NIGHT)
    arrow(s, 2.1, 2.17, 2.1, 2.4)
    box(s, 0.5, 2.4, 3.2, 0.95, fill=MEDIA_BG, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "TF-IDF char 2–5 + LogReg", "b": True, "s": 13, "al": PP_ALIGN.CENTER},
        {"t": "C = 10 · class_weight = balanced", "s": 11, "c": MUTED, "al": PP_ALIGN.CENTER}], space_after=0)
    arrow(s, 2.1, 3.35, 2.1, 3.6)
    box(s, 0.5, 3.6, 3.2, 0.62, fill=WHITE, line=NIGHT, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "proba max ≥ 0,35 ?", "al": PP_ALIGN.CENTER}], size=13, bold=True, color=NIGHT,
        shape=MSO_SHAPE.FLOWCHART_DECISION, margin=0)
    box(s, 4.15, 3.6, 2.3, 0.62, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "type LogReg (tfidf_lr)", "al": PP_ALIGN.CENTER}], size=12, color=WHITE)
    arrow(s, 3.7, 3.91, 4.15, 3.91, color=OK)
    text(s, 3.72, 3.55, 0.4, 0.3, "oui", size=11, color=OK, bold=True, margin=0)
    arrow(s, 2.1, 4.22, 2.1, 4.5)
    text(s, 2.18, 4.2, 0.5, 0.3, "non", size=11, color=CRIT, bold=True, margin=0)
    box(s, 0.5, 4.5, 3.2, 0.62, fill=WHITE, line=NIGHT, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "mot-clé trouvé ?", "al": PP_ALIGN.CENTER}], size=13, bold=True, color=NIGHT,
        shape=MSO_SHAPE.FLOWCHART_DECISION, margin=0)
    box(s, 4.15, 4.5, 2.3, 0.62, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "type mots-clés (conf. 0,5)", "al": PP_ALIGN.CENTER}], size=12, color=WHITE)
    arrow(s, 3.7, 4.81, 4.15, 4.81, color=OK)
    arrow(s, 2.1, 5.12, 2.1, 5.4)
    box(s, 0.5, 5.4, 3.2, 0.5, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "« aucun »", "al": PP_ALIGN.CENTER}], size=13, bold=True, color=MUTED)
    box(s, 0.5, 6.08, 5.95, 0.62, fill=ICE, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "Groupe : **vote majoritaire** des articles · « aucun » → pas d'événement"], size=12)
    # classes
    text(s, 6.9, 1.5, 5.9, 0.35, "8 classes (7 perturbations + « aucun »)", size=15, color=NIGHT, bold=True)
    classes = [("greve", "strike, grève, Streik"), ("catastrophe", "typhoon, séisme, flood"),
               ("sanction", "export ban, embargo"), ("faillite", "chapter 11, insolvency"),
               ("cyberattaque", "ransomware, hacked"), ("penurie", "shortage, production halt"),
               ("logistique", "port closure, congestion"), ("aucun", "earnings, résultats…")]
    for k, (c, ex) in enumerate(classes):
        x = 6.9 + (k % 2) * 2.98
        y = 1.95 + (k // 2) * 0.66
        box(s, x, y, 2.85, 0.56, fill=MEDIA_BG if c != "aucun" else SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": c, "b": True, "s": 13, "f": MONO, "c": NIGHT}, {"t": ex, "s": 11, "c": MUTED}],
            space_after=0, margin=0.1)
    box(s, 6.9, 4.65, 5.93, 0.95, fill=SOFT, line=None, paras=[
        {"t": "Jeu d'entraînement", "b": True, "s": 13, "c": NIGHT},
        "64 phrases d'amorçage (8 × 8), ou `data/annotated/articles_annotes.csv` dès 20 lignes et 2 classes"],
        size=12, space_after=1)
    perspective(s, 6.9, 5.72, 5.93, 0.98, [
        "Zero-shot NLI (mDeBERTa), fine-tuning BERT / XLM-R, évaluation F1 et matrice de confusion sur un jeu "
        "annoté."], size=12)


def slide_13():
    s = frame("LLM local Ollama : prompt strict, contrôles et replis", 3,
              "src/agents/media_nlp.py (LLM_SYSTEM_PROMPT, llm_event, extract_events, relevance) · src/utils/llm.py · "
              "src/config.py · tests/test_agents.py -k llm",
              """
    OÙ INTERVIENT LE LLM
    L'extraction LLM est optionnelle (case « Extraction par LLM local » de l'interface, ou use_llm dans la requête).
    Le LLM remplace la baseline pour QUALIFIER un groupe d'articles : type, libellé en français, lieu, entreprises et
    leurs rôles. Il ne fabrique jamais les faits vérifiables.

    LE PROMPT (LLM_SYSTEM_PROMPT, inchangé depuis le notebook v2)
    Un seul objet JSON, exactement 5 clés dans l'ordre (event, date, location, entities, media), aucune autre. Type
    pris dans une liste fermée avec une définition de chaque classe. Libellé : une phrase en français de 120 caractères
    au plus. lat et lon toujours null (« le système les calcule »), id d'entité toujours null. Entités : uniquement des
    entreprises nommées, jamais un gouvernement, un pays ou une personne. Règle 9 : « N'invente rien. N'utilise aucune
    connaissance extérieure aux articles fournis ». Côté API, format:"json" (Ollama) ou response_format json_object
    (OpenAI) contraint la sortie à du JSON syntaxiquement valide. Le message utilisateur contient l'identifiant
    d'événement et jusqu'à 5 articles (1 500 caractères de texte chacun).

    LES CONTRÔLES APRÈS RÉPONSE (llm_event) : NE JAMAIS FAIRE CONFIANCE À LA SORTIE
    1. parse_llm_json extrait le premier objet JSON de la réponse (tolère un texte parasite autour).
    2. Les 5 clés doivent être présentes, sinon LLMError.
    3. Le type doit appartenir à MEDIA_EVENT_TYPES, sinon LLMError. « aucun » → pas d'événement.
    4. Lieu : accepté seulement s'il apparaît textuellement dans les articles (contains_term sur le corpus normalisé) ;
       relié au référentiel si possible (coordonnées du référentiel), sinon gardé sans coordonnées. Lieu absent du
       texte → on prend le lieu de la baseline et on le note.
    5. Entités : chacune doit apparaître dans le texte, elle-même ou un alias du fournisseur relié. Sinon elle est
       ÉCARTÉE et une note « absente des articles : écartée » est ajoutée. C'est le mécanisme anti-hallucination
       testé par un test qui simule un LLM inventant une entreprise.
    6. _assemble recalcule date (plus ancien article), media (titres et source_id réels), donnees_manquantes et
       identifiants. Si l'objet final viole le schéma Pydantic, LLMError.
    Confiance conventionnelle d'un événement LLM : 0,7.

    LE BUDGET (extract_events), CONÇU POUR UN CPU
    Les groupes sont triés par pertinence (relevance) :
      pertinence = 2 × (articles classés comme perturbation) + meilleure confiance + 1,5 × min(entités/lieux reliés, 4)
                   + 0,5 × taille du groupe.
    Seuls les 6 premiers (LLM_MAX_ARTICLES) passent par le LLM, du plus pertinent au moins pertinent. Chaque appel a
    un délai de 15 s (LLM_ARTICLE_TIMEOUT_S), et l'ensemble un budget de 30 s (LLM_BUDGET_S) ; num_predict = 512
    tokens. Après deux pannes RÉSEAU (LLMError avec network=True), le LLM est désactivé pour le reste du lot. Toute
    erreur (y compris inattendue) bascule ce groupe sur baseline_event. Avant tout, llm_available() vérifie que le
    serveur répond (/api/tags) : s'il est injoignable, tout passe en baseline, avec un avertissement.

    LE JOURNAL D'EXTRACTION
    Pour chaque groupe : extracteur (llm ou baseline) et détail (« sortie conforme », « repli sur la baseline : budget
    LLM de 30 s épuisé », « hors des 6 groupes les plus pertinents »...). Il remonte dans AgentResult.extraction et
    dans /events : l'analyste sait qui a produit chaque événement.

    LIMITE MESURÉE
    Sur le poste de développement (CPU), qwen2.5:3b met 40 à 47 s par article : au-delà du délai de 15 s. En
    pratique, sur ce poste, le chemin LLM se replie presque toujours sur la baseline. Pistes : GPU, qwen2.5:1.5b,
    réduction de num_predict, ou relever le délai pour une démonstration hors temps réel.
    """)
    flow = [("Groupes d'articles", SOFT), ("tri par pertinence", ICE), ("top 6 → LLM", MEDIA_BG),
            ("contrôles post-LLM", ICE), ("NormalizedEvent", NIGHT)]
    for k, (t, bg) in enumerate(flow):
        x = 0.5 + k * 2.5
        box(s, x, 1.55, 2.2, 0.7, fill=bg, line=None, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": t, "al": PP_ALIGN.CENTER}], size=13, bold=True, color=WHITE if bg == NIGHT else NIGHT)
        if k < 4:
            arrow(s, x + 2.2, 1.9, x + 2.5, 1.9, color=NIGHT, width=1.5)
    text(s, 10.5, 2.28, 2.33, 0.3, "extractor = llm, conf 0,7", size=11, color=MUTED, italic=True,
         align=PP_ALIGN.CENTER)
    box(s, 5.5, 2.75, 7.33, 0.55, fill="FDE8E8", line=CRIT, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "reste du lot · délai 15 s · budget 30 s épuisé · 2 pannes réseau · sortie invalide → `baseline_event()`"],
        size=12, color=NIGHT)
    arrow(s, 6.1, 2.25, 6.1, 2.75, color=CRIT, dash=True)
    arrow(s, 8.6, 2.25, 8.6, 2.75, color=CRIT, dash=True)
    formula(s, 0.5, 2.6, 4.75, 1.0, [
        {"t": "pertinence = 2·n_perturb. + conf_max + 1,5·min(n_reliés, 4) + 0,5·taille", "s": 12, "f": MATH,
         "i": True, "c": NIGHT}], label="relevance()")
    code(s, 0.5, 3.75, 6.3, 2.95, [
        "Exactement ces 5 clés, dans cet ordre :",
        '{"event": {"id", "type", "label"},',
        ' "date": "AAAA-MM-JJ",',
        ' "location": {"name", "lat": null, "lon": null},',
        ' "entities": [{"id": null, "name", "role"}],',
        ' "media": [{"titre", "date", "source_id"}]}',
        "9. N'invente rien.  # aucune connaissance extérieure",
        "format: \"json\" · keep_alive: \"15m\""], size=11, title="LLM_SYSTEM_PROMPT (extrait)")
    box(s, 7.1, 3.5, 5.73, 3.2, fill=ICE, line=None, paras=[
        {"t": "Contrôles post-LLM (llm_event)", "b": True, "s": 14, "c": NIGHT, "sa": 4},
        "- 5 clés présentes, sinon `LLMError`",
        "- type ∈ liste fermée, sinon `LLMError`",
        "- lieu cité dans les articles, sinon lieu de la baseline",
        "- entité absente du texte → **écartée** (anti-hallucination)",
        "- date, coordonnées, id, media : recalculés par `_assemble`",
        {"t": "Mesure CPU : 3b ≈ 40–47 s / article > 15 s → repli fréquent sur ce poste", "s": 12, "c": CRIT,
         "i": True}], size=13, space_after=3)


# =========================================================================== bloc 4
def slide_14():
    s = frame("Persistance : des fichiers et un état en mémoire", 4,
              "data/ · src/service.py · src/graph/ontology_engine.py (Evaluation) · src/agents/media_sources.py "
              "(cache_get, cache_put) · scripts/build_scenario.py · scripts/generate_sector_config.py",
              """
    IL N'Y A PAS DE BASE DE DONNÉES
    C'est un choix assumé pour un prototype mono-utilisateur. Tout ce qui doit durer est un fichier versionnable dans
    data/ ; tout ce qui est calculé vit en mémoire dans le processus de l'API.

    CE QUI EST SUR DISQUE
    - data/topology.yaml : la topologie par défaut (électronique de puissance et véhicule électrique, 30 nœuds,
      40 liens). data/topologies/pharma_helvia.yaml : la chaîne pharmaceutique de Helvia Pharma (19 nœuds, 22 liens).
      D'autres fichiers data/topology*.yaml ou data/topologies/*.yaml sont détectés automatiquement (list_topologies).
    - data/replay_scenarios/*.json : scénarios rejouables. Quatre blocs : meta (id, titre, fictional, notice, topologie,
      start_date, days, storyline jour par jour), media (articles datés), weather (relevés et prévisions avec issued),
      finance (séries de clôtures, au moins 25 jours d'historique avant le premier jour). Le scénario électronique
      contient 14 articles, 157 observations météo et 5 séries.
    - data/cache/ : cache JSON des réponses GDELT et Google News (15 min), marqueur de période de repos GDELT (5 min),
      fichiers GKG, résultat du benchmark LLM. Le cache stocke les Articles sérialisés et l'heure d'écriture : cache_get
      renvoie les articles et l'âge, ou None si le TTL est dépassé.
    - data/annotated/articles_annotes.csv : optionnel, jeu annoté pour le classifieur.
    - docs/figures/ : figures de soutenance générées.

    CE QUI EST EN MÉMOIRE
    SupplyChainService : engine (le moteur courant), agents, assistant (Copilot), agent_results (dernier résultat brut
    de chaque agent, avec le journal d'extraction), last_run (dernier PipelineRunResult, renvoyé par /health pour que le
    front retrouve l'état au rechargement), _lock.
    OntologyEngine : graph et active (NetworkX), nodes, edges, index d'alias et de lieux, events (événements courants),
    mode, et current, une Evaluation.

    L'OBJET Evaluation : UN INSTANTANÉ IMMUABLE
    Evaluation regroupe as_of, events (après déduplication), merged (qui a absorbé qui), signals, links (événement →
    nœuds), direct, risks (direct, propagé, total, chemin par nœud) et index. evaluate() fabrique une NOUVELLE
    Evaluation sans toucher à l'état ; ingest() la calcule puis la désigne comme état courant. Conséquence : la
    simulation what-if et la courbe de replay peuvent appeler evaluate() ou propagate() librement, sans jamais
    corrompre l'état réel. C'est un style fonctionnel appliqué au cœur du système.

    CONSÉQUENCES ET LIMITES
    Redémarrer l'API efface l'état : il faut relancer le pipeline (quelques secondes). Pas d'historique des alertes
    d'un jour sur l'autre en live, pas de multi-utilisateur (un seul état partagé, protégé par le verrou), pas de
    versionnement des topologies au-delà de git.

    FABRIQUER DES DONNÉES
    scripts/build_scenario.py fabrique les deux scénarios livrés à partir d'une description en Python.
    scripts/generate_sector_config.py génère une topologie et un scénario modèle pour un secteur (gabarits pharma
    19 nœuds et generique 9 nœuds) et vérifie une topologie (--check : nœud inconnu, parts ≠ 1, cycle, intrants à
    source unique).
    """)
    code(s, 0.5, 1.55, 4.3, 5.15, [
        "data/",
        "  topology.yaml          # défaut, 30 nœuds",
        "  topologies/",
        "    pharma_helvia.yaml   # 19 nœuds",
        "  replay_scenarios/",
        "    crisis_asia_semiconductors.json",
        "    crisis_pharma_api.json",
        "  cache/",
        "    gdelt/<hash>.json    # TTL 15 min",
        "    gdelt_cooldown/      # repos 5 min",
        "    google_news/",
        "    llm_benchmark.json",
        "  annotated/            # optionnel",
        "    articles_annotes.csv",
        "docs/figures/            # PNG soutenance"], size=11, title="Sur disque (versionnable)")
    text(s, 5.15, 1.5, 3.9, 0.35, "En mémoire (processus API)", size=15, color=NIGHT, bold=True)
    box(s, 5.15, 1.95, 3.85, 1.9, fill=NIGHT, line=None, paras=[
        {"t": "SupplyChainService", "b": True, "s": 14, "c": WHITE, "sa": 4},
        {"t": "engine · agents · assistant", "s": 12, "c": CYAN, "f": MONO},
        {"t": "agent_results · last_run", "s": 12, "c": CYAN, "f": MONO},
        {"t": "_lock (asyncio.Lock)", "s": 12, "c": CYAN, "f": MONO}], space_after=2)
    arrow(s, 7.07, 3.85, 7.07, 4.15, color=NIGHT)
    box(s, 5.15, 4.15, 3.85, 2.55, fill=ICE, line=CYAN_D, paras=[
        {"t": "OntologyEngine", "b": True, "s": 14, "c": NIGHT, "sa": 4},
        {"t": "graph · active (DiGraph)", "s": 12, "f": MONO},
        {"t": "events · mode", "s": 12, "f": MONO, "sa": 6},
        {"t": "current : Evaluation", "b": True, "s": 13, "c": CYAN_D},
        {"t": "events, signals, links, direct, risks, index", "s": 11, "c": MUTED}], space_after=1)
    code(s, 9.35, 1.55, 3.48, 3.0, [
        "{",
        ' "meta": {"topology",',
        '   "start_date", "days",',
        '   "fictional", "storyline"},',
        ' "media": [...],',
        ' "weather": [{"issued",',
        '   "date", "gust_max_kmh"}],',
        ' "finance": {"ID": [',
        '   {"date", "close"}]}',
        "}"], size=11, title="Scénario de replay")
    box(s, 9.35, 4.7, 3.48, 0.75, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "`evaluate()` crée une nouvelle `Evaluation` ; `ingest()` la rend courante"], size=12)
    perspective(s, 9.35, 5.55, 3.48, 1.15, [
        "SQLite / PostgreSQL pour historiser alertes et runs ; base graphe (Neo4j) au-delà de quelques milliers de "
        "nœuds."], size=11)


def slide_15():
    s = frame("Ontologie du graphe supply chain (NetworkX)", 4,
              "data/topology.yaml · data/topologies/pharma_helvia.yaml · src/graph/ontology_engine.py (__init__, "
              "_check_shares) · src/schemas/events.py (GraphNode, GraphEdge)",
              """
    LA STRUCTURE
    Un graphe orienté acyclique. Sens des liens : source → target signifie « source fournit target ». On remonte donc
    le graphe pour trouver les fournisseurs d'un nœud, et on le descend pour trouver ce qu'une panne menace. Six types
    de nœuds, rangés par rang (tier) : matière première (4), fournisseur de rang 3 ou 2, port et hub logistique (2,
    parfois 3), usine (1), produit fini (0).

    LA TOPOLOGIE PAR DÉFAUT (data/topology.yaml)
    30 nœuds : 5 matières premières (silicium, lithium, cobalt, terres rares, cuivre), 9 fournisseurs (4 de rang 3,
    5 de rang 2 : Formoz Power Semi à Tainan, Waal Semiconductors à Nimègue, Shenhai Cells, Odra Battery...), 8 ports
    (Kaohsiung, Keelung, Shanghai, Busan, Singapour, Rotterdam, Hambourg, Le Havre), 1 hub (fret aérien Francfort),
    4 usines (Rhein Power Modules à Stuttgart, Novalys Douai, Valenciennes, Leipzig), 3 produits finis (citadine E-City,
    SUV E-Trail, onduleur RX). 40 liens : 33 actifs, 7 de secours. Les entreprises sont fictives (pas de LEI), les
    ports et les villes sont réels avec leurs coordonnées.

    ATTRIBUTS D'UN NŒUD (GraphNode)
    id, name, type, tier, criticality (0 à 1 : importance métier, sert aux priorités et à l'indice), country, place,
    lat, lon, stock_days (jours de couverture : amortit la transmission du risque), aliases (noms utilisés par la
    presse), company (entre dans le référentiel entreprises de l'agent médias), weather_watch (surveillé par l'agent
    météo), keywords (mots-clés sectoriels du rattachement élargi).

    ATTRIBUTS D'UN LIEN (GraphEdge)
    input : catégorie d'intrant fournie à la cible (wafers, puces_puissance, fret_puces...). dependency : part de cet
    intrant couverte par cette source. Pour une cible et un intrant donnés, la somme des dependency vaut 1 : 0,7 + 0,3
    = deux sources. lead_time_days : délai. backup : lien de secours inactif (dependency 0), qui ne propage pas de
    risque mais est proposé dans le plan de mitigation. capacity : part maximale activable.
    Exemple réel : Rhein Power Modules reçoit ses puces de puissance à 70 % via le port de Rotterdam (flux Formoz) et à
    30 % de Waal Semiconductors (capacité 50 %, donc 20 points de réserve) ; secours : Hambourg (60 %, 3 j) et fret
    aérien Francfort (25 %, 1 j).

    LES DEUX GRAPHES DU MOTEUR
    self.graph contient tous les liens, secours compris. self.active ne contient que les liens actifs : c'est lui qui
    sert à la propagation. Le graphe complet sert à la mitigation (qui peut remplacer qui).

    LES VALIDATIONS AU CHARGEMENT (__init__)
    1. Chaque nœud et chaque lien passe par Pydantic (types, bornes).
    2. Nœud en double, lien vers un nœud inconnu : ValueError explicite.
    3. nx.is_directed_acyclic_graph : un cycle est refusé, car la propagation suppose un ordre (on calcule un nœud
       après tous ses fournisseurs).
    4. Ordre topologique calculé une fois (nx.topological_sort sur le graphe actif).
    5. _check_shares : pour chaque (cible, intrant), la somme des parts doit valoir 1.
    6. Index : alias normalisés (noms, alias, identifiants) → nœud ; lieux normalisés → nœuds. Un lieu qui ne désigne
       qu'un seul nœud (« Rotterdam ») devient aussi un alias de ce nœud.

    LES AUTRES BLOCS
    gazetteer : pays et régions sans nœud (Taiwan / Taïwan, Chine, Pays-Bas...), pour que l'agent médias reconnaisse
    les lieux. market_watch : instruments de l'agent finance avec leur symbole Yahoo et les nœuds qu'ils touchent.

    POURQUOI « ONTOLOGIE »
    Au sens du projet : un modèle explicite des concepts (fournisseur, site, intrant, événement, signal) et de leurs
    relations, qui permet au moteur de raisonner. L'architecture cible s'appuie sur le Simple Event Model (événement,
    acteur, lieu, temps) : le NormalizedEvent en reprend les quatre dimensions.
    """)
    cols = [("Tier 4", "Matières premières", "5", "lithium, terres rares…", MEDIA_BG),
            ("Tier 3", "Fournisseurs rang 3", "4", "wafers, cathodes, aimants", SOFT),
            ("Tier 2", "Fournisseurs rang 2 · ports · hub", "5 + 8 + 1", "Formoz, Kaohsiung, Rotterdam", ICE),
            ("Tier 1", "Usines", "4", "Stuttgart, Douai, Valenciennes…", FIN_BG),
            ("Tier 0", "Produits finis", "3", "E-City, E-Trail, onduleur RX", "FDE8E8")]
    for k, (t, name, n, ex, bg) in enumerate(cols):
        x = 0.5 + k * 2.5
        box(s, x, 1.55, 2.22, 1.55, fill=bg, line=None, paras=[
            {"t": t, "s": 11, "c": MUTED, "b": True}, {"t": name, "s": 13, "b": True, "c": NIGHT},
            {"t": n, "s": 22, "b": True, "c": CYAN_D, "sa": 0}, {"t": ex, "s": 11, "c": MUTED}], space_after=1)
        if k < 4:
            arrow(s, x + 2.22, 2.32, x + 2.5, 2.32, color=NIGHT, width=1.75)
    text(s, 0.5, 3.15, 12.3, 0.3, "source → target = « source fournit target » · 30 nœuds · 40 liens (33 actifs, "
         "7 de secours) · graphe sans cycle", size=12, color=MUTED, italic=True)
    rows = [["Nœud (GraphNode)", "Rôle"], ["criticality", "importance métier (0–1)"],
            ["stock_days", "amortit la transmission"], ["aliases · company", "référentiel de l'agent médias"],
            ["weather_watch", "hub surveillé par la météo"], ["keywords", "rattachement élargi"]]
    table(s, 0.5, 3.6, [2.1, 2.55], rows, row_h=0.4, size=12, mono_cols=(0,))
    rows = [["Lien (GraphEdge)", "Rôle"], ["input", "catégorie d'intrant"],
            ["dependency", "part de l'intrant (Σ = 1)"], ["backup", "secours inactif, mitigation"],
            ["capacity", "part activable"], ["lead_time_days", "délai"]]
    table(s, 5.4, 3.6, [2.0, 2.45], rows, row_h=0.4, size=12, mono_cols=(0,))
    box(s, 10.1, 3.6, 2.73, 3.1, fill=NIGHT, line=None, paras=[
        {"t": "Validations", "b": True, "s": 14, "c": WHITE, "sa": 4},
        {"t": "- Pydantic sur nœuds et liens", "c": WHITE},
        {"t": "- nœud inconnu → erreur", "c": WHITE},
        {"t": "- test d'acyclicité (NetworkX)", "c": WHITE},
        {"t": "- Σ dependency = 1", "c": WHITE},
        {"t": "- ordre topologique calculé une fois", "c": WHITE}], size=12, space_after=3, code_color=CYAN,
        bullet_color=CYAN)
    code(s, 0.5, 6.12, 9.35, 0.58, [
        "{source: port_rotterdam, target: plant_ecu_de, input: puces_puissance, dependency: 0.7}"],
        size=11)


def slide_16():
    s = frame("Du signal au risque direct", 4,
              "src/graph/ontology_engine.py (link_weights, semantic_dedupe, _correlate, event_intensity, _freshness, "
              "evaluate) · src/service.py (_cross_fill)",
              """
    LE PIPELINE DU MOTEUR (evaluate)
    1. semantic_dedupe : fusion des événements médias qui racontent le même incident.
    2. _correlate : rattachement aux nœuds et regroupement en signaux corrélés.
    3. Risque direct de chaque nœud à partir de ses signaux.
    4. propagate (slide suivante), puis l'indice global.

    LE RATTACHEMENT (link_weights)
    Pour chaque événement, le moteur cherche les nœuds touchés : entités au rôle « touché » (par identifiant, sinon
    par alias), puis le lieu de l'événement (index des lieux) : poids 1. Entités « exposé » : poids 0,40
    (SOFT_LINK_CONFIDENCE). Un événement sans aucun nœud reste hors graphe (visible dans /events, sans effet).

    LA DÉDUPLICATION SÉMANTIQUE (semantic_dedupe)
    Deux événements médias sont reliés si leurs textes (libellé + titres des articles) ont une similarité TF-IDF
    char 3–5 ≥ 0,50, s'ils sont à moins de 3 jours, et s'ils touchent au moins un nœud commun (ou aucun nœud tous les
    deux). Les groupes (union-find) sont fusionnés par _merge_events : type majoritaire pondéré par le nombre d'articles,
    toutes les sources, rôle d'entité le plus fort, date la plus ancienne, confiance maximale. Pourquoi avant la
    gravité : sinon un même incident classé « logistique » par un article et « catastrophe » par un autre produirait
    deux signaux de familles différentes et compterait deux fois.

    LA CORRÉLATION (_correlate)
    Clé de regroupement : (nœud, famille d'aléa). Les familles : climat (catastrophe, meteo_extreme), opérations
    (greve, logistique), réglementaire, financier, cyber, approvisionnement, marché. Dans une clé, les événements triés
    par date forment un même signal tant que l'écart avec le précédent est ≤ 3 jours. Un signal = un aléa sur un nœud,
    vu par une ou plusieurs sources.

    LES FORMULES
    - Gravité d'un événement = BASE_SEVERITY[type] × intensité × poids du lien. Gravités de base : faillite 0,90,
      catastrophe et météo extrême 0,80, sanction 0,70, grève et cyberattaque 0,65, logistique et pénurie 0,60, tension
      de marché 0,45. La gravité du signal est le maximum de ses événements.
    - Confiance du signal = clip(0,55 + 0,10 × min(nb sources − 1, 2) + 0,25 × (nb agents − 1)). Une source seule :
      0,55. Trois articles : 0,75. Deux agents indépendants : +0,25. Le recoupement entre agents compte plus que la
      répétition d'une même famille de sources, car deux articles peuvent se recopier, alors qu'un relevé météo et un
      article sont indépendants.
    - Règle des liens élargis : s'il existe dans le signal des événements à lien exact, eux seuls comptent pour le
      nombre de sources et d'agents. Un lien élargi ne corrobore jamais un lien exact.
    - Fraîcheur = 1 − 0,5 × min(jours écoulés depuis le dernier événement, 14) / 14 : de 1 (aujourd'hui) à 0,5 (deux
      semaines et plus). Un vieux signal compte encore, à moitié.
    - Contribution = gravité × confiance × fraîcheur.
    - Risque direct du nœud = 1 − Π(1 − contribution_k) : un « ou » probabiliste. Si chaque signal est la probabilité
      indépendante de perturber le nœud, c'est la probabilité qu'au moins un le perturbe. Propriétés : reste dans
      [0, 1], croît avec chaque signal, ne dépasse jamais 1, et deux signaux à 0,5 donnent 0,75 et non 1.

    L'EXEMPLE RÉEL (jour 3)
    Signal sig:port_kaohsiung:climat:1 : un relevé météo (rafales 185 km/h, pluie 320 mm → intensité 1) et un article
    sur le typhon, même nœud, même famille, moins de 3 jours. Gravité 0,80 × 1 × 1 = 0,80. Sources : 3 → +0,20 ;
    agents : médias + météo → +0,25 ; confiance = 0,55 + 0,20 + 0,25 = 1,00. Fraîcheur 1. Contribution 0,80. Avec les
    signaux opérations et marché sur le même nœud, le risque direct du port atteint 0,91.
    """)
    formula(s, 0.5, 1.55, 7.3, 4.0, [
        "gravité = BASE_SEVERITY[type] × intensité × poids_lien",
        "confiance = 0,55 + 0,10·min(n_sources − 1, 2) + 0,25·(n_agents − 1)",
        "fraîcheur = 1 − 0,5 · min(Δjours, 14) / 14",
        "contribution = gravité × confiance × fraîcheur",
        "direct(n) = 1 − Π_k ( 1 − contribution_k )"], size=19,
        label="Règles (ontology_engine.py) · poids_lien = 1 exact, 0,40 élargi")
    rows = [["Type", "Gravité", "Famille"], ["faillite", "0,90", "financier"], ["catastrophe", "0,80", "climat"],
            ["meteo_extreme", "0,80", "climat"], ["sanction", "0,70", "réglementaire"],
            ["greve", "0,65", "opérations"], ["cyberattaque", "0,65", "cyber"], ["logistique", "0,60", "opérations"],
            ["penurie", "0,60", "approvisionnement"], ["tension_marche", "0,45", "marché"]]
    table(s, 8.15, 1.55, [1.75, 0.95, 1.98], rows, row_h=0.36, size=12, mono_cols=(0,))
    box(s, 0.5, 5.7, 7.3, 1.0, fill=SOFT, line=None, paras=[
        {"t": "Avant : dédup sémantique (cos ≥ 0,50, ≤ 3 j, nœud commun) · corrélation par (nœud, famille, ≤ 3 j)",
         "s": 12, "c": NIGHT, "b": True},
        "Un lien élargi ne compte jamais comme source ou agent supplémentaire d'un signal exact."], size=12,
        space_after=2)
    code(s, 8.15, 5.32, 4.68, 1.38, [
        "sig:port_kaohsiung:climat:1",
        "gravité 0,80 · confiance 1,00",
        "  (0,55 + 0,20 + 0,25)  # 3 sources, 2 agents",
        "contribution 0,80 · corroborated"], size=11, title="Exemple réel, jour 3")


def slide_17():
    s = frame("Propagation de l'onde de choc dans le graphe", 4,
              "src/graph/ontology_engine.py (propagate, _transmission, global_index, level_of) · "
              "tests/test_ontology_engine.py · docs/figures/anticipation_plant_ecu_de.png",
              """
    L'IDÉE
    Un nœud peut être menacé sans qu'aucun article ne le cite : il suffit que ses fournisseurs le soient. La propagation
    calcule ce risque indirect en descendant le graphe des matières premières vers les produits finis.

    L'ALGORITHME (propagate), PAS À PAS
    On parcourt les nœuds dans l'ordre topologique du graphe actif : quand on traite un nœud, tous ses fournisseurs ont
    déjà leur risque total. Pour un nœud n :
    1. Pour chaque fournisseur p (lien actif p → n, intrant i, part d) : part perdue = d × risque(p).
    2. Perte de l'intrant i = Σ des parts perdues des sources de cet intrant. La redondance dilue : deux sources à 50 %
       dont une à risque 0,8 donnent une perte de 0,4, pas 0,8.
    3. On retient l'intrant le PLUS touché (max) : une usine a besoin de tous ses intrants ; il suffit qu'un seul
       manque pour arrêter la production. C'est un modèle « maillon le plus faible ».
    4. Transmission = DECAY × (1 − min(stock, 60) / 120), avec DECAY = 0,95. Le stock amortit : 0 jour de stock → 0,95 ;
       20 jours → 0,79 ; 60 jours ou plus → 0,475. On plafonne à 60 jours, car même un gros stock finit par s'épuiser
       pendant une crise longue. DECAY < 1 garantit que le risque s'atténue à chaque saut.
    5. Risque propagé = clip(transmission × perte de l'intrant le plus touché).
    6. Risque total = 1 − (1 − direct)(1 − propagé) : même « ou » probabiliste que pour les signaux.
    7. Chemin dominant : si le propagé l'emporte sur le direct, le chemin du nœud est celui du fournisseur responsable,
       prolongé du nœud. C'est ce chemin que l'alerte affiche (« depuis Port of Kaohsiung le long de 2 liens »).
    Complexité : un seul passage sur les nœuds et les liens, O(N + E).

    L'EXEMPLE CHIFFRÉ (jour 3, valeurs du moteur)
    Port of Kaohsiung : risque total 0,98 (direct 0,91 : typhon corroboré, fermeture du port, fret).
    Port of Rotterdam : un seul intrant fret_puces, à 100 % depuis Kaohsiung, stock 0 → transmission 0,95.
      Propagé = 0,95 × 1,0 × 0,98 = 0,93. Aucun article ne parle de Rotterdam à ce stade : alerte critique quand même.
    Rhein Power Modules (Stuttgart) : intrant puces_puissance = 70 % via Rotterdam + 30 % Waal (risque 0).
      Perte = 0,7 × 0,93 = 0,65 ; stock 20 jours → transmission = 0,95 × (1 − 20/120) = 0,79. Propagé = 0,52 →
      niveau « alerte ». C'est l'avance du système : l'usine est en alerte depuis le jour 2, le premier article qui la
      cite arrive au jour 6 (figure anticipation_plant_ecu_de.png). Quatre jours d'avance, sur un scénario écrit pour la
      démonstration : la vraie mesure demande le backtesting.

    NIVEAUX ET INDICE
    Niveaux : ok < 15 % ≤ info (« à surveiller ») < 35 % ≤ warning (« alerte ») < 60 % ≤ critical. Alerte émise à
    partir de 35 %. Indice global = 100 × Σ(w_n × risque_n) / Σ w_n, avec w_n = criticité × poids de type (produit fini
    ×3, usine ×2, autres ×1). Les produits finis pèsent plus parce que c'est ce que l'entreprise vend.

    LIMITES CONNUES (README)
    Un port traversé par plusieurs flux transmet le risque du flux le plus touché à tous ses clients (les topologies
    fournies l'évitent avec un flux principal par port d'arrivée). Une usine transmet son risque à tous ses produits,
    même ceux qui n'utilisent pas l'intrant touché. Les constantes (0,95, 60 j, 120) sont des règles d'experts à
    calibrer. Alternative citée dans le PDF d'architecture : PageRank personnalisé.
    """)
    formula(s, 0.5, 1.55, 6.2, 3.1, [
        "perte_i(n) = Σ_p  dep(p → n) × risque(p)",
        "T(n) = 0,95 × ( 1 − min(stock_n, 60) / 120 )",
        "propagé(n) = T(n) × max_i perte_i(n)",
        "total(n) = 1 − (1 − direct) (1 − propagé)",
        "indice = 100 · Σ w_n·risque_n / Σ w_n"], size=16,
        label="Ordre topologique · w = criticité × (3 produit, 2 usine, 1 sinon)")
    nodes = [("Port of Kaohsiung", "total 0,98", "direct 0,91", CRIT),
             ("Port of Rotterdam", "propagé 0,93", "0,95 × 1,0 × 0,98", CRIT),
             ("Stuttgart (usine)", "propagé 0,52", "0,79 × 0,7 × 0,93", ALERT)]
    for k, (a, b, c, col) in enumerate(nodes):
        x = 7.05 + k * 1.98
        box(s, x, 1.65, 1.8, 1.55, fill=WHITE, line=col, lw=2.25, anchor=MSO_ANCHOR.MIDDLE, paras=[
            {"t": a, "b": True, "s": 12, "c": NIGHT, "al": PP_ALIGN.CENTER},
            {"t": b, "b": True, "s": 15, "c": col, "al": PP_ALIGN.CENTER},
            {"t": c, "s": 10.5, "c": MUTED, "al": PP_ALIGN.CENTER}], space_after=2, margin=0.06)
        if k < 2:
            arrow(s, x + 1.8, 2.42, x + 1.98, 2.42, color=NIGHT, width=2)
    text(s, 7.05, 3.25, 5.8, 0.6, "Jour 3 : aucun article ne cite encore Rotterdam ni Stuttgart. Stock 0 j au port, "
         "20 j à l'usine ; Waal (30 %) n'est pas touché.", size=12, color=MUTED, italic=True)
    s.shapes.add_picture(str(FIGURES / "anticipation_plant_ecu_de.png"), Inches(7.05), Inches(3.95),
                         width=Inches(4.6))
    text(s, 11.75, 4.0, 1.1, 2.6, "Alerte au jour 2, premier article au jour 6", size=11, color=MUTED, italic=True)
    # barre de niveaux
    text(s, 0.5, 4.85, 6.2, 0.3, "Niveaux de risque", size=13, color=NIGHT, bold=True)
    segs = [("ok", 0.15, OK), ("à surveiller", 0.20, WATCH), ("alerte", 0.25, ALERT), ("critique", 0.40, CRIT)]
    x = 0.5
    for name, frac, col in segs:
        w = 6.2 * frac
        box(s, x, 5.2, w, 0.5, fill=col, line=None, radius=0.0, shape=MSO_SHAPE.RECTANGLE,
            paras=[{"t": name, "al": PP_ALIGN.CENTER}], size=12, bold=True,
            color=NIGHT if col == WATCH else WHITE, anchor=MSO_ANCHOR.MIDDLE, margin=0.02)
        x += w
    for v, xx in (("15 %", 0.5 + 6.2 * 0.15), ("35 %", 0.5 + 6.2 * 0.35), ("60 %", 0.5 + 6.2 * 0.60)):
        text(s, xx - 0.3, 5.73, 0.6, 0.3, v, size=11, color=MUTED, align=PP_ALIGN.CENTER, margin=0)
    box(s, 0.5, 6.1, 6.2, 0.6, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "Alerte émise à partir de 35 % · complexité O(N + E) · chemin dominant conservé"], size=12)


def _sim_chart(s, x, y, w, h):
    cats = ["Kaohsiung", "Rotterdam", "Stuttgart", "Onduleur RX", "Valenciennes", "E-City"]
    base = [0.23, 0.2185, 0.1211, 0.115, 0.1055, 0.1002]
    sim = [0.80, 0.76, 0.4212, 0.4001, 0.3668, 0.3485]
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series("État réel (jour 1)", [round(v * 100) for v in base])
    cd.add_series("Simulé : Kaohsiung à 80 %", [round(v * 100) for v in sim])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(11)
    ch.legend.font.color.rgb = rgb(TEXT)
    ch.has_title = True
    ch.chart_title.text_frame.text = "Risque total (%) : réel vs simulé"
    tp = ch.chart_title.text_frame.paragraphs[0]
    tp.runs[0].font.size = Pt(13)
    tp.runs[0].font.bold = True
    tp.runs[0].font.color.rgb = rgb(NIGHT)
    plot = ch.plots[0]
    plot.gap_width = 60
    plot.overlap = -10
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.font.size = Pt(10)
    dl.font.color.rgb = rgb(TEXT)
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    for ser, col in zip(plot.series, (LINE, CRIT)):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = rgb(col if col != LINE else "9FB3C8")
    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(11)
    ca.tick_labels.font.color.rgb = rgb(TEXT)
    ca.reverse_order = True
    ca.format.line.color.rgb = rgb(LINE)
    va = ch.value_axis
    va.maximum_scale = 100
    va.minimum_scale = 0
    va.has_major_gridlines = False
    va.visible = False


def slide_18():
    s = frame("Simulation what-if et plan de mitigation", 4,
              "src/graph/ontology_engine.py (simulate_disruption, alternative_suppliers, mitigation_plan) · "
              "tests/test_simulation.py · frontend/src/components/WhatIfPanel.tsx",
              """
    LA QUESTION MÉTIER
    « Que se passe-t-il si le port de Kaohsiung est bloqué à 80 % ? » La simulation répond sans attendre que la crise
    arrive, et sans jamais modifier l'état réel affiché.

    simulate_disruption(node_id, severity), PAS À PAS
    1. Vérifie que le nœud existe (_require) et que la gravité est dans [0, 1] (sinon ValueError → 404 / 422 côté API).
    2. COPIE le dictionnaire des risques directs de l'état courant (dict(self.current.direct)). On ne touche ni à
       self.current ni à self.events.
    3. direct[n] = max(direct actuel, gravité simulée) : la simulation ne peut qu'aggraver, jamais « réparer » un
       nœud déjà touché.
    4. Appelle propagate() sur cette copie (fonction pure) et l'indice global simulé.
    5. Impacts : nœuds dont le risque augmente de plus de 0,5 point, triés par écart décroissant ; produits finis
       menacés : ceux qui dépassent 15 % en simulé. Renvoie aussi l'état simulé complet (pour colorer le graphe) et
       le plan de mitigation.
    Les tests (tests/test_simulation.py, 8 tests) vérifient précisément : aucun effet sur l'état réel, monotonie
    (plus de gravité ⇒ plus de risque partout), alternatives, plan.

    LE GRAPHIQUE (valeurs réelles, jour 1)
    Au jour 1, l'indice global vaut 6,0 ; seule une prévision de rafales touche Kaohsiung (0,23). En simulant Kaohsiung
    bloqué à 80 % : Rotterdam passe de 0,22 à 0,76, Stuttgart de 0,12 à 0,42, les trois produits finis de 0,10 à 0,35
    environ ; l'indice simulé monte à 20,9. Trois produits finis sont menacés : l'onduleur RX, la citadine E-City et le
    SUV E-Trail. C'est exactement ce que le scénario confirmera au jour 3 : la simulation avait annoncé la crise.

    alternative_suppliers(node_id, depth=3)
    Parcours en largeur vers l'aval (jusqu'à 3 liens). Pour chaque client touché et l'intrant concerné, on cherche les
    autres sources du même intrant, actives (réserve = capacité − part actuelle) ou de secours (réserve = capacité).
    Exclusion essentielle : toute source qui dépend elle-même du nœud en panne (ensemble « tainted » = le nœud et tous
    ses descendants dans le graphe complet) n'est pas une alternative. Les alternatives sont triées par risque croissant
    puis réserve décroissante. Couverture = min(part à risque, Σ réserves) / part à risque.

    mitigation_plan(node_id)
    Quatre types d'actions, triées par type puis par délai : réallocation (augmenter une source active qui a de la
    réserve), route de secours (activer un lien backup), stock (usines en aval ayant du stock : geler les sorties non
    prioritaires), surveillance (suivre le nœud chaque jour et relancer la simulation). Exemple réel pour Kaohsiung :
    « Augmenter la part de Waal Semiconductors pour Rhein Power Modules : +20 % disponibles (part actuelle 30 %),
    délai 1 j » ; « Activer le secours Fret aérien Francfort : jusqu'à 25 % du besoin, délai 1 j » ; « Activer le
    secours Port of Keelung pour Rotterdam : jusqu'à 50 %, délai 32 j » ; « Rhein Power Modules : 20 j de stock... ».
    Le plan est déterministe et entièrement dérivé de la topologie : il ne propose jamais un fournisseur inexistant.

    CÔTÉ INTERFACE
    WhatIfPanel.tsx appelle POST /graph/simulate ; le bandeau de conseil et un clic sur un nœud (carte, graphe 2D, vue
    3D) présélectionnent le nœud à simuler.
    """)
    box(s, 0.5, 1.55, 6.0, 1.55, fill=ICE, line=None, paras=[
        {"t": "simulate_disruption(node, sévérité)", "b": True, "s": 14, "c": NIGHT, "f": MONO, "sa": 4},
        "- copie de `current.direct` : l'état réel n'est jamais modifié",
        "- `direct[node] = max(actuel, sévérité)` puis `propagate()`",
        "- impacts (Δ > 0,5 pt) · produits ≥ 15 % · plan de mitigation"], size=12, space_after=2)
    _sim_chart(s, 0.5, 3.2, 6.0, 3.5)
    text(s, 6.85, 1.5, 6.0, 0.35, "Plan de mitigation : Kaohsiung (sortie réelle)", size=15, color=NIGHT, bold=True)
    acts = [("réallocation", "Waal Semiconductors → Stuttgart : +20 % disponibles, délai 1 j", OK),
            ("route_secours", "Fret aérien Francfort → Stuttgart : jusqu'à 25 %, délai 1 j", CYAN_D),
            ("route_secours", "Port of Keelung → Rotterdam : jusqu'à 50 %, délai 32 j", CYAN_D),
            ("stock", "Stuttgart : 20 j de stock, réserver aux produits critiques", ALERT),
            ("surveillance", "suivre Kaohsiung chaque jour, relancer la simulation", MUTED)]
    for k, (kind, desc, col) in enumerate(acts):
        y = 1.95 + k * 0.72
        chip(s, 6.85, y + 0.12, kind, fill=col, color=WHITE, size=10.5, w=1.55)
        text(s, 8.55, y, 4.28, 0.65, desc, size=12, color=TEXT, margin=0, anchor=MSO_ANCHOR.MIDDLE)
    box(s, 6.85, 5.65, 5.98, 1.05, fill=SOFT, line=None, paras=[
        {"t": "Indice : 6,0 → 20,9 simulé · 3 produits finis menacés", "b": True, "s": 13, "c": NIGHT},
        "Alternatives : BFS aval (3 liens), sources dépendantes du nœud exclues (« tainted »)"], size=12,
        space_after=2)


# =========================================================================== bloc 5
def slide_19():
    s = frame("Les agents et le contrat BaseAgent", 5,
              "src/agents/base.py · src/agents/media_agent.py · src/agents/weather_agent.py · "
              "src/agents/finance_agent.py · tests/test_agents.py · tests/test_pipeline.py",
              """
    UN AGENT = TROIS MÉTHODES + UN RUN
    BaseAgent (classe abstraite, abc.ABC) impose : collect_live(report) → données brutes des derniers jours ;
    collect_replay(scenario, as_of, report) → données brutes d'un scénario, limitées à ce qui était connu à as_of ;
    extract_events(raw) → liste de NormalizedEvent. Ces trois fonctions restent indépendantes et modulaires : c'est la
    consigne de l'équipe pour qu'elles servent d'outils (« Tool Média ») à un futur orchestrateur. run() les enchaîne
    et applique le même contrat de réponse aux trois agents.

    LE PARAMÈTRE report
    Chaque collecte remplit un dictionnaire report avec l'état de chaque source : ok, partial, failed ou unavailable,
    plus des détails (nombre de requêtes, cache, cause d'échec). run() en déduit le statut :
    - mode inconnu, ou replay sans scénario → status error, error_type invalid_request ;
    - toutes les sources « unavailable » (paquet manquant) → error, source_unavailable ;
    - aucune source ok ou partial → error, network_failure, message : « Ce n'est pas une absence d'événement » ;
    - au moins une source non ok → success mais degraded = true, et le message le dit ;
    - sinon success ; si aucun événement : « Collecte réussie : aucun événement à signaler » (count = 0).
    Toute exception inattendue est rattrapée : error, internal_error, avec le type et le message. Un agent ne fait
    jamais tomber le pipeline (filet de sécurité large, assumé et journalisé avec log.exception).

    LA RÈGLE ZÉRO DÉMO
    collect_live ne renvoie jamais de données de scénario, même en cas de panne totale. S'il n'obtient rien, il renvoie
    une liste vide et le rapport dit pourquoi. Raison : un outil d'alerte qui afficherait des données de démonstration
    à la place de données réelles mentirait à l'utilisateur. Test associé : test_live_failure_is_an_error_never_demo_data.

    LES TROIS AGENTS
    - MediaAgent : GDELT + RSS (ou scénario) → MediaNLP (prétraitement, déduplication, entités, classification, LLM
      optionnel). Toute la chaîne bloquante tourne dans un thread.
    - WeatherAgent : Open-Meteo (ou scénario) → seuils. Événements meteo_extreme.
    - FinanceAgent : yfinance (ou scénario) → variation 5 séances et z-score. Événements tension_marche.
    Aucun ne calcule de gravité : séparation des responsabilités entre qualification (agents) et évaluation (moteur).

    ET L'« AGENT ONTOLOGIE / SYNTHÈSE » ?
    Il n'existe pas en tant qu'agent autonome. Son rôle est réparti entre trois composants déterministes : le moteur
    (fusion, corrélation, risque, alertes), le service (orchestration, validation croisée) et le Copilot (dialogue).
    Le mot « agent » désigne ici un composant de collecte spécialisé avec un contrat, pas un agent LLM qui planifie.
    L'architecture cible (encadré violet) décrit une version agentique étendue : un orchestrateur LLM qui appelle les
    outils média, météo et finance à la demande, un agent ontologie qui construit un graphe de connaissances commun à
    partir des trois bases nettoyées (plan de l'équipe), et un agent de veille quotidien.

    TESTS
    tests/test_agents.py (21 tests) : replay des trois agents, déduplication, règle zéro démo, distinction refus de site
    / panne réseau en RSS, GKG, LLM qui hallucine, replis. tests/test_pipeline.py (9 tests) : crise sur 7 jours, alerte
    précoce, absence de fuite du futur, pannes partielles et totales.
    """)
    code(s, 0.5, 1.55, 5.6, 2.7, [
        "class BaseAgent(ABC):",
        "  name: str",
        "  async def collect_live(report)",
        "  async def collect_replay(scenario, as_of, report)",
        "  async def extract_events(raw) -> list[NormalizedEvent]",
        "",
        "  async def run(mode, scenario, as_of) -> AgentResult:",
        "    # ne lève jamais d'exception"], size=11, title="src/agents/base.py")
    agents = [("MediaAgent", "GDELT + RSS → MediaNLP", MEDIA_BG, MEDIA),
              ("WeatherAgent", "Open-Meteo → seuils", WEATHER_BG, WEATHER),
              ("FinanceAgent", "yfinance → Δ5, z-score", FIN_BG, FIN)]
    for k, (a, b, bg, col) in enumerate(agents):
        x = 0.5 + k * 1.9
        box(s, x, 4.6, 1.75, 0.95, fill=bg, line=col, lw=1.5, anchor=MSO_ANCHOR.MIDDLE,
            paras=[{"t": a, "b": True, "s": 13, "al": PP_ALIGN.CENTER},
                   {"t": b, "s": 11, "c": MUTED, "al": PP_ALIGN.CENTER}], space_after=0, margin=0.06)
        arrow(s, x + 0.87, 4.6, x + 0.87, 4.25, color=col)
    text(s, 0.5, 5.8, 5.6, 0.85, "Aucun agent ne calcule de gravité. Règle zéro démo : le live ne renvoie jamais de "
         "données de scénario.", size=12, color=MUTED, italic=True)
    text(s, 6.45, 1.5, 6.4, 0.35, "run() : du rapport des sources au statut", size=15, color=NIGHT, bold=True)
    rows = [["Situation", "status", "error_type / drapeau"],
            ["mode inconnu, replay sans scénario", "error", "invalid_request"],
            ["toutes les sources « unavailable »", "error", "source_unavailable"],
            ["aucune source ok ou partial", "error", "network_failure"],
            ["au moins une source non ok", "success", "degraded = true"],
            ["tout ok, aucun événement", "success", "count = 0"],
            ["exception inattendue", "error", "internal_error"]]
    table(s, 6.45, 1.9, [3.0, 1.0, 2.38], rows, row_h=0.42, size=12, mono_cols=(1, 2))
    perspective(s, 6.45, 5.05, 6.38, 1.65, [
        "- orchestrateur LLM qui appelle les outils média / météo / finance à la demande",
        "- agent ontologie : graphe de connaissances commun construit par LLM (Ollama)",
        "- agent de veille quotidien qui rédige l'explication de chaque alerte"], size=12)


def slide_20():
    s = frame("Alertes expliquées et recoupement des sources", 5,
              "src/graph/ontology_engine.py (alerts, level_of, ALERT_THRESHOLD) · src/schemas/events.py (Alert) · "
              "frontend/src/components/EvidenceDrawer.tsx",
              """
    QUAND UNE ALERTE EST ÉMISE
    alerts() parcourt les nœuds de l'état courant : tout nœud dont le risque total atteint 35 % (ALERT_THRESHOLD)
    produit une alerte ; son niveau est warning (35–60 %) ou critical (≥ 60 %). Les nœuds entre 15 et 35 % sont
    « à surveiller » (info) mais ne produisent pas d'alerte.

    CE QUE CONTIENT UNE ALERTE (exemple réel, jour 3)
    ALR:plant_ecu_de, l'usine de Stuttgart : risque 0,52, direct 0, propagé 0,52. La règle est générée en clair :
    « Risque propagé 52 % depuis « Port of Kaohsiung » le long de 2 lien(s) ; risque direct 0 %. » Le chemin
    port_kaohsiung → port_rotterdam → plant_ecu_de explique pourquoi une usine que personne ne cite est en alerte. Les
    agents qui ont contribué le long du chemin : finance, médias, météo. Les signal_ids et les source_ids permettent de
    remonter jusqu'à chaque article, relevé et cotation. date = premier signal du chemin (14/09, le jour de la première
    prévision de typhon).

    LES DEUX FORMES DE RÈGLE
    - Risque propagé (le chemin a plus d'un nœud) : origine, nombre de liens, part propagée, part directe.
    - Risque direct : liste des familles de signaux du nœud, avec les agents qui les voient et la mention « corroboré »
      quand au moins deux agents concordent ; par exemple « climat (médias + météo, corroboré), opérations (médias) ».
    Le résumé (summary) reprend le nom du nœud, le risque et les deux libellés de signaux les plus contributifs.

    LA PRIORITÉ
    priorité = risque × (0,5 + 0,5 × criticité). Deux nœuds au même risque ne se valent pas : un fournisseur unique de
    puces (criticité 0,9) passe avant un port secondaire (0,4). Le facteur 0,5 garantit qu'un nœud peu critique mais
    très touché reste visible. Les alertes sont triées par priorité décroissante.

    LE RECOUPEMENT, RÉSUMÉ
    1. Validation croisée par le service (_cross_fill) : un événement médias reçoit les mesures météo et finance du même
       nœud à moins de 3 jours.
    2. Corrélation par le moteur : même nœud, même famille, ≤ 3 jours → un seul signal ; chaque agent supplémentaire
       ajoute 0,25 à la confiance ; corroborated = au moins 2 agents.
    3. Les liens élargis ne corroborent jamais un lien exact.
    Pourquoi c'est l'élément central de la fiabilité : un article isolé peut se tromper ; un article confirmé par un
    relevé météo et par un mouvement de marché indépendants est beaucoup plus probable. Le système rend ce
    raisonnement explicite et chiffré.

    CÔTÉ INTERFACE
    Le tiroir de preuves (EvidenceDrawer.tsx) affiche l'explication en clair, le chemin, les signaux, les preuves
    multi-sources (lien exact ou élargi ×0,40) et le JSON brut.

    LIMITE ET PERSPECTIVE
    L'explication est une règle générée par gabarit, pas un texte rédigé. L'architecture cible prévoit un LLM qui écrit
    deux phrases sourcées par alerte (« agent de veille »), contraint aux source_ids fournis.
    """)
    code(s, 0.5, 1.55, 7.2, 4.15, [
        '{"id": "ALR:plant_ecu_de",',
        ' "node_name": "Rhein Power Modules (Stuttgart)",',
        ' "level": "warning", "risk": 0.5157,',
        ' "direct": 0.0, "propagated": 0.5157,        #1',
        ' "priority": 0.4899,                          #2',
        ' "rule": "Risque propagé 52 % depuis',
        '   « Port of Kaohsiung » le long de 2 lien(s) ;',
        '   risque direct 0 %.",                       #3',
        ' "path": ["port_kaohsiung", "port_rotterdam",',
        '          "plant_ecu_de"],                    #4',
        ' "agents": ["finance", "media", "weather"],',
        ' "signal_ids": ["sig:port_kaohsiung:climat:1", ...],',
        ' "source_ids": ["replay:meteo:port_kaohsiung:...",',
        '   "replay:crisis_asia:004", ...],           #5',
        ' "date": "2026-09-14"}                        #6'], size=11,
         title="Alerte réelle · jour 3 · GET /alerts")
    formula(s, 0.5, 5.85, 7.2, 0.85, ["priorité = 0,5157 × (0,5 + 0,5 × 0,9) = 0,49"], size=16,
            label="Criticité de l'usine de Stuttgart : 0,9")
    ann = [("1", "aucun article ne cite l'usine : tout est propagé"),
           ("2", "priorité = risque × (0,5 + 0,5 × criticité)"),
           ("3", "règle générée en clair, lisible par l'acheteur"),
           ("4", "chemin dominant calculé par `propagate()`"),
           ("5", "preuves traçables jusqu'à la source"),
           ("6", "date du premier signal : la mesure de l'avance")]
    for k, (n, t) in enumerate(ann):
        y = 1.55 + k * 0.55
        num(s, 8.0, y + 0.03, n, d=0.36, fill=CODE_NOTE, color=NIGHT, size=12)
        text(s, 8.47, y, 4.36, 0.5, t, size=12, margin=0, anchor=MSO_ANCHOR.MIDDLE)
    box(s, 8.0, 4.95, 4.83, 1.75, fill=ICE, line=None, paras=[
        {"t": "Recoupement", "b": True, "s": 14, "c": NIGHT, "sa": 3},
        "- `_cross_fill` : météo / finance → événement médias",
        "- corrélation : +0,25 de confiance par agent",
        "- `corroborated` = au moins 2 agents",
        "- alerte ≥ 35 % · critique ≥ 60 %"], size=12, space_after=2)


def slide_21():
    s = frame("Copilot conversationnel ancré sur le graphe", 5,
              "src/copilot/assistant.py (TOOL_SPECS, SYSTEM_PROMPT, _chat_llm, route, parse_severity, render) · "
              "src/utils/llm.py (chat_with_tools) · src/graph/ontology_engine.py (resolve_node) · tests/test_copilot.py",
              """
    LE PRINCIPE : LE COPILOT NE SAIT RIEN PAR LUI-MÊME
    Il ne voit l'état de la chaîne qu'à travers 8 outils qui interrogent le moteur. Toute réponse est donc calculée par
    le moteur, puis formulée. C'est la principale défense contre l'hallucination dans un domaine où un chiffre inventé
    pourrait déclencher une mauvaise décision d'achat.

    LES 8 OUTILS (CopilotAssistant)
    etat_global (indice, nombre d'alertes, nœuds critiques), noeuds_exposes (top N), produits_menaces (produits finis
    ≥ 15 %), expliquer_alertes (règle, chemin, sources, pour un nœud ou les N premières), chemin_critique (chemin
    dominant et dépendances amont classées par « risque si panne totale »), fournisseurs_alternatifs, simuler_perturbation
    (gravité 0 à 1, sans modifier l'état réel), plan_mitigation. Chaque outil résout le nom de nœud demandé avec
    _resolve / resolve_node et renvoie un dictionnaire JSON.

    MODE LLM (USE_LLM=true et serveur joignable)
    Le prompt système fixe 6 règles : réponse en français, courte ; toujours appeler au moins un outil avant de
    répondre ; n'inventer aucun chiffre, fournisseur ni événement ; citer les source_ids et le chemin ; pour « que se
    passe-t-il si », appeler simuler_perturbation (« bloqué à 80 % » = 0,8, « fermeture » = 1,0) en précisant qu'une
    simulation ne change pas l'état réel ; demander une précision si le nœud est ambigu. Boucle _chat_llm : on envoie le
    prompt système, les 6 derniers messages d'historique et la question, avec les spécifications d'outils au format
    « function calling » ; tant que le modèle demande des outils, on les exécute et on lui renvoie les résultats (rôle
    tool) ; au plus 4 tours (MAX_TOOL_ROUNDS). Garde-fous en code : si le modèle répond sans avoir appelé un seul outil,
    la réponse est REJETÉE (LLMError « le modèle a répondu sans consulter le graphe ») ; réponse vide ou pas de réponse
    finale après 4 tours : rejet aussi. Tout rejet bascule sur le mode déterministe, avec une note. Le dernier nœud
    évoqué est gardé dans context.last_node_id pour les questions de suivi (« et ses alternatives ? »).

    MODE DÉTERMINISTE (par défaut, et repli)
    route() choisit un outil par expressions régulières sur la phrase normalisée, dans un ordre de priorité : simulation
    (« simul », « que se passe », « et si ») ; plan (« plan », « contourn », « que faire ») ; alternatives
    (« alternati », « remplac », « secours ») ; nœud nommé + « bloqué / fermé / grève » → simulation ; produits finis ;
    chemin / dépendances ; alertes / pourquoi / sources ; exposés / risque ; nœud seul → chemin critique ; sinon état
    global. parse_severity extrait la gravité : « 80 % » → 0,8 ; fermeture, arrêt complet, faillite → 1,0 ; blocage ou
    grève sans chiffre → 0,8 ; sinon 0,7. Si le nœud manque pour une simulation, le Copilot demande lequel au lieu de
    deviner. Les réponses sont mises en forme par des fonctions _render_* : chiffres et noms viennent tous de l'outil.

    resolve_node : TROUVER LE NŒUD DANS UNE PHRASE
    Les alias normalisés sont testés du plus long au plus court (« port of kaohsiung » avant « kaohsiung »), en mot
    entier, 4 caractères au moins. À défaut, tolérance aux fautes de frappe : difflib.get_close_matches sur les mots
    d'au moins 5 lettres, seuil 0,85 (« Rotterdm » → Rotterdam).

    POURQUOI DEUX MODES
    Le mode déterministe garantit une démo fiable sans GPU ni Ollama et sert de filet. Le mode LLM apporte la
    compréhension de questions libres et la combinaison de plusieurs outils. Les tests (19) couvrent le routage, les
    questions de démonstration, un LLM simulé qui appelle des outils, et les replis.
    """)
    tools = ["etat_global", "noeuds_exposes", "produits_menaces", "expliquer_alertes", "chemin_critique",
             "fournisseurs_alternatifs", "simuler_perturbation", "plan_mitigation"]
    text(s, 0.5, 1.5, 12.3, 0.35, "8 outils sur le moteur (seule source de vérité)", size=15, color=NIGHT, bold=True)
    for k, t in enumerate(tools):
        x = 0.5 + (k % 4) * 3.1
        y = 1.92 + (k // 4) * 0.45
        chip(s, x, y, t, fill=NIGHT, color=CYAN, size=11, w=2.95, h=0.36)
    # voie LLM
    box(s, 0.5, 3.0, 6.0, 3.7, fill=ICE, line=None)
    text(s, 0.7, 3.08, 5.6, 0.35, "Mode LLM : appel d'outils (Ollama)", size=14, color=NIGHT, bold=True)
    seq = ["prompt système + 6 messages + question", "le modèle demande des outils", "exécution → résultats (rôle tool)",
           "réponse finale (≤ 4 tours)"]
    for k, t in enumerate(seq):
        y = 3.55 + k * 0.62
        box(s, 0.75, y, 3.6, 0.46, fill=WHITE, line=CYAN_D, anchor=MSO_ANCHOR.MIDDLE, paras=[t], size=12)
        if k < 3:
            arrow(s, 2.55, y + 0.46, 2.55, y + 0.62, color=CYAN_D)
    arrow(s, 4.35, 4.48, 4.6, 4.48, color=CYAN_D, head=False)
    arrow(s, 4.6, 4.48, 4.6, 3.78, color=CYAN_D, head=False)
    arrow(s, 4.6, 3.78, 4.35, 3.78, color=CYAN_D)
    text(s, 4.65, 3.85, 1.75, 0.55, "boucle", size=11, color=CYAN_D, italic=True)
    box(s, 0.75, 6.05, 5.5, 0.5, fill="FDE8E8", line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "sans outil, vide ou > 4 tours → rejet → mode déterministe"], size=12)
    # voie règles
    box(s, 6.83, 3.0, 6.0, 3.7, fill=SOFT, line=None)
    text(s, 7.03, 3.08, 5.6, 0.35, "Mode déterministe (défaut et repli)", size=14, color=NIGHT, bold=True)
    text(s, 7.03, 3.5, 5.6, 2.2, [
        "- `route()` : regex dans un ordre de priorité (simulation › plan › alternatives › …)",
        "- `parse_severity` : « 80 % » → 0,8 · fermeture → 1,0 · grève → 0,8",
        "- `resolve_node` : alias le plus long, puis difflib ≥ 0,85",
        "- nœud ambigu → le Copilot demande une précision",
        "- `context.last_node_id` pour les questions de suivi"], size=12, space_after=4)
    code(s, 7.03, 5.75, 5.6, 0.8, [
        "« Fermeture de Rotterdam »",
        "→ simuler_perturbation(port_rotterdam, 1.0)"], size=11)


# =========================================================================== bloc 6
def slide_22():
    s = frame("Architecture du front-end React", 6,
              "frontend/package.json · vite.config.ts · src/main.tsx · App.tsx · store.tsx · api.ts · types.ts · "
              "components/Header.tsx, Dashboard.tsx, AdviceStrip.tsx, RiskChart.tsx, SignalTimeline.tsx",
              """
    LA STACK FRONT ET SES RAISONS
    React 18 (composants, écosystème de visualisation), TypeScript en mode strict (les types miroirs des schémas
    Pydantic attrapent les erreurs de forme à la compilation : npm run build lance tsc -b avant vite build), Vite 5
    (serveur de dev instantané avec rechargement à chaud, build Rollup optimisé, découpage du code), Tailwind CSS 3
    (styles utilitaires, palette pastel centralisée dans tailwind.config.js et theme.ts), Framer Motion (transitions
    entre vues, tiroir, bulle), Lucide (icônes). Pas de Redux : l'état est simple et tient dans un Context React.

    LE FLUX DE DONNÉES
    main.tsx monte <StoreProvider><App/></StoreProvider>. store.tsx contient tout l'état partagé : santé de l'API
    (apiDown), scénarios et topologies, mode live/replay, scénario, jour, topologie, option LLM, dernier run, état du
    graphe, alertes, événements, chargement, erreur, conversation du Copilot, cible du tiroir de preuves, nœud
    présélectionné pour le what-if, vue active. Au démarrage : Promise.all sur /health, /scenarios et /topologies ; si
    /health renvoie un last_run, le front recharge l'état existant sans relancer l'analyse. « Lancer l'analyse »
    appelle POST /pipeline/run puis, en parallèle, /graph/state, /alerts et /events. Une clé de run (mode + scénario ou
    topologie) détecte un changement de chaîne : la conversation du Copilot est alors vidée, pour qu'une réponse
    affichée décrive toujours l'état chargé.

    api.ts : UN SEUL POINT D'ENTRÉE HTTP
    http<T>() ajoute l'en-tête JSON, transforme une erreur réseau en ApiError(0, « API injoignable sur ... Lancez :
    uvicorn src.api.main:app --port 8000 ») et une erreur HTTP en ApiError(status, detail de FastAPI). L'URL vient de
    VITE_API_URL, par défaut http://localhost:8000.

    LES VUES
    1. Header : barre de pilotage (replay : scénario, curseur de jour, résumé narratif du jour ; live : topologie ; case
       LLM ; bouton ; état des trois sources).
    2. Tour de contrôle (Dashboard.tsx) : phrase de synthèse, bandeau de conseil, trois indicateurs, courbe de l'indice
       (RiskChart, « recalculé avec ce qui était connu chaque jour » en replay), chronologie des signaux
       (SignalTimeline : un cercle vide = article non rattaché), alertes prioritaires.
    3. Chaîne & simulation (ChainView.tsx) : graphe 2D, vue orbitale 3D, carte, tableau, panneau what-if (slide 23).
    4. Preuves & traçabilité (EvidenceDrawer.tsx) : tiroir latéral.
    Le compagnon Slime (Companion.tsx) est présent sur toutes les vues (slide 24).

    LE BANDEAU DE CONSEIL (AdviceStrip.tsx)
    Si l'API fournit un jour une recommandation, elle est affichée ; sinon, règles déterministes sur l'indice : moins
    de 20 → veille passive et test what-if du nœud le plus exposé ; 20 à 50 → source dominante et alternatives du
    maillon exposé ; plus de 50 → action prioritaire et produits finis à protéger. Bouton « Simuler ce nœud ».

    LE DÉCOUPAGE DU CODE
    MapView (MapLibre ≈ 1 Mo) et OrbitalGraph (three.js ≈ 1,5 Mo) sont importés avec React.lazy et Suspense : ils ne
    sont téléchargés qu'à l'ouverture de ces vues. Le bundle principal fait ≈ 350 Ko. vite.config.ts relève le seuil
    d'avertissement (chunkSizeWarningLimit 1600) pour ces deux morceaux connus.
    """)
    # arbre de composants
    box(s, 0.5, 1.55, 2.4, 0.55, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "main.tsx", "al": PP_ALIGN.CENTER, "f": MONO}], size=13, color=WHITE, bold=True)
    arrow(s, 1.7, 2.1, 1.7, 2.35, color=NIGHT)
    box(s, 0.5, 2.35, 2.4, 0.75, fill=ICE, line=CYAN_D, anchor=MSO_ANCHOR.MIDDLE, paras=[
        {"t": "StoreProvider", "b": True, "s": 13, "al": PP_ALIGN.CENTER, "f": MONO},
        {"t": "état global (Context)", "s": 11, "c": MUTED, "al": PP_ALIGN.CENTER}], space_after=0)
    arrow(s, 1.7, 3.1, 1.7, 3.35, color=NIGHT)
    box(s, 0.5, 3.35, 2.4, 0.55, fill=NIGHT, line=None, anchor=MSO_ANCHOR.MIDDLE,
        paras=[{"t": "App.tsx", "al": PP_ALIGN.CENTER, "f": MONO}], size=13, color=WHITE, bold=True)
    comps = [("Header", "pilotage live / replay"), ("Dashboard", "tour de contrôle"),
             ("ChainView", "graphes, carte, what-if"), ("EvidenceDrawer", "preuves"), ("Companion", "Slime + Copilot")]
    for k, (a, b) in enumerate(comps):
        y = 1.55 + k * 0.74
        box(s, 3.45, y, 2.75, 0.6, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
            {"t": a, "b": True, "s": 13, "f": MONO, "c": NIGHT}, {"t": b, "s": 11, "c": MUTED}], space_after=0)
        arrow(s, 2.9, 3.62, 3.45, y + 0.3, color=MUTED, width=1)
    box(s, 0.5, 4.2, 2.4, 1.15, fill=WHITE, line=LINE, paras=[
        {"t": "api.ts · types.ts", "b": True, "s": 12, "f": MONO, "c": NIGHT},
        {"t": "client typé, ApiError, miroir Pydantic", "s": 11, "c": MUTED}], space_after=2)
    # stack
    text(s, 6.6, 1.5, 6.2, 0.35, "Stack et justification", size=15, color=NIGHT, bold=True)
    stack = [("React 18 + TypeScript strict", "types miroirs des schémas Pydantic"),
             ("Vite 5", "dev instantané, build Rollup, découpage"),
             ("Tailwind CSS 3", "palette pastel centralisée"),
             ("Framer Motion · Lucide", "transitions, icônes"),
             ("maplibre-gl 5 · react-force-graph-3d", "chargés à la demande")]
    for k, (a, b) in enumerate(stack):
        y = 1.92 + k * 0.6
        text(s, 6.6, y, 3.4, 0.55, a, size=13, color=NIGHT, bold=True, margin=0, anchor=MSO_ANCHOR.MIDDLE)
        text(s, 10.0, y, 2.83, 0.55, b, size=12, color=MUTED, margin=0, anchor=MSO_ANCHOR.MIDDLE)
    # tailles de bundle
    text(s, 0.5, 5.55, 6, 0.3, "Bundles produits par `npm run build` (frontend/dist)", size=13, color=NIGHT, bold=True)
    for k, (v, l) in enumerate([("≈ 350 Ko", "bundle principal"), ("≈ 1,06 Mo", "MapView (lazy)"),
                                ("≈ 1,5 Mo", "OrbitalGraph (lazy)")]):
        x = 0.5 + k * 2.0
        text(s, x, 5.9, 1.9, 0.45, v, size=20, color=CYAN_D, bold=True, margin=0)
        text(s, x, 6.36, 1.9, 0.3, l, size=11, color=MUTED, margin=0)
    box(s, 6.6, 5.05, 6.23, 1.65, fill=ICE, line=None, paras=[
        {"t": "Bandeau de conseil (AdviceStrip.tsx)", "b": True, "s": 13, "c": NIGHT, "sa": 3},
        "- indice < 20 : veille, tester le nœud le plus exposé",
        "- 20 à 50 : source dominante et alternatives",
        "- > 50 : action prioritaire, produits finis à protéger"], size=12, space_after=2)


def slide_23():
    s = frame("Cartographie 2D/3D et vues du graphe", 6,
              "frontend/src/components/ChainView.tsx, OntologyGraph.tsx, OrbitalGraph.tsx, MapView.tsx, "
              "ChainTable.tsx, WhatIfPanel.tsx · src/clickGuard.ts · src/graphUtils.ts",
              """
    TROIS FAÇONS DE VOIR LA MÊME CHAÎNE
    ChainView.tsx regroupe un sélecteur de vue, le tableau (ChainTable : stocks, risque direct et propagé, chemin) et
    le panneau what-if. Les trois vues lisent le même GraphState et colorent les nœuds par niveau de risque.

    1. GRAPHE 2D EN COLONNES (OntologyGraph.tsx)
    Les nœuds sont placés en colonnes par rang (matières à gauche, produits finis à droite), comme le flux physique.
    C'est la vue la plus lisible pour suivre un chemin de propagation.

    2. VUE ORBITALE 3D (OrbitalGraph.tsx, react-force-graph-3d sur three.js)
    L'entreprise est au centre ; les nœuds sont placés sur des coquilles sphériques successives selon leur type
    (produits finis, usines, ports et hubs, puis fournisseurs et matières sur la coquille amont, rayon 270). Le
    placement est calculé (fonction layout), pas laissé à la simulation de forces, pour qu'il soit stable d'un rendu à
    l'autre ; chaque coquille a une rotation (twist) pour répartir les nœuds en volume. Les signaux actifs sont des
    satellites en orbite autour des maillons touchés. Les libellés HTML sont échappés (fonction esc) pour éviter toute
    injection via un nom de nœud.

    3. CARTE (MapView.tsx, MapLibre GL)
    MapLibre est la bibliothèque libre (fork de Mapbox GL v1) : pas de clé d'API ni de quota. Style gratuit Carto
    Positron (fond clair et neutre, qui laisse ressortir les couleurs de risque). Nœuds et liens sont ajoutés en
    couches GeoJSON (addLayer) ; un bouton bascule entre la projection plane (Mercator) et le globe 3D
    (setProjection({type: "globe"}), MapLibre 5). Hors ligne, ou si le style ne se charge pas, la carte bascule sur un
    fond uni avec les nœuds et les liens : la vue reste utilisable pendant une démo sans réseau.

    INTERACTIONS COMMUNES
    - clickGuard.ts : on mémorise la position du pointeur à l'appui ; si le relâchement est à plus de 4 px, c'est un
      glisser (déplacement de carte, rotation du globe ou de la sphère) et non un clic. Sans cela, chaque rotation
      sélectionnerait un nœud par erreur. Fonctionne pour souris, stylet et doigt.
    - Un clic sélectionne le nœud dans le panneau what-if et illumine sa propagation en aval : graphUtils.ts calcule
      downstream (parcours en largeur par les liens actifs, les secours ne propagent pas), propagationEdges (les liens à
      illuminer), productsDownstream (produits finis menacés) et alternativesFor (secours des clients directs). C'est
      la même logique que le moteur, recalculée côté client pour un retour visuel instantané, sans appel réseau.

    ÉCART AVEC LA DEMANDE INITIALE (encadré violet)
    Globe.gl n'est pas utilisé. Le globe est celui de MapLibre, et la 3D « graphe » est react-force-graph-3d. Globe.gl
    (three.js, arcs animés entre pays) serait une option pour visualiser des flux intercontinentaux en arcs ; la
    combinaison actuelle couvre déjà carte, globe et graphe 3D avec deux dépendances.
    """)
    cards = [("Graphe 2D en colonnes", "OntologyGraph.tsx",
              ["- colonnes par rang : matières → produits", "- vue la plus lisible pour suivre un chemin",
               "- couleur = niveau de risque"]),
             ("Vue orbitale 3D", "OrbitalGraph.tsx · react-force-graph-3d",
              ["- entreprise au centre, coquilles par type", "- placement calculé, stable (`layout`)",
               "- signaux en satellites sur les maillons touchés"]),
             ("Carte MapLibre GL", "MapView.tsx · Carto Positron",
              ["- couches GeoJSON nœuds + liens", "- bascule Mercator ↔ globe (`setProjection`)",
               "- hors ligne : fond uni, vue utilisable"])]
    for k, (a, b, items) in enumerate(cards):
        x = 0.5 + k * 4.16
        box(s, x, 1.55, 3.95, 2.75, fill=SOFT, line=None)
        num(s, x + 0.2, 1.72, k + 1)
        text(s, x + 0.75, 1.68, 3.1, 0.4, a, size=15, color=NIGHT, bold=True)
        text(s, x + 0.2, 2.2, 3.6, 0.35, b, size=11, color=CYAN_D, font=MONO)
        text(s, x + 0.2, 2.65, 3.6, 1.6, items, size=12, space_after=4)
    box(s, 0.5, 4.5, 6.0, 1.15, fill=ICE, line=None, paras=[
        {"t": "clickGuard.ts", "b": True, "s": 13, "c": NIGHT, "f": MONO},
        "relâchement à plus de 4 px de l'appui = glisser, pas clic : rotation sans sélection parasite"], size=12,
        space_after=2)
    box(s, 6.83, 4.5, 6.0, 1.15, fill=ICE, line=None, paras=[
        {"t": "graphUtils.ts", "b": True, "s": 13, "c": NIGHT, "f": MONO},
        "`downstream` (BFS, liens actifs) · `propagationEdges` · `productsDownstream` · `alternativesFor`"],
        size=12, space_after=2)
    text(s, 0.5, 5.75, 6.0, 0.9, "Un clic sur un nœud, dans n'importe quelle vue, le présélectionne dans le "
         "what-if et illumine sa propagation en aval, sans appel réseau.", size=12, color=MUTED, italic=True)
    perspective(s, 6.83, 5.8, 6.0, 0.9, [
        "Globe.gl (arcs animés entre pays) : non utilisé. Globe actuel = projection globe de MapLibre."], size=12)


def slide_24():
    s = frame("Le compagnon Slime, réactif aux états d'alerte", 6,
              "frontend/src/components/Companion.tsx · Slime.tsx · frontend/public/copilot/slime_*.png · "
              "scripts/prepare_copilot_sprites.py · frontend/sprites_src/",
              """
    POURQUOI UN COMPAGNON
    Un outil d'alerte est consulté en un coup d'œil. Le Slime donne l'état global sans lire de chiffre : sa couleur
    suit l'indice de risque, sa pose dit ce que fait le système. Il sert aussi d'avatar au Copilot, ce qui humanise la
    conversation sans ajouter d'élément décoratif gratuit. Il est ancré en bas à droite, immobile (aucun suivi du
    scroll, choix fait pour ne pas distraire).

    15 SPRITES = 3 COULEURS × 5 POSES (Slime.tsx)
    Couleur (slimeRiskFor) : calm (bleu) si l'indice est au niveau « ok », warning (jaune) au niveau « à surveiller »,
    critical (rouge) au niveau « alerte » ou « critique ». Les chemins sont de la forme
    copilot/slime_<couleur>_<pose>.png. Les 15 images sont préchargées au démarrage (new Image().src) : aucun
    clignotement quand la pose change.

    LA PRIORITÉ DES POSES (une machine à états simple)
    thinking > happy > sleepy > announce > idle.
    - thinking : un appel au Copilot ou une analyse est en cours ; affiché au moins 0,7 s (MIN_THINKING_MS) même si la
      réponse est plus rapide, pour que l'utilisateur perçoive le changement.
    - happy : pendant 4 s après une réponse réussie.
    - sleepy : après 2 minutes sans interaction (SLEEP_AFTER_MS = 120 000 ms), avec une respiration lente (scaleY 0,97
      ↔ 1 sur 4,5 s, classe CSS slime-breathe). Paramètre d'URL ?slimeSleep=10 pour le montrer en démo en 10 s. Bouger
      la souris le réveille.
    - announce : ouverture du Copilot (message d'accueil) ou conseil affiché dans la bulle.
    - idle : le reste du temps.
    La bulle de statut résume les alertes sérieuses (warning et critical) ; en veille : « zZ… je veille en silence ».

    LE CHAT (Companion.tsx)
    Questions rapides générées à partir de l'état (par exemple sur le port le plus critique, « Produits menacés »,
    « Plan de contournement ») ; historique des 8 derniers messages envoyés à /chat ; chaque réponse peut déplier les
    outils appelés et leur résultat JSON, ce qui montre l'ancrage dans le graphe.

    ACCESSIBILITÉ ET RENDU
    Chaque image a un texte alternatif (« Slime réfléchit, risque élevé »). Le pixel art est affiché avec
    image-rendering: pixelated : sans cela, le navigateur lisserait les pixels.

    LA FABRICATION DES SPRITES (scripts/prepare_copilot_sprites.py)
    À partir des planches dessinées (etats_slime, slime_situation_bleu / jaune / rouge) : retrait du fond blanc par
    flood-fill depuis les bords (on ne retire que le blanc connecté à l'extérieur, pas les reflets blancs du
    personnage), recadrage, retour à la grille native du pixel art, corps ramenés à la même largeur pour que le Slime
    ne bouge pas d'un pixel d'une pose à l'autre. Option --hd pour garder la pleine résolution. Les images de cette
    slide sont les vrais fichiers de frontend/public/copilot/, agrandis au plus proche voisin.
    """)
    risks = [("calm", "normal"), ("warning", "à surveiller"), ("critical", "alerte / critique")]
    poses = ["idle", "announce", "thinking", "happy", "sleepy"]
    for j, p in enumerate(poses):
        text(s, 2.0 + j * 1.25, 1.5, 1.2, 0.3, p, size=12, color=NIGHT, bold=True, align=PP_ALIGN.CENTER,
             font=MONO)
    for i, (r, lab) in enumerate(risks):
        y = 1.9 + i * 1.6
        text(s, 0.5, y + 0.35, 1.45, 0.75, [{"t": r, "b": True, "f": MONO, "c": NIGHT, "s": 13},
                                            {"t": lab, "s": 11, "c": MUTED}], space_after=0)
        for j, p in enumerate(poses):
            path = SPRITES / f"slime_{r}_{p}.png"
            x = 2.0 + j * 1.25
            box(s, x, y, 1.15, 1.42, fill=SOFT, line=None, radius=0.1)
            if path.exists():
                s.shapes.add_picture(pixel_image(path), Inches(x + 0.1), Inches(y + 0.3), width=Inches(0.95))
    box(s, 8.5, 1.55, 4.33, 2.3, fill=NIGHT, line=None, paras=[
        {"t": "Priorité des poses", "b": True, "s": 14, "c": WHITE, "sa": 4},
        {"t": "thinking › happy › sleepy › announce › idle", "s": 12, "c": CYAN, "f": MONO, "sa": 6},
        {"t": "- thinking : appel en cours, ≥ 0,7 s", "c": WHITE},
        {"t": "- happy : 4 s après une réponse", "c": WHITE},
        {"t": "- sleepy : 2 min sans interaction", "c": WHITE},
        {"t": "- announce : accueil ou conseil", "c": WHITE}], size=12, space_after=2, bullet_color=CYAN)
    box(s, 8.5, 4.0, 4.33, 1.25, fill=ICE, line=None, paras=[
        {"t": "Couleur = indice global", "b": True, "s": 13, "c": NIGHT},
        "ok → calm · à surveiller → warning · alerte ou critique → critical"], size=12, space_after=2)
    box(s, 8.5, 5.4, 4.33, 1.3, fill=SOFT, line=None, paras=[
        {"t": "prepare_copilot_sprites.py", "b": True, "s": 13, "c": NIGHT, "f": MONO},
        "flood-fill du fond blanc, recadrage, grille native, largeurs égalisées ; `image-rendering: pixelated`"],
        size=12, space_after=2)


def _tests_chart(s, x, y, w, h):
    files = [("ontology_engine", 18), ("schemas", 15), ("sectors", 15), ("agents", 21), ("final_adjustments", 22),
             ("copilot", 19), ("live_sources", 10), ("api", 10), ("pipeline", 9), ("simulation", 8),
             ("app_smoke", 8)]
    files.sort(key=lambda t: t[1])
    cd = CategoryChartData()
    cd.categories = [f for f, _ in files]
    cd.add_series("Tests", [n for _, n in files])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = True
    ch.chart_title.text_frame.text = "155 tests (tous verts)"
    r = ch.chart_title.text_frame.paragraphs[0].runs[0]
    r.font.size, r.font.bold = Pt(13), True
    r.font.color.rgb = rgb(NIGHT)
    plot = ch.plots[0]
    plot.gap_width = 45
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(10)
    plot.data_labels.font.color.rgb = rgb(TEXT)
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    ser = plot.series[0]
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = rgb(CYAN_D)
    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(10)
    ca.tick_labels.font.color.rgb = rgb(TEXT)
    ca.format.line.color.rgb = rgb(LINE)
    va = ch.value_axis
    va.has_major_gridlines = False
    va.visible = False
    va.maximum_scale = 26
    va.minimum_scale = 0


def slide_25():
    s = frame("Mécanismes transverses, tests et limites", 6,
              "app/common.py · tests/ (11 fichiers) · pytest.ini · README.md (Suite du travail) · "
              "scripts/export_soutenance.py · scripts/check_feeds.py",
              """
    LA GESTION DES ERREURS, COUCHE PAR COUCHE
    Le fil rouge du projet : une panne doit être visible comme une panne, jamais déguisée en « tout va bien ».
    1. HTTP (http_get) : pas d'exception, cause enregistrée (statut ou type d'erreur), nouvel essai seulement quand
       c'est utile (429, 5xx, réseau).
    2. Source : chaque source a un état ok / partial / failed / unavailable dans le rapport, avec un détail lisible ;
       les replis (cache GDELT, Google News, adresses RSS de rechange) sont signalés, pas cachés.
    3. Agent : run() ne lève jamais, statut success / error typé, drapeau degraded.
    4. Pipeline : un agent en panne → partial ; tous en panne → error et état précédent conservé.
    5. API : codes HTTP précis (404, 400, 422) ; le front affiche le detail de FastAPI.
    6. Front : ApiError(0) affiche la commande pour lancer l'API ; chaque vue lourde a un état de chargement ; la carte a
       un repli hors ligne. Streamlit (app/common.py) va plus loin : si l'API ne répond pas à /health en 1,5 s, il
       bascule sur un moteur embarqué dans son propre processus (même code, sans HTTP), indiqué dans la barre latérale.

    LIVE ET REPLAY
    Même code, mêmes agents, même moteur ; seule la source des données brutes change. Replay : scénario JSON daté
    (fictif et annoncé comme tel), jour choisi au curseur, aucune fuite du futur, LLM seulement pour le jour affiché,
    topologie imposée par le scénario. Live : GDELT, RSS, Open-Meteo, Yahoo Finance sur 7 jours, topologie choisie,
    rattachement élargi activé, jamais de données de démonstration. Relevé du 16/11/2026 sur un poste personnel :
    rss, gdelt, open_meteo et yfinance répondent tous « ok », 19 événements réels remontent.

    LES TESTS (vérifiés le 20/11/2026)
    155 tests collectés par pytest (136 fonctions, certaines paramétrées), répartis en 11 fichiers ; tous passent.
    Ils n'appellent ni Internet ni Ollama : les réponses de GDELT, d'Open-Meteo et du LLM sont simulées (monkeypatch).
    Les tests ont un rôle de spécification : « pas de fuite du futur », « le LLM qui hallucine est corrigé », « la
    simulation ne modifie pas l'état réel » sont écrits comme des tests. Note pratique : selon l'environnement, des
    tests RSS échouent si feedparser n'est pas installé (le statut devient « unavailable » au lieu de « failed ») ;
    il faut installer tout requirements.txt avant de lancer pytest.

    LES LIMITES DU PROTOTYPE, À DIRE AVANT QU'ON LES DEMANDE
    - Données : fournisseurs et scénarios simulés ; l'avance de 4 jours vient d'un scénario écrit pour la démo.
    - Calibration : constantes du moteur et seuils météo / finance posés par expertise, non calibrés.
    - Backtesting réel non fait : Nexperia, ouragan Helene, grève des ports, terres rares (la brique GKG existe).
    - NLP : baseline à 64 phrases d'amorçage, pas d'évaluation F1 ; pas de BERT / XLM-R / zero-shot.
    - LLM sur CPU trop lent pour le délai de 15 s : repli fréquent.
    - Persistance en mémoire, pas d'historique ni de multi-utilisateur.
    - Propagation : maillon le plus faible par nœud, une usine transmet à tous ses produits.

    LA SUITE (README, « Suite du travail »)
    1. Observer en live les rattachements élargis et ajuster les keywords. 2. Tester copilot et extraction avec un vrai
    serveur Ollama (GPU). 3. Remplacer la topologie simulée par celle du Bloc 4 et ajouter les codes LEI. 4. Écrire des
    scénarios à partir de crises réelles (GKG) et mesurer avance et fausses alertes. 5. Calibrer les constantes. 6.
    Annoter des articles (le classifieur les utilise dès 20).
    """)
    rows = [["Couche", "Comportement en cas de panne"],
            ["http_get", "jamais d'exception, cause enregistrée"],
            ["source", "ok / partial / failed / unavailable"],
            ["agent", "error typé, `degraded`, jamais de démo"],
            ["pipeline", "partial ; tout KO → état conservé"],
            ["API", "404 · 400 · 422 + detail"],
            ["front", "ApiError(0), repli carte, moteur embarqué"]]
    table(s, 0.5, 1.55, [1.15, 3.05], rows, row_h=0.42, size=12, first_col_bold=True)
    rows = [["", "Replay", "Live"],
            ["données", "scénario JSON daté", "GDELT, RSS, météo, marchés"],
            ["topologie", "fixée par le scénario", "choisie (sélecteur)"],
            ["LLM", "jour affiché seulement", "si activé"],
            ["élargi", "non", "oui (défaut)"]]
    table(s, 4.95, 1.55, [1.0, 1.65, 1.95], rows, row_h=0.42, size=11)
    _tests_chart(s, 9.85, 1.45, 3.0, 3.45)
    box(s, 4.95, 3.9, 4.6, 0.95, fill=SOFT, line=None, anchor=MSO_ANCHOR.MIDDLE, paras=[
        "Tests sans Internet ni Ollama : réponses GDELT, Open-Meteo et LLM simulées · 136 fonctions → 155 cas"],
        size=12)
    box(s, 0.5, 5.05, 6.0, 1.65, fill="FDE8E8", line=None, paras=[
        {"t": "Limites actuelles", "b": True, "s": 14, "c": CRIT, "sa": 3},
        "- fournisseurs et scénarios simulés ; constantes non calibrées",
        "- pas de backtesting réel (Nexperia, Helene, ports, terres rares)",
        "- baseline NLP non évaluée ; LLM trop lent sur CPU"], size=12, space_after=2, bullet_color=CRIT)
    perspective(s, 6.83, 5.05, 6.0, 1.65, [
        "- backtesting GKG et mesure de l'avance et des fausses alertes",
        "- calibration des constantes · topologie réelle du Bloc 4 + LEI",
        "- deep learning / zero-shot · historisation en base"], size=12)


# =========================================================================== assemblage
def main() -> None:
    for build in (slide_01, slide_02, slide_03, slide_04, slide_05, slide_06, slide_07, slide_08, slide_09,
                  slide_10, slide_11, slide_12, slide_13, slide_14, slide_15, slide_16, slide_17, slide_18,
                  slide_19, slide_20, slide_21, slide_22, slide_23, slide_24, slide_25):
        build()
    assert len(prs.slides) == TOTAL, f"{len(prs.slides)} slides au lieu de {TOTAL}"
    prs.core_properties.title = "A.E.G.I.S. : architecture technique complète"
    prs.core_properties.author = "Équipe A.E.G.I.S. (Master Project INGE3 n°6)"
    prs.save(OUTPUT)
    print(f"Présentation écrite : {OUTPUT} ({TOTAL} slides)")


if __name__ == "__main__":
    main()
