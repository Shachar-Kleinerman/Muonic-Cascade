"""The help guide of the site (opened with the "?" button next to the language switch), in Hebrew and English.

The page shows it as a layer over the window. Everything here is plain HTML / inline SVG, drawn at run time, so it follows
the chosen language. The illustrations use REAL numbers: a small cascade of C-12 and Ne-20 computed with the site's own
physics settings (see gen_help_data.py: FERMI2, Uehling, screening Z-1, recoil, start n = 5, statistical population).
"""
import html as _html

# (energy keV, counts) of the photons of 1500 muons, rounded; from help_data.json
_SPECTRA = {
    "C": [(0.015, 1), (0.023, 1), (0.027, 1)],
    "Ne": [(0.367, 1)],
}


def _load_spectra():
    """The numbers sit in help_guide_data.py (generated from help_data.json by build_help_data_module)."""
    try:
        import help_guide_data as d
        return d.SPECTRA, d.EXAMPLE
    except ImportError:                                        # a guide without data would be wrong: fall back to a tiny sample
        return _SPECTRA, [("5g_9/2", "4f_7/2", 6.295), ("4f_7/2", "3d_5/2", 13.614), ("3d_5/2", "2p_3/2", 38.975), ("2p_3/2", "1s_1/2", 207.305)]


TEXT = {
    "EN": {
        "title": "What this site can do",
        "close": "Close",
        "intro": "This site simulates how a negative muon, captured by an atom, cascades down the energy levels of the muonic atom, "
                 "and the X-rays it emits on the way. The energies and the transition rates come from MUDIRAC, a solver of the "
                 "radial Dirac equation (Sturniolo &amp; Hillier, X-Ray Spectrometry 2021).",
        "s1": "1. Create a spectrum with the settings you choose",
        "s1_items": [
            "Pick the element in the periodic table (up to Z = 111) and the isotope, or the natural mix.",
            "Choose the nuclear model (Fermi 2-term charge distribution, uniform sphere, or point charge), the starting level n "
            "(2 to 8) and how the muons are spread over its sublevels: statistical, uniform, or one chosen sublevel (delta).",
            "Set the number of muons, and switch the two corrections on or off: vacuum polarization (Uehling) and electronic "
            "screening. The nuclear recoil is always included.",
            "Press the create button: MUDIRAC computes every level the muons pass through and the spectrum appears.",
        ],
        "s2": "2. View the spectrum and compare it with other spectra",
        "s2_items": [
            "Every spectrum is a tab on the left. Tick the tabs to show: they are drawn together or one under the other. "
            "Drag a tab to reorder, click its colour circle to change the colour, and use the icons to edit, copy or delete it.",
            "Use the logarithmic axis, the relative-intensity mode and the column-width slider. Zoom with the mouse wheel, "
            "drag to move, double-click to return to the full view.",
            "Hover over a column to see the exact energies of the lines inside it and how many photons each has.",
        ],
        "s3": "3. Watch the simulation next to the growing spectrum",
        "s3_items": [
            "With fewer than 5,000 muons, press the play button on a tab. On the left the muon falls from level to level and emits a "
            "photon at every step; on the right the spectrum builds up photon by photon.",
            "Control the speed, step from transition to transition, or jump along the timeline (one segment per muon).",
            "Hover over a level to see the branching ratios of its decay at the bottom; click a transition to open the radial "
            "wavefunctions of the two states.",
        ],
        "know": "Good to know",
        "know_items": [
            "All energies and transition rates are MUDIRAC's; the site adds the cascade of the muons.",
            "Only electric-dipole (E1) radiative transitions are included, as in MUDIRAC. Processes such as Auger emission or "
            "nuclear capture are not simulated, and the starting population is an assumption you choose, so the relative "
            "intensities of the lines are a model and not a prediction.",
            "When MUDIRAC cannot converge a level with the chosen settings, the site says so instead of showing an approximate result.",
        ],
        "click_el": "Click an element in the periodic table",
        "ax_energy": "Photon energy (keV)",
        "ax_counts": "Counts",
        "ex_spec": "Example: two spectra drawn together (12C and 20Ne, 1,500 muons each, start n = 5, statistical)",
        "ex_sim": "Example: one muon of 20Ne falls from 5g to 1s while the spectrum builds up",
        "lv": "Energy levels",
        "sp": "Spectrum",
    },
    "HE": {
        "title": "מה אפשר לעשות באתר",
        "close": "סגירה",
        "intro": "האתר מדמה איך מיואון שלילי שנלכד באטום יורד ברמות האנרגיה של האטום המיואוני, ואת קרני ה-X שהוא פולט בדרך. "
                 "האנרגיות ושיעורי המעברים מגיעים מ-MUDIRAC, פותר של משוואת דיראק הרדיאלית "
                 "(Sturniolo &amp; Hillier, X-Ray Spectrometry 2021).",
        "s1": "1. יצירת ספקטרום עם ההגדרות שבחרת",
        "s1_items": [
            "בוחרים את היסוד בטבלה המחזורית (עד Z = 111) ואת האיזוטופ, או ממוצע טבעי.",
            "בוחרים את מודל הגרעין (התפלגות מטען Fermi דו-פרמטרית, כדור אחיד או מטען נקודתי), את רמת ההתחלה n "
            "(2 עד 8) ואת פיזור המיואונים על תתי-הרמות שלה: סטטיסטי, אחיד או תת-רמה אחת שנבחרה (דלתא).",
            "קובעים את מספר המיואונים, ומפעילים או מכבים את שני התיקונים: קיטוב הריק (Uehling) ומיסוך אלקטרוני. "
            "הרתע הגרעיני תמיד נכלל.",
            "לוחצים על כפתור היצירה: MUDIRAC מחשב כל רמה שהמיואונים עוברים בה, והספקטרום מופיע.",
        ],
        "s2": "2. צפייה בספקטרום והשוואה לספקטרומים אחרים",
        "s2_items": [
            "כל ספקטרום הוא לשונית בצד שמאל. מסמנים את הלשוניות להצגה: הן מצוירות יחד או זו מתחת לזו. "
            "אפשר לגרור לשונית כדי לשנות סדר, ללחוץ על עיגול הצבע כדי לשנות צבע, ולהשתמש באייקונים לעריכה, שכפול ומחיקה.",
            "אפשר להשתמש בציר לוגריתמי, בעוצמה יחסית ובמחוון עובי העמודות. מגדילים בגלגלת העכבר, גוררים כדי להזיז, "
            "ולחיצה כפולה מחזירה לתצוגה המלאה.",
            "מעבירים את העכבר מעל עמודה כדי לראות את האנרגיות המדויקות של הקווים שבתוכה וכמה פוטונים יש לכל אחד.",
        ],
        "s3": "3. צפייה בסימולציה לצד הספקטרום הנבנה",
        "s3_items": [
            "כשיש פחות מ-5,000 מיואונים אפשר ללחוץ על כפתור ההפעלה בלשונית. בצד שמאל המיואון יורד מרמה לרמה ופולט פוטון "
            "בכל צעד, ובצד ימין הספקטרום נבנה פוטון אחר פוטון.",
            "אפשר לשלוט במהירות, לעבור ממעבר למעבר, או לקפוץ על ציר הזמן (קטע אחד לכל מיואון).",
            "מעבירים את העכבר מעל רמה כדי לראות למטה את יחסי ההסתעפות של הדעיכה שלה, ולוחצים על מעבר כדי לפתוח את "
            "פונקציות הגל הרדיאליות של שני המצבים.",
        ],
        "know": "כדאי לדעת",
        "know_items": [
            "כל האנרגיות ושיעורי המעברים הם של MUDIRAC; האתר מוסיף את מפל המיואונים.",
            "נכללים רק מעברי קרינה של דיפול חשמלי (E1), כמו ב-MUDIRAC. תהליכים כמו פליטת Auger או לכידה גרעינית אינם "
            "מדומים, ואכלוס ההתחלה הוא הנחה שאתה בוחר, ולכן העוצמות היחסיות של הקווים הן מודל ולא חיזוי.",
            "כש-MUDIRAC לא מצליח להתכנס לרמה עם ההגדרות שנבחרו, האתר אומר זאת במקום להציג תוצאה מקורבת.",
        ],
        "click_el": "לוחצים על יסוד בטבלה המחזורית",
        "ax_energy": "אנרגיית פוטון (keV)",
        "ax_counts": "ספירות",
        "ex_spec": "דוגמה: שני ספקטרומים מצוירים יחד (12C ו-20Ne, 1,500 מיואונים לכל אחד, התחלה n = 5, סטטיסטי)",
        "ex_sim": "דוגמה: מיואון אחד של 20Ne יורד מ-5g ל-1s בזמן שהספקטרום נבנה",
        "lv": "רמות אנרגיה",
        "sp": "ספקטרום",
    },
}

_CSS = """<style>
.mh{font-family:'Rubik','Segoe UI',Arial,sans-serif;color:#0f172a;line-height:1.55;font-size:15px}
.mh h1{font-size:24px;margin:0 0 8px 0;color:#0f4c81}
.mh h2{font-size:18px;margin:26px 0 8px 0;color:#0f4c81;border-bottom:2px solid #dbe5f0;padding-bottom:4px}
.mh p{margin:0 0 10px 0}
.mh ul{margin:6px 0 12px 0;padding-inline-start:22px}.mh li{margin:4px 0}
.mh .fig{margin:12px 0 4px 0;padding:12px;background:#f8fafc;border:1px solid #dbe5f0;border-radius:10px;direction:ltr}
.mh .cap{font-size:13px;color:#475569;margin:0 0 10px 0}
.mh svg{max-width:100%;height:auto;display:block;margin:0 auto}
.mh .row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start;justify-content:center}
.mh .box{min-width:112px;text-align:center}
.mh .box .l{font-size:12px;font-weight:600;margin-bottom:3px}
.mh .box .v{background:#e8edf3;border-radius:7px;padding:5px 10px;font-size:13px}
.mh .cb{display:flex;align-items:center;gap:6px;font-size:12.5px;margin:2px 0;text-align:start}
.mh .cb i{width:13px;height:13px;border-radius:3px;background:#0f4c81;display:inline-block;position:relative}
.mh .cb i:after{content:'';position:absolute;left:4px;top:1px;width:3px;height:7px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(40deg)}
.mh .go{margin-top:10px;display:inline-block;background:#0f4c81;color:#fff;border-radius:7px;padding:6px 18px;font-size:13px;font-weight:600}
.mh .note{background:#f1f5f9;border-inline-start:4px solid #0f4c81;border-radius:6px;padding:8px 14px;margin-top:6px}
</style>"""


def _fmt(e):
    return f"{e:.2f}" if e < 100 else f"{e:.1f}"


def _spectrum_svg(lang, spectra):
    """Two real spectra drawn together, 2 keV columns, linear counts."""
    t = TEXT[lang]
    W, H, ml, mr, mt, mb = 600, 250, 62, 16, 14, 46
    xmax, binw = 230.0, 2.0
    cols = {"C": "#2563eb", "Ne": "#f97316"}
    agg = {}
    for el, lines in spectra.items():
        d = {}
        for e, c in lines:
            k = int(e // binw)
            d[k] = d.get(k, 0) + c
        agg[el] = d
    ymax = max(max(d.values()) for d in agg.values()) * 1.08
    pw, ph = W - ml - mr, H - mt - mb
    sx = lambda e: ml + e / xmax * pw
    sy = lambda c: mt + ph - c / ymax * ph
    o = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif">',
         f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="#fff" stroke="#cbd5e1"/>']
    for tick in range(0, 201, 50):
        x = sx(tick)
        o.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt + ph}" stroke="#e2e8f0" stroke-dasharray="3,3"/>')
        o.append(f'<text x="{x:.1f}" y="{mt + ph + 15}" font-size="11" text-anchor="middle" fill="#334155">{tick}</text>')
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        c = ymax / 1.08 * frac
        y = sy(c)
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + pw}" y2="{y:.1f}" stroke="#e2e8f0" stroke-dasharray="3,3"/>')
        o.append(f'<text x="{ml - 6}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="#334155">{int(round(c, -1))}</text>')
    for el, d in agg.items():
        for k, c in d.items():
            x0 = sx(k * binw)
            w = max(2.2, pw * binw / xmax * 0.9)
            o.append(f'<rect x="{x0:.1f}" y="{sy(c):.1f}" width="{w:.1f}" height="{mt + ph - sy(c):.1f}" fill="{cols[el]}" opacity="0.85"/>')
    o.append(f'<text x="{ml + pw / 2}" y="{H - 8}" font-size="12" text-anchor="middle" fill="#0f172a" style="unicode-bidi:isolate">{t["ax_energy"]}</text>')
    o.append(f'<text transform="translate(14,{mt + ph / 2}) rotate(-90)" font-size="12" text-anchor="middle" fill="#0f172a">{t["ax_counts"]}</text>')
    lx = ml + pw - 120
    for i, (el, name) in enumerate((("C", "¹²C"), ("Ne", "²⁰Ne"))):
        o.append(f'<rect x="{lx}" y="{mt + 8 + i * 18}" width="14" height="10" fill="{cols[el]}" opacity="0.85"/>'
                 f'<text x="{lx + 20}" y="{mt + 17 + i * 18}" font-size="12" fill="#0f172a">{name}</text>')
    o.append("</svg>")
    return "".join(o)


def _simulation_svg(lang, spectra, example):
    """Level diagram with the (real) path of one muon and, on the right, a spectrum that is still being built."""
    t = TEXT[lang]
    W, H = 640, 300
    lx0, rows = 70, 5
    pos = lambda n, l: (lx0 + l * 58, 262 - (n - 1) * 52)
    o = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif">',
         '<defs><marker id="mhar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#0f4c81"/></marker></defs>',
         f'<text x="{lx0 + 130}" y="14" font-size="12" font-weight="600" text-anchor="middle" fill="#0f172a" style="unicode-bidi:isolate">{t["lv"]}</text>',
         f'<text x="{W - 135}" y="14" font-size="12" font-weight="600" text-anchor="middle" fill="#0f172a" style="unicode-bidi:isolate">{t["sp"]}</text>']
    for n in range(1, rows + 1):
        y = 262 - (n - 1) * 52
        o.append(f'<text x="14" y="{y + 4}" font-size="11" fill="#475569">n = {n}</text>')
        for l in range(n):
            x, _ = pos(n, l)
            o.append(f'<line x1="{x - 18}" y1="{y}" x2="{x + 18}" y2="{y}" stroke="#334155" stroke-width="2"/>')
    for l, name in enumerate("spdfg"):
        o.append(f'<text x="{pos(5, l)[0]}" y="{286}" font-size="11" text-anchor="middle" fill="#475569">{name}</text>')
    lvl = lambda name: (int(name[0]), "spdfgh".index(name[1]))
    for i, (a, b, e) in enumerate(example):
        (na, la), (nb, lb) = lvl(a), lvl(b)
        xa, ya = pos(na, la)
        xb, yb = pos(nb, lb)
        o.append(f'<line x1="{xa}" y1="{ya + 3}" x2="{xb + (6 if xb < xa else -6)}" y2="{yb - 4}" stroke="#0f4c81" stroke-width="2" marker-end="url(#mhar)"/>')
        o.append(f'<text x="{(xa + xb) / 2 + 10}" y="{(ya + yb) / 2 - 4}" font-size="11" font-weight="600" fill="#0f4c81">{_fmt(e)} keV</text>')
    # the muon, between the 2nd and 3rd level of the path
    xm, ym = pos(*lvl(example[2][0]))
    o.append(f'<circle cx="{xm}" cy="{ym - 9}" r="9" fill="#c1121f" stroke="#fff" stroke-width="1.5"/>'
             f'<text x="{xm}" y="{ym - 5.5}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">μ⁻</text>')
    # spectrum of Ne, partly built: the photons of this muon are solid, the others pale
    ne = spectra["Ne"]
    px0, px1, py1, py0 = 395, 625, 262, 40
    xmax, binw = 230.0, 2.0
    d = {}
    for e, c in ne:
        d[int(e // binw)] = d.get(int(e // binw), 0) + c
    ymax = max(d.values())
    own = {int(e // binw) for _, _, e in example}
    o.append(f'<rect x="{px0}" y="{py0}" width="{px1 - px0}" height="{py1 - py0}" fill="#fff" stroke="#cbd5e1"/>')
    for k, c in d.items():
        x = px0 + k * binw / xmax * (px1 - px0)
        h = c / ymax * (py1 - py0 - 6)
        mine = k in own
        o.append(f'<rect x="{x:.1f}" y="{py1 - h:.1f}" width="2.4" height="{h:.1f}" fill="{"#f97316" if mine else "#fcd9bd"}"/>')
    for tick in (0, 100, 200):
        x = px0 + tick / xmax * (px1 - px0)
        o.append(f'<text x="{x:.1f}" y="{py1 + 14}" font-size="10" text-anchor="middle" fill="#334155">{tick}</text>')
    o.append(f'<text x="{(px0 + px1) / 2}" y="{py1 + 28}" font-size="11" text-anchor="middle" fill="#0f172a" style="unicode-bidi:isolate">{t["ax_energy"]}</text>')
    o.append("</svg>")
    return "".join(o)


def _table_svg():
    """A small, schematic periodic table with neon marked (the element of the examples)."""
    cell, gap = 13, 2
    rows = {1: [1, 18], 2: [1, 2] + list(range(13, 19)), 3: [1, 2] + list(range(13, 19))}
    for r in (4, 5, 6, 7):
        rows[r] = list(range(1, 19))
    W, H = 18 * (cell + gap), 7 * (cell + gap)
    o = [f'<svg viewBox="0 0 {W} {H}" width="{W * 1.5:.0f}" height="{H * 1.5:.0f}" xmlns="http://www.w3.org/2000/svg">']
    for r, cs in rows.items():
        for c in cs:
            hot = (r == 2 and c == 18)
            o.append(f'<rect x="{(c - 1) * (cell + gap)}" y="{(r - 1) * (cell + gap)}" width="{cell}" height="{cell}" rx="2" '
                     f'fill="{"#0f4c81" if hot else "#ffffff"}" stroke="{"#0f4c81" if hot else "#cbd5e1"}"/>')
            if hot:
                o.append(f'<text x="{(c - 1) * (cell + gap) + cell / 2}" y="{(r - 1) * (cell + gap) + cell - 3.5}" font-size="7.5" '
                         f'font-family="Arial,sans-serif" font-weight="700" text-anchor="middle" fill="#ffffff">Ne</text>')
    o.append("</svg>")
    return "".join(o)


def help_html(lang, labels):
    """The whole guide for one language. labels: the site's own captions of the create window (so they always match it)."""
    lang = "HE" if lang == "HE" else "EN"
    t = TEXT[lang]
    spectra, example = _load_spectra()
    L = lambda k: _html.escape(labels.get(k, k))
    boxes = [("muon_count", "10"), ("distribution_label", L("dist_stat_short")), ("initial_level_row_label", "n = 5"),
             ("isotope_label", L("isotope_natural")), ("nuclear_model", "FERMI2")]
    mock = "".join(f'<div class="box"><div class="l">{L(k)}</div><div class="v">{v}</div></div>' for k, v in boxes)
    mock += ('<div class="box" style="min-width:190px"><div class="cb"><i></i>' + L("qed_label") + '</div>'
             '<div class="cb"><i></i>' + L("screening_label") + '</div></div>')

    def ul(items):
        return "<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"

    body = [
        _CSS, f'<div class="mh" dir="{"rtl" if lang == "HE" else "ltr"}">', f'<h1>{t["title"]}</h1>', f'<p>{t["intro"]}</p>',
        f'<h2>{t["s1"]}</h2>', ul(t["s1_items"]),
        f'<div class="fig"><div style="text-align:center;margin-bottom:8px">{_table_svg()}<div class="cap">{t["click_el"]}</div></div>'
        f'<div class="row">{mock}</div><div style="text-align:center"><span class="go">{L("create_spec_sim")}</span></div></div>',
        f'<h2>{t["s2"]}</h2>', ul(t["s2_items"]),
        f'<div class="fig">{_spectrum_svg(lang, spectra)}</div><p class="cap">{t["ex_spec"]}</p>',
        f'<h2>{t["s3"]}</h2>', ul(t["s3_items"]),
        f'<div class="fig">{_simulation_svg(lang, spectra, example)}</div><p class="cap">{t["ex_sim"]}</p>',
        f'<h2>{t["know"]}</h2>', f'<div class="note">{ul(t["know_items"])}</div>', "</div>",
    ]
    return "".join(body)
