"""Génère presentation_non_technique.pptx : la présentation A.E.G.I.S. pour un public non technique.

19 slides, palette bleu nuit / cyan / blanc, discours oral complet dans les notes du présentateur.
Fil rouge : Claire, acheteuse chez Novalys (entreprise fictive de data/topology.yaml),
pendant les 7 jours du scénario de replay crisis_asia_semiconductors.

Usage (depuis la racine du projet) :
    pip install python-pptx pillow
    python scripts/generate_presentation_non_technique.py

Images reprises du dépôt si elles existent :
    docs/figures/anticipation_plant_ecu_de.png   (slide 13 ; produite par scripts/export_soutenance.py)
    frontend/public/copilot/slime_*.png          (compagnon Slime, slides 8, 12 et 13)
"""

from io import BytesIO
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "presentation_non_technique.pptx"
FIGURE = ROOT / "docs" / "figures" / "anticipation_plant_ecu_de.png"
SPRITES = ROOT / "frontend" / "public" / "copilot"

# ---------------------------------------------------------------- palette
NIGHT = "0B1F3A"   # bleu nuit : fonds sombres, titres
NAVY = "13294B"    # cartes sur fond sombre
NAVY2 = "2A4A72"   # traits et nœuds secondaires
CYAN = "00B4D8"    # accent principal
CYAN_D = "0284A8"  # cyan lisible sur fond blanc (petits textes)
ICE = "E6F7FB"     # teinte cyan très claire (cartes, analogies)
ICE2 = "BDEBF5"
WHITE = "FFFFFF"
TEXT = "334155"
MUTED = "64748B"
MUTED_DARK = "8FA3BF"  # texte discret sur fond sombre
LINE = "D5DEE8"
SOFT = "F2F5F9"
# niveaux de risque, utilisés avec parcimonie
WATCH = "F2C14E"
ALERT = "F08A4B"
CRIT = "D64545"

FONT = "Calibri"
W, H = 13.333, 7.5
TOTAL = 19
ACRONYM = "Automated Early-warning & Graph Intelligence for Supply-chain"

prs = Presentation()
prs.slide_width = Inches(W)
prs.slide_height = Inches(H)
BLANK = prs.slide_layouts[6]


# ---------------------------------------------------------------- utilitaires
def rgb(h):
    return RGBColor.from_string(h)


def _drop_style(shape):
    """Retire le style par défaut (ombre, contour de thème) des formes python-pptx."""
    st = shape._element.find(qn("p:style"))
    if st is not None:
        shape._element.remove(st)


def shape(slide, kind, x, y, w, h, fill=None, line=None, line_w=1.0, radius=None, rot=0, name=None):
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    _drop_style(s)
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(line_w)
    else:
        s.line.fill.background()
    if radius is not None:
        s.adjustments[0] = radius
    if rot:
        s.rotation = rot
    if name:
        s.name = name
    return s


def rect(slide, x, y, w, h, fill=None, line=None, **kw):
    return shape(slide, MSO_SHAPE.RECTANGLE, x, y, w, h, fill, line, **kw)


def card(slide, x, y, w, h, fill=SOFT, line=None, radius=0.08, **kw):
    return shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill, line, radius=radius, **kw)


def circle(slide, cx, cy, d, fill=None, line=None, line_w=1.0):
    return shape(slide, MSO_SHAPE.OVAL, cx - d / 2, cy - d / 2, d, d, fill, line, line_w)


def _style_run(run, size, color, bold, italic, font, spacing):
    f = run.font
    f.name = font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = rgb(color)
    if spacing:
        f._rPr.set("spc", str(spacing))


def text(slide, x, y, w, h, paras, size=16, color=TEXT, bold=False, italic=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, font=FONT, spacing=None, space_after=0, line_spacing=None, target=None, name=None):
    """Zone de texte. `paras` : chaîne, ou liste de paragraphes ; un paragraphe est une chaîne
    ou une liste de runs (texte, {options}) avec les options size, color, bold, italic, spacing."""
    if target is None:
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        if name:
            tb.name = name
    else:
        tb = target
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(paras, str):
        paras = [paras]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if space_after:
            p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        runs = [(para, {})] if isinstance(para, str) else para
        for txt, opt in runs:
            r = p.add_run()
            r.text = txt
            _style_run(r, opt.get("size", size), opt.get("color", color), opt.get("bold", bold),
                       opt.get("italic", italic), font, opt.get("spacing", spacing))
    return tb


def label_in(shp, txt, size=14, color=WHITE, bold=True, align=PP_ALIGN.CENTER, italic=False, margin=0.05):
    """Écrit un texte centré dans une forme."""
    text(None, 0, 0, 0, 0, txt, size=size, color=color, bold=bold, italic=italic, align=align,
         anchor=MSO_ANCHOR.MIDDLE, target=shp)
    tf = shp.text_frame
    tf.margin_left = tf.margin_right = Inches(margin)
    return shp


def connector(slide, x1, y1, x2, y2, color=NAVY2, width=1.5, arrow=False, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    _drop_style(c)
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(width)
    if dash:
        c.line.dash_style = MSO_LINE.DASH
    if arrow:
        ln = c.line._get_or_add_ln()
        tail = etree.SubElement(ln, qn("a:tailEnd"))
        tail.set("type", "triangle")
        tail.set("w", "med")
        tail.set("len", "med")
    return c


def sprite(name, scale=8):
    """Agrandit un sprite pixel art sans le flouter (plus proche voisin)."""
    path = SPRITES / name
    if not path.exists():
        return None
    im = Image.open(path).convert("RGBA")
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    buf = BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf, im.width / im.height


def add_sprite(slide, name, x, y, w):
    res = sprite(name)
    if res is None:
        return None
    buf, ratio = res
    return slide.shapes.add_picture(buf, Inches(x), Inches(y), Inches(w), Inches(w / ratio))


# ---------------------------------------------------------------- icônes dessinées (blanc sur pastille cyan)
def icon_badge(slide, cx, cy, d=0.7, kind="doc", bg=CYAN, fg=WHITE):
    circle(slide, cx, cy, d, fill=bg)
    s = d * 0.5
    if kind == "doc":
        shape(slide, MSO_SHAPE.FOLDED_CORNER, cx - s * 0.38, cy - s * 0.5, s * 0.76, s, fill=fg)
    elif kind == "cloud":
        shape(slide, MSO_SHAPE.CLOUD, cx - s * 0.6, cy - s * 0.4, s * 1.2, s * 0.8, fill=fg)
    elif kind == "bars":
        for i, hh in enumerate((0.45, 0.75, 1.0)):
            rect(slide, cx - s * 0.5 + i * s * 0.36, cy + s * 0.5 - s * hh, s * 0.26, s * hh, fill=fg)
    elif kind == "map":
        pts = [(-0.45, 0.3), (0.0, -0.4), (0.45, 0.25)]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            connector(slide, cx + ax * s, cy + ay * s, cx + bx * s, cy + by * s, color=fg, width=1.75)
        for px, py in pts:
            circle(slide, cx + px * s, cy + py * s, s * 0.34, fill=fg)
    elif kind == "gear":
        shape(slide, MSO_SHAPE.GEAR_6, cx - s * 0.5, cy - s * 0.5, s, s, fill=fg)
    elif kind == "bolt":
        shape(slide, MSO_SHAPE.LIGHTNING_BOLT, cx - s * 0.42, cy - s * 0.5, s * 0.84, s, fill=fg)
    elif kind == "arrow":
        shape(slide, MSO_SHAPE.RIGHT_ARROW, cx - s * 0.55, cy - s * 0.35, s * 1.1, s * 0.7, fill=fg)
    elif kind == "loop":
        shape(slide, MSO_SHAPE.CIRCULAR_ARROW, cx - s * 0.55, cy - s * 0.55, s * 1.1, s * 1.1, fill=fg)
    elif kind == "bubble":
        shape(slide, MSO_SHAPE.ROUNDED_RECTANGULAR_CALLOUT, cx - s * 0.55, cy - s * 0.45, s * 1.1, s * 0.8, fill=fg)
    elif kind == "check":
        shape(slide, MSO_SHAPE.FLOWCHART_CONNECTOR, cx - s * 0.18, cy - s * 0.18, s * 0.36, s * 0.36, fill=fg)
    elif kind == "layers":
        for i in range(3):
            card(slide, cx - s * 0.5, cy - s * 0.5 + i * s * 0.34, s, s * 0.26, fill=fg, radius=0.3)
    elif kind == "plug":
        circle(slide, cx, cy, s * 0.9, line=fg, line_w=2)
        connector(slide, cx - s * 0.32, cy + s * 0.32, cx + s * 0.32, cy - s * 0.32, color=fg, width=2)
    elif kind == "letter":
        pass
    return None


# ---------------------------------------------------------------- cadre commun
def background(slide, color):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(color)


def day_tracker(slide, day, dark=False):
    """Repère J1…J7 du scénario, en haut à droite."""
    x0, y = 9.55, 0.46
    text(slide, x0 - 1.95, y - 0.12, 1.55, 0.26, "Scénario typhon", size=11, color=MUTED, align=PP_ALIGN.RIGHT)
    for i in range(1, 8):
        cx = x0 + (i - 1) * 0.47
        if i == day:
            c = circle(slide, cx, y, 0.38, fill=CYAN)
            label_in(c, f"J{i}", size=10, color=WHITE)
        elif i < day:
            c = circle(slide, cx, y, 0.32, fill=NAVY2)
            label_in(c, f"J{i}", size=9, color=WHITE, bold=False)
        else:
            c = circle(slide, cx, y, 0.32, fill=WHITE, line=LINE, line_w=1.25)
            label_in(c, f"J{i}", size=9, color=MUTED, bold=False)


def analogy(slide, txt, dark=False):
    """Motif récurrent : la pastille « analogie » en bas de chaque slide."""
    fill = NAVY if dark else ICE
    pill = card(slide, 0.6, 6.2, 10.6, 0.58, fill=fill, radius=0.5, name="Analogie")
    c = circle(slide, 0.6 + 0.31, 6.49, 0.4, fill=CYAN)
    label_in(c, "≈", size=16, color=WHITE)
    text(slide, 1.25, 6.2, 9.8, 0.58,
         [[("Analogie  ", {"bold": True, "color": CYAN if dark else CYAN_D, "italic": False}),
           (txt, {"italic": True, "color": WHITE if dark else NIGHT})]],
         size=15, anchor=MSO_ANCHOR.MIDDLE)
    return pill


def footer(slide, num, dark=False):
    col = MUTED_DARK if dark else MUTED
    text(slide, 0.6, 7.0, 9.0, 0.25,
         [[("A.E.G.I.S.", {"bold": True}), (f"  ·  {ACRONYM}", {})]], size=10, color=col)
    text(slide, 11.73, 7.0, 1.0, 0.25, f"{num} / {TOTAL}", size=10, color=col, align=PP_ALIGN.RIGHT)


def frame(num, kicker, title, analogy_txt, notes, day=None, dark=False):
    s = prs.slides.add_slide(BLANK)
    background(s, NIGHT if dark else WHITE)
    text(s, 0.6, 0.34, 7.5, 0.3, kicker.upper(), size=12, bold=True, color=CYAN if dark else CYAN_D, spacing=150)
    text(s, 0.6, 0.72, 12.1, 1.05, title, size=30, bold=True, color=WHITE if dark else NIGHT, name="Titre")
    if day:
        day_tracker(s, day, dark)
    if analogy_txt:
        analogy(s, analogy_txt, dark)
    footer(s, num, dark)
    s.notes_slide.notes_text_frame.text = notes.strip()
    return s


def dot_rows(slide, x, y, w, items, size=15, color=TEXT, dot=CYAN, gap=0.12, row_h=0.62):
    """Liste aérée : une pastille + un texte par ligne (pas de puces texte)."""
    for i, it in enumerate(items):
        yy = y + i * (row_h + gap)
        circle(slide, x + 0.09, yy + 0.16, 0.16, fill=dot)
        text(slide, x + 0.32, yy, w - 0.32, row_h, it, size=size, color=color)


def stat(slide, x, y, w, big, small, big_color=CYAN_D, small_color=TEXT, big_size=40, small_size=14):
    text(slide, x, y, w, 0.7, big, size=big_size, bold=True, color=big_color)
    text(slide, x, y + 0.72, w, 0.6, small, size=small_size, color=small_color)


# ================================================================ SLIDES

# ---------------------------------------------------------------- 1. Couverture
s = prs.slides.add_slide(BLANK)
background(s, NIGHT)
# réseau stylisé + anneau protecteur (l'égide)
C = (10.2, 3.75)
mid = [(8.9, 2.6), (11.6, 2.4), (11.9, 4.6), (9.0, 5.0), (10.3, 1.75)]
outer = [((8.9, 2.6), (7.75, 1.4)), ((11.6, 2.4), (12.55, 1.2)), ((11.9, 4.6), (12.7, 6.0)),
         ((9.0, 5.0), (8.0, 6.3)), ((10.3, 1.75), (10.4, 0.6)), ((9.0, 5.0), (10.0, 6.85))]
circle(s, C[0], C[1], 4.6, line=CYAN, line_w=1.5)
for m in mid:
    connector(s, C[0], C[1], m[0], m[1], color=NAVY2, width=1.5)
for a, b in outer:
    hot = b == (12.55, 1.2)
    connector(s, a[0], a[1], b[0], b[1], color=CYAN if hot else NAVY2, width=2 if hot else 1.25)
connector(s, C[0], C[1], 11.6, 2.4, color=CYAN, width=2)
for m in mid:
    circle(s, m[0], m[1], 0.26, fill=CYAN if m == (11.6, 2.4) else NAVY2)
for _, b in outer:
    circle(s, b[0], b[1], 0.2, fill=ALERT if b == (12.55, 1.2) else NAVY2)
circle(s, C[0], C[1], 0.62, fill=CYAN)
circle(s, C[0], C[1], 0.3, fill=WHITE)

text(s, 0.8, 1.35, 7.0, 0.3, "PROJET DE FIN D'ÉTUDES  ·  INGE3 N°6", size=13, bold=True, color=CYAN, spacing=200)
text(s, 0.8, 1.85, 7.0, 1.3, "A.E.G.I.S.", size=72, bold=True, color=WHITE, spacing=300)
text(s, 0.8, 3.2, 6.6, 0.8, ACRONYM, size=18, color=ICE2)
text(s, 0.8, 4.2, 6.6, 1.3, "Voir la crise avant qu'elle n'arrête l'usine", size=30, bold=True, color=WHITE)
text(s, 0.8, 6.55, 6.6, 0.3, "ESME  ·  Ingé 3  ·  2026-2027", size=12, color=MUTED_DARK)
text(s, 0.8, 5.65, 6.6, 0.4,
     [[("Analogie  ", {"bold": True, "color": CYAN, "italic": False}),
       ("l'égide, le bouclier d'Athéna : on se protège avant le coup.", {"italic": True})]],
     size=15, color=ICE2)
s.notes_slide.notes_text_frame.text = """
[Ton posé. Laisser le titre s'afficher deux secondes avant de parler.]

Bonjour à toutes et à tous. Je vous présente A.E.G.I.S., pour « Automated Early-warning & Graph Intelligence for Supply-chain ». En français : un système d'alerte précoce pour les chaînes d'approvisionnement.

Le nom n'est pas choisi au hasard. Dans la mythologie grecque, l'égide est le bouclier d'Athéna, la déesse de la sagesse et de la stratégie. Un bouclier ne sert à rien une fois qu'on a été frappé : il sert parce qu'on le lève avant le coup. C'est exactement l'idée de notre projet.

Notre promesse tient en une phrase : voir la crise avant qu'elle n'arrête l'usine.

Pendant les quinze prochaines minutes, je vais vous raconter une histoire. Celle d'un problème bien réel qui coûte très cher aux industriels, puis celle de Claire, une acheteuse, qui va vivre une crise jour après jour avec notre outil à ses côtés. Vous n'aurez besoin d'aucune connaissance technique pour suivre : si je fais bien mon travail, vous comprendrez comment ça marche sans que je prononce un seul mot de jargon.

[Transition] Commençons par une histoire vraie, qui s'est déroulée il y a tout juste un an.
"""

# ---------------------------------------------------------------- 2. Nexperia
s = frame(2, "Acte 1  ·  Le problème", "Une puce à quelques centimes peut arrêter une usine entière",
          "un grain de sable suffit à bloquer tout l'engrenage.", """
Automne 2025. Nexperia, un fabricant de puces électroniques très simples, vendues quelques centimes pièce. Le genre de composant que personne ne regarde, mais qu'on retrouve dans toutes les voitures.

Le 29 septembre, les États-Unis durcissent leurs règles contre la maison mère chinoise de Nexperia. Quelques jours plus tard, le 4 octobre, la Chine riposte et bloque l'export des puces fabriquées dans ses usines Nexperia. Le 10 octobre, Nexperia prévient ses clients : elle ne garantit plus ses livraisons.

Et le 27 octobre, Honda réduit de moitié la production de son usine d'Alliston, au Canada. Faute de puces à quelques centimes, des voitures à plusieurs dizaines de milliers d'euros ne sortent plus de la chaîne.

[Pointer le grand chiffre] Entre le premier signal public et l'arrêt de l'usine : 28 jours. Presque un mois.

Le point essentiel, c'est que tout était écrit dans la presse. Les informations existaient, elles étaient publiques. Ce qui a manqué, ce n'est pas l'information, c'est quelqu'un, ou quelque chose, pour faire le lien entre une décision politique à Washington et une ligne de production au Canada.

C'est le grain de sable dans l'engrenage : une pièce minuscule, et toute la machine s'arrête.

[Transition] Pourquoi ce lien est-il si difficile à faire ? Parce que le danger se cache là où personne ne regarde.
""")
text(s, 0.6, 1.95, 4.4, 1.9, "28", size=130, bold=True, color="0096C7")
text(s, 0.6, 3.85, 4.4, 0.6, "jours", size=32, bold=True, color=NIGHT)
text(s, 0.6, 4.5, 4.2, 1.2, "entre le premier signal public et l'arrêt partiel d'une usine Honda", size=16, color=TEXT)
events = [
    ("29 sept. 2025", "Les États-Unis durcissent leurs règles contre la maison mère de Nexperia", CYAN),
    ("4 oct. 2025", "La Chine bloque l'export des puces Nexperia fabriquées sur son sol", CYAN),
    ("10 oct. 2025", "Nexperia ne garantit plus ses livraisons", WATCH),
    ("27 oct. 2025", "Honda réduit de moitié la production à Alliston (Canada)", CRIT),
]
xs = [5.6, 7.45, 9.3, 11.15]
connector(s, 5.6, 2.75, 11.15, 2.75, color=LINE, width=2.5)
for (d, t, col), x in zip(events, xs):
    circle(s, x, 2.75, 0.34, fill=col)
    text(s, x - 0.12, 2.05, 1.75, 0.35, d, size=14, bold=True, color=NIGHT)
    text(s, x - 0.12, 3.15, 1.62, 2.2, t, size=14, color=TEXT)
text(s, 5.48, 5.35, 7.2, 0.5, "Le signal existait. Personne ne l'a relié à temps.", size=18, bold=True, italic=True,
     color=CYAN_D)

# ---------------------------------------------------------------- 3. Iceberg
s = frame(3, "Acte 1  ·  Le problème", "On ne voit que ses fournisseurs directs",
          "l'iceberg : on voit la pointe, le danger est sous l'eau.", """
Quand on demande à une entreprise industrielle qui sont ses fournisseurs, elle sait répondre. Ce sont ses fournisseurs directs, ceux à qui elle envoie des bons de commande. On les appelle le « rang 1 ».

Mais ces fournisseurs ont eux-mêmes des fournisseurs : c'est le rang 2. Qui ont à leur tour des fournisseurs : le rang 3. Et c'est là, dans ces étages invisibles, que naissent la plupart des crises.

[Pointer l'exemple à droite] Prenons Novalys, l'entreprise que nous allons suivre. Novalys achète des modules électroniques à une usine de Stuttgart : ça, elle le voit. Ces modules contiennent des puces fabriquées à Tainan, à Taïwan : rang 2, beaucoup moins visible. Et ces puces sont gravées sur des plaquettes de silicium produites à Hsinchu : rang 3, totalement invisible au quotidien.

Si une tempête frappe Hsinchu, personne chez Novalys ne fera le lien. Pour eux, le problème n'existera que le jour où l'usine de Stuttgart appellera pour dire : « on ne peut plus vous livrer ». Et ce jour-là, il est souvent trop tard pour réagir sereinement.

C'est l'image de l'iceberg : la pointe émergée, ce sont vos fournisseurs directs. La masse sous l'eau, celle qui coule les navires, ce sont les fournisseurs de vos fournisseurs.

[Transition] Et même si on voulait regarder sous l'eau, il y a un deuxième obstacle : la quantité d'information à surveiller.
""")
# iceberg
connector(s, 0.6, 3.05, 6.4, 3.05, color=CYAN, width=2, dash=True)
shape(s, MSO_SHAPE.ISOSCELES_TRIANGLE, 2.6, 2.0, 2.0, 1.05, fill=ICE2)
shape(s, MSO_SHAPE.ISOSCELES_TRIANGLE, 1.0, 3.05, 5.2, 2.9, fill=NAVY2, rot=180)
text(s, 4.55, 2.15, 2.0, 0.6, [[("Rang 1", {"bold": True, "color": NIGHT})], "ce que l'on voit"], size=14,
     color=TEXT)
text(s, 1.6, 3.25, 4.0, 1.0, [[("Rangs 2 et 3", {"bold": True, "size": 20})],
                              "les fournisseurs de vos fournisseurs"], size=14, color=WHITE, align=PP_ALIGN.CENTER)
text(s, 0.6, 2.6, 2.0, 0.35, "surface", size=11, color=CYAN_D, italic=True)
# exemple Novalys
text(s, 7.1, 1.95, 5.6, 0.4, "Chez Novalys, par exemple :", size=18, bold=True, color=NIGHT)
chain = [("1", "Rhein Power Modules", "Stuttgart · les modules électroniques", ICE2, NIGHT),
         ("2", "Formoz Power Semi", "Tainan, Taïwan · les puces", NAVY2, WHITE),
         ("3", "TaiSil Wafer", "Hsinchu, Taïwan · les plaquettes de silicium", NIGHT, WHITE)]
for i, (n, name, desc, bg, fg) in enumerate(chain):
    y = 2.55 + i * 1.0
    c = circle(s, 7.45, y + 0.36, 0.62, fill=bg)
    label_in(c, n, size=18, color=fg)
    text(s, 7.95, y + 0.02, 4.75, 0.38, name, size=17, bold=True, color=NIGHT)
    text(s, 7.95, y + 0.4, 4.75, 0.35, desc, size=14, color=TEXT)
    if i < 2:
        connector(s, 7.45, y + 0.7, 7.45, y + 1.0, color=LINE, width=2)
text(s, 7.1, 5.55, 5.6, 0.45, "Quand le rang 3 tombe, le rang 1 l'apprend souvent trop tard.", size=15, italic=True,
     color=CYAN_D)

# ---------------------------------------------------------------- 4. Le bruit
s = frame(4, "Acte 1  ·  Le problème", "Les signaux existent, mais ils sont noyés",
          "une aiguille dans une botte de foin qui grossit à chaque minute.", """
Je vous présente maintenant Claire. Claire est acheteuse chez Novalys, un constructeur de véhicules électriques. Novalys est une entreprise fictive, inventée pour la démonstration, mais le métier de Claire, lui, est bien réel.

Chaque matin, Claire devrait idéalement savoir s'il se passe quelque chose quelque part dans le monde qui pourrait menacer ses approvisionnements. Une grève dans un port, une tempête près d'une usine, une sanction contre un fournisseur, une flambée du prix du transport.

[Pointer la grille de mots] Le problème, c'est le volume. La presse mondiale publie des milliers d'articles par jour, dans des dizaines de langues : l'outil que nous utilisons en couvre 65. À cela s'ajoutent les prévisions météo de chacun de ses sites, et les indicateurs des marchés. Trois sources différentes, à croiser en permanence.

Dans toute cette masse, un seul signal concerne vraiment Novalys aujourd'hui : [pointer la case cyan] un typhon qui se forme près de Kaohsiung, à Taïwan. Encore faut-il le voir, et surtout comprendre qu'il la concerne.

Aucun être humain ne peut faire ce travail de tri chaque jour, de manière fiable. Ce n'est pas un manque de compétence : c'est un problème de capacité.

[Transition] Alors, comment aider Claire ? C'est là qu'intervient A.E.G.I.S.
""")
words = ["grève", "Streik", "inondation", "huelga", "sanction", "faillite",
         "port fermé", "rafales", "embargo", "pénurie", "alluvione", "incendie",
         "shortage", "taxe", "TYPHON", "piratage", "tufão", "quota",
         "explosion", "rupture", "Hafen", "délai", "flood", "tarifs",
         "alerta", "blocus", "séisme", "strike", "retard", "fret"]
for i, w in enumerate(words):
    r, c = divmod(i, 6)
    x, y = 0.6 + c * 1.07, 1.95 + r * 0.62
    hot = w == "TYPHON"
    b = card(s, x, y, 0.95, 0.5, fill=CYAN if hot else SOFT, radius=0.2)
    label_in(b, "typhon" if hot else w, size=12 if not hot else 13, color=WHITE if hot else "94A3B8",
             bold=hot, margin=0.02)
text(s, 0.6, 5.15, 6.4, 0.6, "Un seul de ces signaux concerne vraiment Novalys aujourd'hui.", size=14, italic=True,
     color=MUTED)
# persona
card(s, 7.6, 1.95, 5.13, 1.35, fill=SOFT)
c = circle(s, 8.3, 2.62, 0.85, fill=NIGHT)
label_in(c, "C", size=26, color=CYAN)
text(s, 8.95, 2.15, 3.6, 0.45, "Claire", size=22, bold=True, color=NIGHT)
text(s, 8.95, 2.62, 3.65, 0.6, "Acheteuse chez Novalys (entreprise fictive)", size=14, color=TEXT)
stat(s, 7.6, 3.65, 2.45, "65", "langues dans la presse mondiale suivie")
stat(s, 10.25, 3.65, 2.45, "3", "sources à croiser : presse, météo, marchés")
text(s, 7.6, 5.15, 5.1, 0.7, "Impossible de tout lire, chaque jour, et de faire le lien avec ses sites.", size=15,
     bold=True, color=NIGHT)

# ---------------------------------------------------------------- 5. La solution
s = frame(5, "Acte 2  ·  La solution", "A.E.G.I.S. veille à votre place, sur votre chaîne",
          "la tour de contrôle d'un aéroport : elle voit tous les avions et prévient avant la collision.", """
A.E.G.I.S. est un outil de veille automatique. Son rôle est simple : relier ce qui se passe dans le monde à VOTRE chaîne d'approvisionnement, et vous dire quoi surveiller en priorité.

Il repose sur trois promesses.

[Carte 1] Première promesse : la veille, 24 heures sur 24. L'outil lit l'actualité, la météo et les marchés à la place de Claire. Il ne se fatigue pas, il ne part pas en vacances, il ne rate pas l'article publié à trois heures du matin en coréen.

[Carte 2] Deuxième promesse, et c'est la plus importante : l'information est reliée à votre chaîne. Une tempête à Taïwan n'a aucun intérêt en soi. Elle en a si elle passe sur le port par lequel transitent vos puces. A.E.G.I.S. rattache chaque information à un site, un port ou un fournisseur précis.

[Carte 3] Troisième promesse : des alertes priorisées et expliquées. Vert, orange, rouge. Claire sait immédiatement quoi regarder en premier, et surtout pourquoi.

L'image que nous utilisons, c'est celle de la tour de contrôle d'un aéroport. Les contrôleurs ne pilotent pas les avions. Mais ils voient tout le ciel en même temps, ils anticipent les trajectoires, et ils préviennent avant la collision. D'ailleurs, l'écran principal de notre outil s'appelle justement la « Tour de contrôle ».

[Transition] Concrètement, comment cette tour de contrôle est-elle organisée ?
""", dark=True)
cards = [("bolt", "Veille 24 h/24", "L'outil lit l'actualité, la météo et les marchés à votre place."),
         ("map", "Reliée à votre chaîne", "Chaque information est rattachée à un de vos sites, ports ou fournisseurs."),
         ("layers", "Priorisée et expliquée", "Vert, orange, rouge : vous savez quoi regarder d'abord, et pourquoi.")]
for i, (ic, head, body) in enumerate(cards):
    x = 0.6 + i * 4.15
    card(s, x, 2.05, 3.85, 3.75, fill=NAVY)
    icon_badge(s, x + 0.75, 2.85, 0.9, ic)
    text(s, x + 0.35, 3.6, 3.2, 0.5, head, size=21, bold=True, color=WHITE)
    text(s, x + 0.35, 4.2, 3.2, 1.4, body, size=15, color=ICE2)

# ---------------------------------------------------------------- 6. Trois guetteurs
s = frame(6, "Acte 2  ·  La solution", "Trois guetteurs, une carte, un cerveau",
          "les sentinelles sur les remparts qui font leur rapport à l'état-major.", """
L'organisation d'A.E.G.I.S. tient en trois éléments.

[Colonne de gauche] D'abord, trois guetteurs. Le premier lit la presse du monde entier. Le deuxième surveille la météo autour de chacun de vos sites : vent, pluie, tempêtes. Le troisième suit les marchés : le prix du transport maritime, le prix de certains composants. Chacun est spécialiste de son domaine.

[Au centre] Ensuite, la carte de votre chaîne. C'est le plan de toutes vos dépendances : quelle matière va chez quel fournisseur, par quel port, vers quelle usine, pour quel produit. Les guetteurs y épinglent ce qu'ils trouvent.

[Puis] Enfin, le cerveau : le moteur de décision. Il regarde la carte, combine les informations des trois guetteurs, et calcule pour chaque maillon un niveau de risque.

[À droite] Le résultat, c'est un feu tricolore pour chaque site : à surveiller, alerte, ou critique.

Pensez aux sentinelles d'un château fort. Chaque guetteur surveille sa portion de rempart et fait son rapport. Mais c'est l'état-major, avec la carte du territoire devant lui, qui décide où envoyer les renforts. Un guetteur seul voit un nuage de poussière ; l'état-major comprend que c'est une armée qui marche vers le pont.

[Transition] Voyons maintenant comment Claire utilise tout cela, étape par étape.
""")
guards = [("doc", "Presse", "le monde entier"), ("cloud", "Météo", "autour de vos sites"),
          ("bars", "Marchés", "transport, composants")]
for i, (ic, head, sub) in enumerate(guards):
    y = 1.95 + i * 1.33
    card(s, 0.6, y, 3.1, 1.08, fill=SOFT)
    icon_badge(s, 1.15, y + 0.54, 0.7, ic)
    text(s, 1.65, y + 0.2, 2.0, 0.4, head, size=18, bold=True, color=NIGHT)
    text(s, 1.65, y + 0.58, 2.0, 0.4, sub, size=14, color=TEXT)
    connector(s, 3.75, y + 0.54, 4.6, 3.95, color=CYAN, width=1.75, arrow=True)
card(s, 4.65, 2.75, 2.55, 2.4, fill=ICE)
icon_badge(s, 5.92, 3.45, 0.85, "map", bg=NIGHT)
text(s, 4.8, 4.0, 2.25, 1.0, [[("La carte", {"bold": True, "size": 18, "color": NIGHT})], "de votre chaîne"],
     size=15, color=TEXT, align=PP_ALIGN.CENTER)
connector(s, 7.25, 3.95, 7.75, 3.95, color=CYAN, width=1.75, arrow=True)
card(s, 7.8, 2.75, 2.45, 2.4, fill=NIGHT)
icon_badge(s, 9.02, 3.45, 0.85, "gear")
text(s, 7.9, 4.0, 2.25, 1.0, [[("Le cerveau", {"bold": True, "size": 18, "color": WHITE})], "moteur de décision"],
     size=15, color=ICE2, align=PP_ALIGN.CENTER)
connector(s, 10.3, 3.95, 10.75, 3.95, color=CYAN, width=1.75, arrow=True)
card(s, 10.8, 2.45, 1.93, 3.0, fill=SOFT)
for i, (col, lab) in enumerate([(WATCH, "À surveiller"), (ALERT, "Alerte"), (CRIT, "Critique")]):
    y = 2.85 + i * 0.85
    circle(s, 11.2, y + 0.2, 0.42, fill=col)
    text(s, 11.5, y + 0.04, 1.2, 0.35, lab, size=14, bold=True, color=NIGHT)

# ---------------------------------------------------------------- 7. Étape 0 : la carte
s = frame(7, "Acte 3  ·  Le parcours de Claire", "Étape 0 : on dessine votre chaîne, une seule fois",
          "le plan du métro : chaque station, chaque correspondance.", """
Tout commence par une étape que l'on ne fait qu'une fois : dessiner la carte de la chaîne de Novalys.

[Balayer les colonnes de gauche à droite] On part des matières premières, comme le lithium du Chili ou le silicium. On passe par les fournisseurs, comme Formoz, qui fabrique des puces à Taïwan. Puis par les ports, comme Kaohsiung à Taïwan et Rotterdam aux Pays-Bas. On arrive aux usines, Stuttgart en Allemagne, Valenciennes en France. Et enfin aux produits finis : la citadine électrique E-City, le SUV E-Trail.

Au total, la carte de Novalys compte 30 maillons, répartis sur cinq étages, de la mine jusqu'au produit fini.

Pour chaque site, on note aussi un détail crucial : combien de jours de stock il a devant lui. Une usine qui a trois semaines de stock ne réagit pas du tout comme une usine qui n'en a que trois jours. On y reviendra.

Je précise que les fournisseurs de cette démonstration sont inventés : les ports et les villes sont réels, mais les entreprises sont fictives. Pour une vraie entreprise, cette carte se construit à partir de sa liste de fournisseurs critiques, en une à deux heures d'export de ses outils de gestion.

C'est le plan du métro : avant de prévoir les perturbations, il faut savoir quelles stations sont reliées entre elles, et où sont les correspondances.

[Transition] La carte est prête. Le scénario peut commencer. Jour 1.
""")
cols = [("Matières premières", ["Lithium · Chili", "Silicium · Chine"]),
        ("Fournisseurs", ["Formoz · Taïwan", "TaiSil · Taïwan"]),
        ("Ports", ["Kaohsiung", "Rotterdam"]),
        ("Usines", ["Stuttgart", "Valenciennes"]),
        ("Produits finis", ["Citadine E-City", "SUV E-Trail"])]
cw, gap = 2.13, 0.37
for i, (head, items) in enumerate(cols):
    x = 0.6 + i * (cw + gap)
    h = card(s, x, 1.95, cw, 0.48, fill=NIGHT, radius=0.5)
    label_in(h, head, size=14, color=WHITE)
    for j, it in enumerate(items):
        b = card(s, x, 2.65 + j * 0.72, cw, 0.56, fill=SOFT)
        label_in(b, it, size=14, color=NIGHT, bold=False)
    if i < 4:
        connector(s, x + cw + 0.04, 3.29, x + cw + gap - 0.04, 3.29, color=CYAN, width=2, arrow=True)
for i, (big, small) in enumerate([("30", "maillons sur la carte de Novalys"),
                                  ("5", "étages, de la mine au produit fini"),
                                  ("1 fois", "on dessine la carte à l'installation")]):
    stat(s, 0.6 + i * 4.15, 4.35, 3.8, big, small, big_size=40)

# ---------------------------------------------------------------- 8. Jour 1
s = frame(8, "Acte 3  ·  Le parcours de Claire", "Jour 1 : le signal faible",
          "le détecteur de fumée qui sent avant de voir la flamme.", """
Jour 1. Lundi matin. Claire ouvre A.E.G.I.S.

[Pointer le panneau de gauche] L'indice de risque global de Novalys est à 6 sur 100. Le petit compagnon de l'interface, notre Slime, est bleu : tout est calme. Aucune alerte.

Et pourtant, [pointer la droite] l'outil a déjà repéré deux choses.

Le guetteur météo voit une prévision de rafales violentes à Kaohsiung, à Taïwan, dans deux jours. Kaohsiung, c'est le port par lequel partent les puces de Novalys vers l'Europe.

Le guetteur presse, lui, a lu un article sur un typhon qui se renforce dans la région. L'article ne cite aucun site de Novalys : il n'est donc pas encore relié à la carte, il reste en attente.

C'est ce qu'on appelle un signal faible. Rien d'alarmant pris isolément, mais deux indices qui pointent dans la même direction.

L'image, c'est le détecteur de fumée. Il n'attend pas de voir les flammes : il réagit aux premières particules dans l'air, bien avant que l'incendie soit visible. Ici, il n'y a pas encore de feu, mais il y a de la fumée.

Claire, elle, a maintenant une question en tête : « et si ce port fermait vraiment ? ».

[Transition] Et justement, A.E.G.I.S. lui permet de poser cette question avant que ça arrive.
""", day=1)
card(s, 0.6, 1.95, 5.0, 3.95, fill=SOFT)
add_sprite(s, "slime_calm_idle.png", 1.0, 2.35, 1.55)
text(s, 2.85, 2.25, 2.6, 1.3, [[("6", {"size": 80, "bold": True, "color": NIGHT}),
                                (" / 100", {"size": 24, "color": MUTED})]], size=24)
text(s, 2.9, 3.55, 2.6, 0.4, "Indice de risque global", size=14, color=TEXT)
text(s, 1.0, 4.35, 4.3, 0.9, "Aucune alerte. Tout est calme… en apparence.", size=17, italic=True, bold=True,
     color=CYAN_D)
text(s, 6.1, 1.95, 6.6, 0.45, "Ce qu'A.E.G.I.S. a déjà repéré", size=20, bold=True, color=NIGHT)
sig = [("cloud", "Météo", "Rafales violentes prévues à Kaohsiung (Taïwan) dans 2 jours"),
       ("doc", "Presse", "Un article sur un typhon qui se renforce, sans site de Novalys cité : en attente")]
for i, (ic, head, body) in enumerate(sig):
    y = 2.6 + i * 1.25
    card(s, 6.1, y, 6.63, 1.05, fill=WHITE, line=LINE, line_w=1.25)
    icon_badge(s, 6.62, y + 0.52, 0.66, ic)
    text(s, 7.15, y + 0.12, 5.4, 0.35, head, size=15, bold=True, color=CYAN_D)
    text(s, 7.15, y + 0.45, 5.4, 0.6, body, size=15, color=NIGHT)
text(s, 6.1, 5.2, 6.6, 0.7, "Kaohsiung, c'est le port par lequel partent les puces de Novalys.", size=15,
     italic=True, color=TEXT)

# ---------------------------------------------------------------- 9. Simulation
s = frame(9, "Acte 3  ·  Le parcours de Claire", "« Et si le port fermait ? » On simule avant que ça arrive",
          "le simulateur de vol, ou le GPS qui propose un itinéraire bis.", """
Claire clique sur le port de Kaohsiung et lance une simulation : « et si ce port était touché à 80 % ? ».

[Pointer la chaîne de gauche à droite] L'outil lui montre immédiatement l'onde de choc. Le port de Kaohsiung est touché. Par ricochet, le flux vers Rotterdam se tarit. L'usine de modules de Stuttgart, qui dépend de ces puces, est menacée. Puis les deux usines d'assemblage de Novalys. Et au bout de la chaîne, les trois produits finis.

Ce qui était un vague article sur un typhon devient, en quelques secondes, une liste concrète de produits menacés.

[Pointer le badge] Point important : c'est une simulation. Rien n'est modifié dans la réalité, l'état réel de la chaîne ne bouge pas. Claire peut tester autant de scénarios qu'elle le souhaite.

[Pointer les trois cartes du bas] Surtout, l'outil ne s'arrête pas au diagnostic. Il propose un plan B : passer par un autre port taïwanais, Keelung ; activer un fournisseur de secours, Waal Semiconductors aux Pays-Bas ; et pour les pièces les plus urgentes, basculer sur le fret aérien via Francfort.

C'est le principe du simulateur de vol : les pilotes s'entraînent aux pannes moteur au sol, pas en plein vol. Ou plus simplement, c'est votre GPS : il voit un bouchon devant vous et vous propose déjà un autre itinéraire.

[Transition] Le lendemain, la simulation commence à devenir réalité.
""", day=1)
nodes = [("Port de Kaohsiung", CRIT), ("Port de Rotterdam", ALERT), ("Usine de Stuttgart", ALERT),
         ("2 usines d'assemblage", WATCH), ("3 produits finis", WATCH)]
cxs = [1.6, 4.15, 6.7, 9.25, 11.7]
for i, ((lab, col), cx) in enumerate(zip(nodes, cxs)):
    circle(s, cx, 2.5, 0.72, fill=col)
    text(s, cx - 1.0, 2.98, 2.0, 0.7, lab, size=15, bold=True, color=NIGHT, align=PP_ALIGN.CENTER)
    if i < 4:
        connector(s, cx + 0.45, 2.5, cxs[i + 1] - 0.45, 2.5, color=NAVY2, width=2, arrow=True)
text(s, 1.15, 2.33, 0.9, 0.35, "80 %", size=14, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
text(s, 0.6, 4.05, 4.0, 0.4, "Plan B proposé", size=18, bold=True, color=NIGHT)
b = card(s, 8.6, 4.05, 4.13, 0.38, fill=ICE, radius=0.5)
label_in(b, "Simulation : la réalité n'est pas modifiée", size=12, color=CYAN_D)
planb = [("arrow", "Port de Keelung", "Expédier par l'autre port de Taïwan"),
         ("loop", "Waal Semiconductors", "Activer le fournisseur de secours (Pays-Bas)"),
         ("bolt", "Fret aérien Francfort", "Pour les pièces les plus urgentes")]
for i, (ic, head, body) in enumerate(planb):
    x = 0.6 + i * 4.14
    card(s, x, 4.55, 3.85, 1.4, fill=SOFT)
    icon_badge(s, x + 0.55, 5.25, 0.66, ic)
    text(s, x + 1.05, 4.75, 2.7, 0.4, head, size=16, bold=True, color=NIGHT)
    text(s, x + 1.05, 5.12, 2.7, 0.75, body, size=14, color=TEXT)

# ---------------------------------------------------------------- 10. Jour 2 : dominos
s = frame(10, "Acte 3  ·  Le parcours de Claire", "Jour 2 : l'alerte arrive avant les journaux",
          "les dominos : on voit tomber le premier, on sait lesquels suivront.", """
Jour 2. Le port de Kaohsiung annonce sa fermeture, et la prévision météo s'aggrave.

[Pointer le panneau sombre] Et là, il se passe quelque chose d'important : l'usine de Stuttgart passe en alerte.

Or, à ce moment-là, aucun article de presse ne parle de cette usine. Pas un seul. Si Claire se contentait de lire les journaux, elle ne verrait rien.

Comment l'outil le sait-il ? Parce qu'il connaît la carte. Il sait que l'usine de Stuttgart dépend des puces qui passent par Kaohsiung, puis par Rotterdam. Il sait aussi qu'elle n'a qu'une vingtaine de jours de stock. Il en déduit que le risque va remonter jusqu'à elle, même si personne n'en parle encore.

[Pointer les dominos] C'est exactement l'image des dominos. Quand on voit tomber le premier, et qu'on sait comment ils sont alignés, on n'a pas besoin d'attendre pour savoir lesquels vont suivre. Le typhon pousse le port, le port pousse la route vers Rotterdam, la route pousse Stuttgart, et Stuttgart poussera Valenciennes.

C'est toute la différence entre une veille de presse classique, qui vous dit ce qui est arrivé, et A.E.G.I.S., qui vous dit ce qui va vous arriver.

[Transition] Mais une alerte, aussi précoce soit-elle, ne vaut que si l'on peut lui faire confiance. Alors Claire clique dessus.
""", day=2)
doms = [("Typhon", CRIT), ("Port de Kaohsiung", CRIT), ("Route vers Rotterdam", ALERT),
        ("Usine de Stuttgart", ALERT), ("Usine de Valenciennes", LINE)]
for i, (lab, col) in enumerate(doms):
    x = 1.0 + i * 1.38
    d = card(s, x, 2.45, 0.58, 1.9, fill=col, radius=0.12, rot=-22 if i == 0 else (-8 if i == 1 else 0))
    if i == 3:
        d.line.color.rgb = rgb(CYAN)
        d.line.width = Pt(3)
    text(s, x - 0.38, 4.55, 1.34, 0.9, lab, size=14, bold=i == 3, color=NIGHT, align=PP_ALIGN.CENTER)
b = card(s, 4.5, 1.95, 1.75, 0.36, fill=CYAN, radius=0.5)
label_in(b, "ALERTE · jour 2", size=12, color=WHITE)
card(s, 8.1, 1.95, 4.63, 3.95, fill=NIGHT)
text(s, 8.5, 2.25, 3.9, 0.8, "Jour 2", size=40, bold=True, color=CYAN)
text(s, 8.5, 3.1, 3.9, 0.9, "L'usine de Stuttgart passe en alerte", size=21, bold=True, color=WHITE)
text(s, 8.5, 4.1, 3.9, 1.6, "Aucun article ne parle encore de cette usine. L'outil déduit le risque de sa "
                            "dépendance au port.", size=15, color=ICE2)

# ---------------------------------------------------------------- 11. Preuves
s = frame(11, "Acte 3  ·  Le parcours de Claire", "Chaque alerte montre ses preuves",
          "le médecin qui montre la radio avant de poser le diagnostic.", """
Jour 3. Le typhon a touché terre. Le port est fermé, et l'usine de puces de Tainan est inondée. Claire ouvre l'alerte sur l'usine de Stuttgart, Rhein Power Modules.

Elle ne voit pas seulement un voyant rouge. Elle voit trois réponses.

[Carte 1] D'où vient l'information ? L'outil affiche les articles et les prévisions météo d'origine, avec leur date. Claire peut cliquer et lire la source elle-même.

[Carte 2] Par où passe le risque ? Le chemin exact dans la chaîne : Kaohsiung, puis Rotterdam, puis Stuttgart. Elle comprend en un coup d'œil pourquoi une tempête à Taïwan concerne une usine allemande.

[Carte 3] Pourquoi ce niveau d'alerte ? La règle appliquée, en clair. Ici : deux sources différentes, la presse et la météo, confirment le même événement, et le stock de l'usine ne couvre qu'une vingtaine de jours.

Pas de boîte noire. Claire peut défendre cette alerte devant sa direction, ou au contraire la contester si elle connaît une information que l'outil n'a pas.

C'est comme chez le médecin. Un bon médecin ne vous dit pas seulement « vous avez une fracture » : il vous montre la radio, il vous montre où est la fissure, et il vous explique pourquoi il recommande un plâtre. Vous lui faites confiance parce que vous voyez ce qu'il voit.

[Transition] Et si Claire a une question que l'écran ne traite pas directement ? Elle peut simplement la poser.
""", day=3)
pill = card(s, 0.6, 1.95, 6.3, 0.38, fill=ICE, radius=0.5)
label_in(pill, "Exemple : alerte sur Rhein Power Modules (Stuttgart)", size=13, color=CYAN_D)
proofs = [("doc", "D'où vient l'info ?", "L'article et la prévision météo d'origine, datés. Un clic pour lire la source."),
          ("map", "Par où passe le risque ?", None),
          ("layers", "Pourquoi ce niveau ?", "Deux sources différentes confirment, et le stock de l'usine ne couvre "
                                             "qu'une vingtaine de jours.")]
for i, (ic, head, body) in enumerate(proofs):
    x = 0.6 + i * 4.14
    card(s, x, 2.55, 3.85, 3.4, fill=SOFT)
    icon_badge(s, x + 0.65, 3.2, 0.8, ic)
    text(s, x + 0.3, 3.8, 3.3, 0.45, head, size=18, bold=True, color=NIGHT)
    if body:
        text(s, x + 0.3, 4.35, 3.3, 1.5, body, size=15, color=TEXT)
    else:
        for j, step in enumerate(["Kaohsiung", "Rotterdam", "Stuttgart"]):
            yy = 4.32 + j * 0.52
            p = card(s, x + 0.3, yy, 1.9, 0.38, fill=NIGHT if j == 2 else WHITE, line=None if j == 2 else LINE,
                     radius=0.5)
            label_in(p, step, size=13, color=WHITE if j == 2 else NIGHT)
            if j < 2:
                connector(s, x + 1.25, yy + 0.38, x + 1.25, yy + 0.52, color=CYAN, width=1.5)

# ---------------------------------------------------------------- 12. Copilot
s = frame(12, "Acte 3  ·  Le parcours de Claire", "Poser ses questions en français",
          "un collègue expert, disponible à toute heure, qui ne bluffe jamais.", """
Jour 5. La situation se complique : une grève éclate au port de Rotterdam. Les deux bouts de la route des puces sont maintenant bloqués. Claire doit préparer une réunion avec sa direction, et elle a des questions précises.

Plutôt que de naviguer dans les écrans, elle les pose directement à l'assistant, en français, comme elle le ferait à un collègue.

[Pointer la conversation] « Si Kaohsiung ferme, quels produits sont menacés ? » L'assistant répond : les trois produits finis, et il indique par où passe le choc. Sa réponse s'appuie sur la carte et sur les calculs de l'outil, pas sur une intuition.

Deuxième question : « Quel est le prix de notre contrat avec Formoz ? ». Et là, l'assistant répond honnêtement : « je n'ai pas cette donnée ». Les contrats ne sont pas dans la base, et il ne va pas inventer un chiffre pour faire plaisir.

[Pointer le Slime] Cet assistant prend la forme de notre petit compagnon, le Slime. Il change de couleur selon le niveau de risque : bleu quand tout va bien, jaune quand il faut surveiller, rouge en cas d'alerte.

Cette règle du « je ne sais pas » est fondamentale. Un assistant qui invente une réponse plausible est plus dangereux qu'un assistant qui reconnaît ses limites. C'est le collègue expert idéal : disponible à toute heure, toujours précis, et qui ne bluffe jamais.

[Transition] Avançons maintenant jusqu'au dernier jour du scénario.
""", day=5)
card(s, 0.6, 1.95, 7.4, 4.0, fill=SOFT)
text(s, 0.85, 2.05, 3.0, 0.3, "Illustration", size=11, italic=True, color=MUTED)


def bubble(slide, x, y, w, h, txt, user):
    b = card(slide, x, y, w, h, fill=CYAN if user else WHITE, line=None if user else LINE, radius=0.25)
    label_in(b, txt, size=14, color=WHITE if user else NIGHT, bold=False, align=PP_ALIGN.LEFT, margin=0.18)


bubble(s, 2.3, 2.4, 5.45, 0.55, "Si Kaohsiung ferme, quels produits sont menacés ?", True)
add_sprite(s, "slime_calm_happy.png", 0.85, 3.17, 0.55)
bubble(s, 1.55, 3.1, 6.2, 0.9, "Les trois produits finis : E-City, E-Trail et l'onduleur RX. "
                               "Le choc passe par Rotterdam, puis par l'usine de Stuttgart.", False)
bubble(s, 2.3, 4.2, 5.45, 0.55, "Quel est le prix de notre contrat avec Formoz ?", True)
add_sprite(s, "slime_calm_happy.png", 0.85, 4.97, 0.55)
bubble(s, 1.55, 4.9, 6.2, 0.75, "Je n'ai pas cette donnée : les contrats ne sont pas dans la base.", False)
add_sprite(s, "slime_warning_announce.png", 9.55, 1.95, 1.9)
checks = ["Répond en français, chiffres à l'appui", "Montre le chemin dans la chaîne",
          "Dit « je ne sais pas » plutôt que d'inventer"]
for i, t in enumerate(checks):
    y = 3.8 + i * 0.7
    icon_badge(s, 8.75, y + 0.22, 0.42, "check")
    text(s, 9.1, y, 3.63, 0.6, t, size=15, color=NIGHT, bold=i == 2)

# ---------------------------------------------------------------- 13. Jour 7
s = frame(13, "Acte 3  ·  Le parcours de Claire", "Jour 7 : la presse découvre ce que vous saviez depuis 4 jours",
          "le bulletin météo face à l'averse : on avait pris le parapluie.", """
Jour 7, dernier jour du scénario. La presse annonce que l'usine d'assemblage de Valenciennes s'arrête une semaine. La veille, au jour 6, elle annonçait déjà que l'usine de Stuttgart réduisait sa production.

[Pointer la courbe bleue] Ce graphique résume toute l'histoire. La courbe bleue, c'est le risque calculé par A.E.G.I.S. pour l'usine de Stuttgart. Elle franchit le seuil d'alerte dès le jour 2, à 42 %.

[Pointer la courbe orange] La courbe orange, c'est ce qu'on aurait vu en lisant seulement les articles qui citent l'usine. Elle reste à zéro jusqu'au jour 6, date du premier article.

[Pointer la zone bleutée] Entre les deux : quatre jours d'avance. Quatre jours pendant lesquels Claire pouvait commander ailleurs, réserver du fret aérien, prévenir ses clients. Quatre jours pendant lesquels ses concurrents, eux, ne savaient rien.

Je dois être honnête avec vous, et c'est d'ailleurs écrit en bas du graphique : ce scénario a été écrit pour la démonstration. Ces quatre jours illustrent la mécanique, ce ne sont pas une mesure de performance. La vraie mesure, nous allons la faire sur des crises réelles, j'y reviendrai.

C'est la différence entre le bulletin météo et l'averse. Quand la pluie tombe, ceux qui ont écouté le bulletin ont déjà leur parapluie. Les autres courent se mettre à l'abri.

[Transition] Concrètement, que changent ces quelques jours pour une entreprise ?
""", day=7)
if FIGURE.exists():
    pic = s.shapes.add_picture(str(FIGURE), Inches(0.6), Inches(1.95), Inches(7.1))
    pic.name = "Figure anticipation Stuttgart"
else:
    ph = card(s, 0.6, 1.95, 7.1, 4.0, fill=SOFT)
    label_in(ph, "Figure absente : lancer python scripts/export_soutenance.py", size=14, color=MUTED, bold=False)
stat(s, 8.15, 1.95, 4.5, "Jour 2", "A.E.G.I.S. alerte sur l'usine de Stuttgart", big_color=CYAN_D, big_size=34)
stat(s, 8.15, 3.2, 4.5, "Jour 6", "premier article de presse qui cite l'usine", big_color=ALERT, big_size=34)
stat(s, 8.15, 4.45, 4.5, "4 jours", "d'avance pour agir", big_color=NIGHT, big_size=34)
text(s, 8.15, 5.6, 4.55, 0.4, "Scénario de démonstration : avance à confirmer sur des crises réelles.", size=11,
     italic=True, color=MUTED)

# ---------------------------------------------------------------- 14. Valeur
s = frame(14, "Acte 4  ·  La valeur ajoutée", "Quelques jours d'avance, c'est le temps d'agir",
          "la différence entre un détour et un accident.", """
Revenons à la question qui compte pour un décideur : à quoi servent ces jours d'avance ?

[Cartes du haut, une par une] À trois choses très concrètes.

Un : commander ailleurs. Activer le fournisseur de secours avant que tout le monde se rue dessus. Quand une pénurie est publique, les capacités de secours sont prises d'assaut en quelques heures. Celui qui arrive premier est servi.

Deux : changer de route. Passer par un autre port, ou faire venir en avion les quelques pièces vraiment critiques. C'est plus cher, mais infiniment moins cher qu'une usine à l'arrêt.

Trois : prévenir ses clients. Annoncer un retard maîtrisé, avec un plan, plutôt que de subir un appel furieux. La confiance d'un client se joue souvent là.

[Cartes du bas] Deux principes rendent ces alertes utiles au quotidien. D'abord, elles sont triées : ce qui peut réellement arrêter une usine passe en premier, le reste attend. Ensuite, l'outil tient compte des stocks : un site qui a deux mois de réserve ne déclenche pas de fausse panique. C'est ce qui évite le syndrome du garçon qui criait au loup, où l'on finit par ignorer toutes les alertes.

Un conducteur prévenu d'un accident sur l'autoroute fait un petit détour. Un conducteur qui ne l'est pas se retrouve bloqué deux heures. Même route, même accident : seule l'information change.

[Transition] Il existe d'autres outils de veille sur le marché. Qu'est-ce qui distingue A.E.G.I.S. ?
""")
acts = [("loop", "Commander ailleurs", "Activer le fournisseur de secours avant la ruée."),
        ("arrow", "Changer de route", "Autre port, ou avion pour les pièces urgentes."),
        ("bubble", "Prévenir ses clients", "Annoncer un retard maîtrisé plutôt que le subir.")]
for i, (ic, head, body) in enumerate(acts):
    x = 0.6 + i * 4.14
    card(s, x, 1.95, 3.85, 2.1, fill=SOFT)
    icon_badge(s, x + 0.65, 2.6, 0.8, ic)
    text(s, x + 1.25, 2.38, 2.5, 0.45, head, size=18, bold=True, color=NIGHT)
    text(s, x + 0.35, 3.2, 3.2, 0.8, body, size=15, color=TEXT)
for i, (head, body) in enumerate([("Des alertes triées", "Ce qui peut arrêter une usine passe en premier."),
                                  ("Les stocks pris en compte", "Un site bien approvisionné ne déclenche pas "
                                                                "de fausse panique.")]):
    x = 0.6 + i * 6.2
    card(s, x, 4.3, 5.93, 1.6, fill=NIGHT)
    text(s, x + 0.4, 4.5, 5.2, 0.45, head, size=19, bold=True, color=CYAN)
    text(s, x + 0.4, 5.0, 5.2, 0.8, body, size=15, color=WHITE)

# ---------------------------------------------------------------- 15. Différence
s = frame(15, "Acte 4  ·  La valeur ajoutée", "Ce qui nous distingue",
          "le crash-test publié face à la promesse du vendeur.", """
Le marché de la veille sur les fournisseurs existe déjà. De grandes plateformes, souvent américaines ou européennes, couvrent des centaines de langues et des millions d'entreprises. Nous ne prétendons pas les battre sur la taille.

[Colonne de gauche] Ce que le marché met en avant, c'est la couverture : toujours plus de sources, toujours plus de langues, des scores de risque. Mais ces plateformes publient rarement deux chiffres pourtant essentiels : combien de jours d'avance elles donnent réellement, et combien de fausses alertes elles déclenchent.

[Colonne de droite] C'est précisément l'espace que nous occupons. A.E.G.I.S. veut prouver plutôt que promettre. Nous mesurons l'avance réelle, en jours, en rejouant des crises passées. Nous comptons les fausses alertes. Chaque alerte est expliquée, source à l'appui. Et l'outil fonctionne avec des données ouvertes, donc à un coût faible, accessible à une PME industrielle.

[Ligne du bas] Enfin, le même outil s'adapte à d'autres métiers. On change la carte, pas le moteur. Nous l'avons déjà fait tourner sur une chaîne pharmaceutique, avec un scénario d'inondations en Inde et de cyberattaque au port d'Anvers. L'agroalimentaire et l'énergie sont des pistes naturelles.

Quand vous achetez une voiture, vous pouvez croire le vendeur qui vous dit qu'elle est sûre. Ou regarder le résultat du crash-test, publié, mesuré, comparable. Nous voulons être le crash-test.

[Transition] Je vous ai promis d'expliquer le fonctionnement sans jargon. C'est le moment.
""")
card(s, 0.6, 1.95, 5.93, 2.95, fill=SOFT)
text(s, 0.95, 2.15, 5.3, 0.45, "Ce que le marché promet", size=19, bold=True, color=MUTED)
dot_rows(s, 0.95, 2.75, 5.3, ["Toujours plus de sources et de langues", "Des scores de risque",
                              "Peu de preuves publiées sur la fiabilité"], dot="94A3B8", row_h=0.5)
card(s, 6.8, 1.95, 5.93, 2.95, fill=NIGHT)
text(s, 7.15, 2.15, 5.3, 0.45, "Ce qu'A.E.G.I.S. prouve", size=19, bold=True, color=CYAN)
dot_rows(s, 7.15, 2.7, 5.3, ["L'avance réelle, mesurée en jours", "Les fausses alertes, comptées",
                              "Chaque alerte expliquée, source à l'appui", "Des données ouvertes, un coût faible"],
         color=WHITE, row_h=0.42, gap=0.1)
text(s, 0.6, 5.12, 6.0, 0.35, "Un même outil, plusieurs métiers :", size=15, bold=True, color=NIGHT)
chips = [("Électronique et véhicule électrique", NIGHT, WHITE), ("Pharmacie", NIGHT, WHITE),
         ("Agroalimentaire (piste)", ICE, CYAN_D), ("Énergie (piste)", ICE, CYAN_D)]
x = 0.6
for lab, bg, fg in chips:
    w = 0.4 + len(lab) * 0.085
    c = card(s, x, 5.55, w, 0.42, fill=bg, radius=0.5)
    label_in(c, lab, size=13, color=fg)
    x += w + 0.15

# ---------------------------------------------------------------- 16. Quatre gestes
s = frame(16, "Acte 5  ·  Comment ça marche", "Quatre gestes : écouter, comprendre, relier, prévenir",
          "une rédaction de journal : reporters, tri, recoupement, puis la une.", """
Si je devais résumer le fonctionnement d'A.E.G.I.S. en quatre verbes, ce seraient ceux-là.

[1] Écouter. Chaque jour, l'outil collecte la presse mondiale, les prévisions météo autour de chaque site, et les indicateurs des marchés. Automatiquement, sans intervention humaine.

[2] Comprendre. Pour chaque information, il repère de quoi elle parle : est-ce une grève, une tempête, une sanction, une faillite ? Où cela se passe-t-il ? Quand ? Quelles entreprises sont citées ? Il regroupe aussi les dizaines d'articles qui racontent le même événement, pour ne pas le compter dix fois.

[3] Relier. Il rattache ensuite l'information au bon maillon de la carte : ce port, cette usine, ce fournisseur. C'est l'étape qui transforme une actualité mondiale en information qui vous concerne.

[4] Prévenir. Enfin, il calcule jusqu'où l'onde de choc se propage dans la chaîne, en tenant compte des stocks et des fournisseurs de secours, puis il alerte, avec les preuves.

C'est exactement le fonctionnement d'une rédaction de journal. Les reporters sur le terrain collectent l'information. Le secrétariat de rédaction trie et vérifie. Les journalistes recoupent et font le lien entre les faits. Et le rédacteur en chef décide de ce qui fait la une.

[Transition] Reste une question légitime : pourquoi faire confiance à une machine pour tout cela ?
""")
steps = [("Écouter", "Lire chaque jour la presse mondiale, la météo de vos sites et les marchés."),
         ("Comprendre", "Repérer de quoi parle l'information : grève, tempête, sanction… où, et quand."),
         ("Relier", "La rattacher au bon maillon : ce port, cette usine, ce fournisseur."),
         ("Prévenir", "Calculer jusqu'où l'onde se propage, puis alerter avec les preuves.")]
connector(s, 1.15, 2.55, 0.6 + 3 * 3.1 + 0.55, 2.55, color=ICE2, width=3)
for i, (head, body) in enumerate(steps):
    x = 0.6 + i * 3.1
    c = circle(s, x + 0.55, 2.55, 1.1, fill=NIGHT if i < 3 else CYAN)
    label_in(c, str(i + 1), size=30, color=CYAN if i < 3 else WHITE)
    text(s, x, 3.35, 2.85, 0.5, head, size=22, bold=True, color=NIGHT)
    text(s, x, 3.95, 2.8, 1.9, body, size=15, color=TEXT)

# ---------------------------------------------------------------- 17. Confiance
s = frame(17, "Acte 5  ·  Comment ça marche", "Pourquoi on peut lui faire confiance",
          "une enquête : on croise les témoignages avant de conclure.", """
Un outil d'alerte n'a de valeur que si l'on peut lui faire confiance. Nous avons construit A.E.G.I.S. autour de quatre garde-fous.

[En haut à gauche] Les sources se recoupent. Une information confirmée à la fois par la presse et par la météo pèse beaucoup plus qu'un article isolé. Et un article seul, qui ne cite précisément aucun de vos sites, ne peut jamais déclencher d'alerte à lui tout seul : au mieux, il fait passer un site en « à surveiller ».

[En haut à droite] Le stock amortit le choc. Plus un site a de réserves, moins un problème en amont se transmet jusqu'à lui. C'est ce qui permet d'éviter les fausses paniques.

[En bas à gauche] Aucun fait sans sa source. Chaque alerte renvoie à l'article ou à la mesure d'origine. Et l'assistant ne complète jamais avec des suppositions : s'il ne sait pas, il le dit.

[En bas à droite] Une panne reste une panne. Si une source ne répond pas, par exemple si le site d'actualités est inaccessible, l'écran l'indique clairement. Un silence ne doit jamais être confondu avec un « tout va bien ». C'est un point qu'on oublie souvent, et il est crucial : un écran vert parce que la collecte est en panne, c'est le pire des scénarios.

Pensez à une enquête de police. Un bon enquêteur ne conclut pas sur la foi d'un seul témoin. Il croise les témoignages, il vérifie les alibis, il distingue ce qu'il sait de ce qu'il suppose. A.E.G.I.S. applique la même discipline.

[Transition] Je vous dois maintenant un point d'étape honnête sur l'état du projet.
""")
trust = [("map", "Les sources se recoupent", "Presse et météo d'accord pèsent plus qu'un article isolé. "
                                               "Un article seul et flou ne déclenche jamais d'alerte."),
         ("layers", "Le stock amortit le choc", "Plus un site a de réserves, moins le problème en amont "
                                                 "se transmet. On évite de crier au loup."),
         ("doc", "Aucun fait sans sa source", "Chaque alerte renvoie à son origine. L'assistant "
                                               "n'invente jamais."),
         ("plug", "Une panne reste une panne", "Si une source ne répond pas, l'écran le dit. Le silence ne "
                                                "passe jamais pour un « tout va bien ».")]
for i, (ic, head, body) in enumerate(trust):
    r, c = divmod(i, 2)
    x, y = 0.6 + c * 6.18, 1.95 + r * 2.07
    card(s, x, y, 5.95, 1.85, fill=SOFT)
    icon_badge(s, x + 0.62, y + 0.62, 0.74, ic)
    text(s, x + 1.2, y + 0.3, 4.5, 0.45, head, size=18, bold=True, color=NIGHT)
    text(s, x + 1.2, y + 0.78, 4.55, 1.0, body, size=14, color=TEXT)

# ---------------------------------------------------------------- 18. Où on en est
s = frame(18, "Acte 5  ·  Comment ça marche", "Où on en est, honnêtement",
          "un médicament : le labo est concluant, place aux essais cliniques.", """
Je tiens à être transparent sur l'état du projet, parce que c'est précisément notre argument face au marché : la preuve plutôt que la promesse.

[Colonne de gauche] Aujourd'hui, nous avons un prototype complet, qui fonctionne de bout en bout : les trois guetteurs, la carte, le moteur de décision, les écrans et l'assistant. Il tourne sur deux crises simulées, l'une en électronique, celle que je viens de vous raconter, l'autre en pharmacie. Et il dispose d'un mode réel, branché sur la vraie presse, la vraie météo et les vrais marchés : lors de notre dernier test, il a fait remonter une vingtaine d'événements réels.

Mais je le redis : les quatre jours d'avance de la démonstration viennent d'un scénario que nous avons écrit. Ils prouvent que la mécanique fonctionne, pas que l'outil est fiable.

[Colonne de droite] La prochaine étape est donc la plus importante. Nous allons rejouer quatre crises réelles, jour par jour : Nexperia, dont je vous ai parlé au début ; l'ouragan Helene en 2024 ; une grève des ports ; et les restrictions chinoises sur les terres rares. Pour chacune, nous mesurerons combien de jours d'avance l'outil aurait réellement donnés. Nous ferons aussi tourner l'outil sur une année entière pour compter les fausses alertes. Et nous souhaitons faire valider les alertes par un professionnel des achats.

C'est le parcours d'un médicament. Les essais en laboratoire sont concluants : la molécule fait ce qu'on attend d'elle. Mais avant de la mettre sur le marché, il faut les essais cliniques, sur de vrais patients, avec des résultats mesurés. Nous en sommes là.

[Transition] Pour conclure.
""")
card(s, 0.6, 1.95, 5.55, 3.95, fill=ICE)
text(s, 0.95, 2.15, 4.9, 0.45, "Aujourd'hui", size=21, bold=True, color=NIGHT)
dot_rows(s, 0.95, 2.8, 4.95, ["Un prototype complet, qui fonctionne de bout en bout",
                              "Deux crises simulées : électronique et pharmacie",
                              "Un mode réel branché sur la presse, la météo et les marchés"],
         color=NIGHT, row_h=0.8, gap=0.12)
shape(s, MSO_SHAPE.CHEVRON, 6.4, 3.55, 0.55, 0.75, fill=CYAN)
card(s, 7.18, 1.95, 5.55, 3.95, fill=NIGHT)
text(s, 7.53, 2.15, 4.9, 0.45, "Prochaine étape", size=21, bold=True, color=CYAN)
dot_rows(s, 7.53, 2.8, 4.95, ["Rejouer 4 vraies crises : Nexperia, ouragan Helene, grève des ports, terres rares",
                              "Compter les fausses alertes sur une année entière",
                              "Faire valider les alertes par un professionnel des achats"],
         color=WHITE, row_h=0.8, gap=0.12)

# ---------------------------------------------------------------- 19. Conclusion
s = prs.slides.add_slide(BLANK)
background(s, NIGHT)
C2 = (10.6, 3.2)
circle(s, C2[0], C2[1], 3.6, line=CYAN, line_w=1.5)
for m in [(9.5, 2.3), (11.7, 2.2), (11.6, 4.1), (9.6, 4.2)]:
    connector(s, C2[0], C2[1], m[0], m[1], color=NAVY2, width=1.5)
    circle(s, m[0], m[1], 0.24, fill=NAVY2)
circle(s, C2[0], C2[1], 0.62, fill=CYAN)
circle(s, C2[0], C2[1], 0.3, fill=WHITE)
text(s, 0.6, 0.34, 7.5, 0.3, "CONCLUSION", size=12, bold=True, color=CYAN, spacing=150)
text(s, 0.6, 1.0, 7.8, 1.6, "Ne plus subir, anticiper", size=48, bold=True, color=WHITE)
text(s, 0.6, 2.55, 7.6, 0.5, [[("A.E.G.I.S.", {"bold": True, "color": CYAN}), (f"  ·  {ACRONYM}", {})]], size=15,
     color=ICE2)
card(s, 0.6, 3.35, 7.4, 1.95, fill=NAVY)
text(s, 0.95, 3.55, 6.8, 0.45, "Notre proposition : un pilote gratuit", size=20, bold=True, color=CYAN)
text(s, 0.95, 4.05, 6.75, 1.2, "Votre chaîne, une crise que vous avez vécue, rejouée jour par jour. Accord de "
                               "confidentialité signé, données supprimées en fin de projet.", size=15, color=WHITE)
text(s, 8.6, 5.3, 4.1, 0.6, "Merci. Vos questions ?", size=24, bold=True, color=WHITE, align=PP_ALIGN.RIGHT)
analogy(s, "l'égide levée à temps : protégé avant le choc.", dark=True)
footer(s, 19, dark=True)
s.notes_slide.notes_text_frame.text = """
Revenons au point de départ. En 2025, 28 jours séparaient le premier signal public de l'arrêt d'une usine Honda. L'information existait. Elle n'a simplement pas été reliée à temps.

A.E.G.I.S. est né de ce constat. Nous ne prétendons pas prédire l'avenir. Nous prétendons quelque chose de plus modeste et de plus utile : relier ce qui se passe dans le monde à votre chaîne d'approvisionnement, assez tôt pour que vous puissiez agir, et toujours en vous montrant les preuves.

Avec Claire, vous avez vu le parcours complet : un signal faible au jour 1, une simulation pour préparer un plan B, une alerte au jour 2 sur une usine dont personne ne parlait encore, des preuves pour chaque alerte, un assistant qui répond en français et qui sait dire « je ne sais pas ». Et au bout, quelques jours d'avance : le temps de commander ailleurs, de changer de route, de prévenir ses clients.

[Pointer la carte] Notre prochaine étape, c'est la preuve sur des crises réelles. Et pour cela, nous cherchons des partenaires. Nous proposons un pilote gratuit : nous construisons la carte de votre chaîne, et nous rejouons jour par jour une crise que vous avez vraiment vécue, pour voir ce qu'A.E.G.I.S. vous aurait dit. Tout cela sous accord de confidentialité, avec suppression des données à la fin du projet.

Ne plus subir, anticiper. C'est le sens de l'égide : un bouclier ne sert que s'il est levé avant le coup.

Je vous remercie pour votre attention, et je suis prêt à répondre à vos questions.

[Questions probables à préparer : « Vos quatre jours sont-ils réels ? » → non, scénario de démonstration, d'où le plan de mesure sur quatre crises réelles. « Qu'est-ce qui vous distingue des grands acteurs ? » → la preuve mesurée et l'explication de chaque alerte. « Que faut-il fournir pour démarrer ? » → la liste des fournisseurs critiques, les jours de stock en ordre de grandeur, et deux ou trois crises déjà vécues.]
"""

# ---------------------------------------------------------------- métadonnées et écriture
prs.core_properties.title = "A.E.G.I.S. – présentation non technique"
prs.core_properties.subject = ACRONYM
prs.core_properties.author = "Équipe projet INGE3 n°6"
prs.save(OUTPUT)
print(f"Présentation écrite : {OUTPUT} ({len(prs.slides)} slides)")
if not FIGURE.exists():
    print("Attention : figure absente, emplacement réservé sur la slide 13 "
          "(lancer python scripts/export_soutenance.py puis relancer ce script).")
