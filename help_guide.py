"""The help guide of the site (opened with the "?" button next to the language switch), in Hebrew and English.

It shows how to move between the three main screens of the site as a triangle of pictures: create a spectrum, view and
compare spectra, interactive simulation. Each picture is a real screenshot of the site (Hebrew or English, as chosen), with the
button that leads to the next screen circled in dark green, like a brush stroke. Drawn at run time as one inline SVG; the
screenshots are in help_guide_images.py (made by build_help_images.py).
"""
import html as _html
import math

import help_guide_images as _img

TEXT = {
    "EN": {
        "title": "How to move around the site",
        "close": "Close",
        "cite": "How to cite this article:",
        "intro": "The site simulates the X-ray cascade of a negative muon captured by an atom. The energies and the transition "
                 "probabilities come from MUDIRAC, a solver of the radial Dirac equation (the article above). "
                 "The three main screens follow each other in a circle: press the circled button to reach the next one.",
        "names": ["1. Create a spectrum", "2. View and compare spectra", "3. Interactive simulation"],
        "cap": [
            "Choose the element in the periodic table and the settings, then press the circled button to create the spectrum.",
            "Every spectrum is a tab on the left; tick the tabs to compare them. Press the circled play button of a tab to watch its simulation.",
            "The muon falls from level to level next to the growing spectrum. The circled button opens the window for a new spectrum.",
        ],
        "back": "To return from the simulation to the spectra view, press",
        "know": "Good to know",
        "know_items": [
            "All energies and transition probabilities are MUDIRAC's; the site adds the cascade of the muons.",
            "Only radiative electric-dipole (E1) transitions are simulated, and the starting population is your choice, so the "
            "relative intensities of the lines are a model rather than a prediction.",
        ],
    },
    "HE": {
        "title": "איך מסתובבים באתר",
        "close": "סגירה",
        "cite": "ציטוט המאמר:",
        "intro": "האתר מדמה את מפל קרני ה-X של מיואון שלילי שנלכד באטום. האנרגיות והסתברויות המעברים מגיעות מ-MUDIRAC, "
                 "פותר של משוואת דיראק הרדיאלית (המאמר שלמעלה). "
                 "שלושת המסכים המרכזיים עוקבים זה אחר זה במעגל: לוחצים על הלחצן המסומן כדי להגיע למסך הבא.",
        "names": ["1. יצירת ספקטרום", "2. צפייה והשוואת ספקטרומים", "3. סימולציה אינטראקטיבית"],
        "cap": [
            "בוחרים את היסוד בטבלה המחזורית ואת ההגדרות, ולוחצים על הלחצן המסומן כדי ליצור את הספקטרום.",
            "כל ספקטרום הוא לשונית בצד שמאל; מסמנים לשוניות כדי להשוות ביניהן. לוחצים על כפתור ההפעלה המסומן של לשונית כדי לצפות בסימולציה שלה.",
            "המיואון יורד מרמה לרמה לצד הספקטרום הנבנה. הלחצן המסומן פותח את החלון ליצירת ספקטרום חדש.",
        ],
        "back": "כדי לחזור מהסימולציה לתצוגת הספקטרומים, לוחצים על",
        "know": "כדאי לדעת",
        "know_items": [
            "כל האנרגיות והסתברויות המעברים הן של MUDIRAC; האתר מוסיף את מפל המיואונים.",
            "מדומים רק מעברי קרינה של דיפול חשמלי (E1), ואכלוס ההתחלה הוא בחירה שלך, ולכן העוצמות היחסיות של הקווים "
            "הן מודל ולא חיזוי.",
        ],
    },
}

CITATION = ("Sturniolo S, Hillier A. Mudirac: A Dirac equation solver for elemental analysis with muonic X-rays. "
            "<i>X-Ray Spectrom.</i> 2021;50:180–196. "
            '<a href="https://doi.org/10.1002/xrs.3212" target="_blank" rel="noopener noreferrer">https://doi.org/10.1002/xrs.3212</a>')

_CSS = """<style>
.mh{font-family:'Rubik','Segoe UI',Arial,sans-serif;color:#0f172a;line-height:1.55;font-size:15px}
.mh h1{font-size:25px;margin:0 0 12px 0;color:#0f4c81}
.mh h2{font-size:18px;margin:24px 0 8px 0;color:#0f4c81;border-bottom:2px solid #dbe5f0;padding-bottom:4px}
.mh p{margin:0 0 10px 0}
.mh a{color:#0f4c81;word-break:break-all}
.mh .cite{background:#f1f5f9;border-inline-start:4px solid #0f4c81;border-radius:6px;padding:10px 16px;margin:0 0 14px 0;font-size:16px}
.mh .cite b{display:block;margin-bottom:2px}
.mh .cite .en{direction:ltr;text-align:left;display:block}
.mh .fig{margin:14px 0 6px 0;padding:10px;background:#f8fafc;border:1px solid #dbe5f0;border-radius:10px;direction:ltr}
.mh svg{max-width:100%;height:auto;display:block;margin:0 auto}
.mh ol{margin:10px 0 8px 0;padding-inline-start:26px}.mh li{margin:5px 0}
.mh ul{margin:6px 0 12px 0;padding-inline-start:22px}
.mh .note{background:#f1f5f9;border-inline-start:4px solid #0f4c81;border-radius:6px;padding:6px 14px;margin-top:6px}
.mh .btn{display:inline-block;background:#0f4c81;color:#fff;border-radius:6px;padding:1px 10px;font-size:13.5px;margin:0 3px}
</style>"""

_GREEN = "#14532d"
_SC = 540.0 / 1100.0          # the pictures are 1100 px wide and drawn 540 wide


def _brush(cx, cy, rx, ry, phase=0.0):
    """A hand-drawn looking loop (dark green, brush stroke): a slightly spiralling ellipse that overshoots its start, drawn
    twice with different widths so that the stroke has some body."""
    paths = []
    for k, (sw, op, dp) in enumerate(((6.5, 0.93, 0.0), (3.0, 0.55, 0.55))):
        pts = []
        t0 = -0.35 * math.pi + dp + phase
        t1 = t0 + 2 * math.pi * 1.07
        n = 70
        for i in range(n + 1):
            t = t0 + (t1 - t0) * i / n
            grow = 1.0 + 0.09 * (t - t0) / (2 * math.pi) + 0.025 * math.sin(3 * t + phase)
            pts.append((cx + rx * grow * math.cos(t), cy + ry * grow * math.sin(t)))
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        paths.append(f'<path d="{d}" fill="none" stroke="{_GREEN}" stroke-width="{sw}" stroke-linecap="round" '
                     f'stroke-linejoin="round" opacity="{op}"/>')
    return "".join(paths)


def _cycle_svg(lang, labels):
    t = TEXT[lang]
    keys = ["create", "spectra", "sim"]
    imgs = [_img.IMAGES[(lang, k)] for k in keys]
    pos = [(330, 36), (650, 440), (10, 440)]                  # top, bottom right, bottom left
    W, H = 1200, 740
    o = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif">',
         '<defs><marker id="mhar2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#0f4c81"/></marker></defs>']
    centres = []
    for i, (im, (x, y)) in enumerate(zip(imgs, pos)):
        w, h = im["w"] * _SC, im["h"] * _SC
        o.append(f'<rect x="{x - 1}" y="{y - 1}" width="{w + 2:.1f}" height="{h + 2:.1f}" rx="7" fill="#fff" stroke="#94a3b8" stroke-width="1.5"/>')
        o.append(f'<image href="data:image/webp;base64,{im["b64"]}" x="{x}" y="{y}" width="{w:.1f}" height="{h:.1f}"/>')
        o.append(f'<circle cx="{x + 4}" cy="{y + 4}" r="15" fill="#0f4c81" stroke="#fff" stroke-width="2"/>'
                 f'<text x="{x + 4}" y="{y + 10}" font-size="17" font-weight="700" text-anchor="middle" fill="#fff">{i + 1}</text>')
        o.append(f'<text x="{x + w / 2:.1f}" y="{y + h + 26:.1f}" font-size="19" font-weight="700" text-anchor="middle" fill="#0f172a" '
                 f'style="unicode-bidi:isolate">{_html.escape(t["names"][i])}</text>')
        bx0, by0, bx1, by1 = im["box"]
        cx, cy = x + (bx0 + bx1) / 2 * _SC, y + (by0 + by1) / 2 * _SC
        rx, ry = (bx1 - bx0) / 2 * _SC + 11, (by1 - by0) / 2 * _SC + 10
        o.append(_brush(cx, cy, rx, ry, phase=0.9 * i))
        centres.append((x, y, w, h))
    (x1, y1, w1, h1), (x2, y2, w2, h2), (x3, y3, w3, h3) = centres
    arrow = 'fill="none" stroke="#0f4c81" stroke-width="5" stroke-linecap="round" marker-end="url(#mhar2)"'
    # 1 -> 2 : from the right edge of the top picture down to the top of the bottom-right one
    o.append(f'<path d="M {x1 + w1 + 14:.0f} {y1 + 70:.0f} C {x1 + w1 + 120:.0f} {y1 + 90:.0f} {x2 + w2 * 0.75:.0f} {y2 - 120:.0f} {x2 + w2 * 0.55:.0f} {y2 - 12:.0f}" {arrow}/>')
    # 2 -> 3 : between the two bottom pictures
    o.append(f'<path d="M {x2 - 10:.0f} {y2 + h2 / 2:.0f} L {x3 + w3 + 16:.0f} {y2 + h2 / 2:.0f}" {arrow}/>')
    # 3 -> 1 : from the top of the bottom-left picture up to the left edge of the top one
    o.append(f'<path d="M {x3 + w3 * 0.45:.0f} {y3 - 12:.0f} C {x3 + w3 * 0.25:.0f} {y3 - 120:.0f} {x1 - 120:.0f} {y1 + 90:.0f} {x1 - 14:.0f} {y1 + 70:.0f}" {arrow}/>')
    lab = lambda s: _html.escape(s)
    o.append(f'<text x="{x1 + w1 + 120:.0f}" y="{y1 + 150:.0f}" font-size="16" font-weight="600" fill="#0f4c81" text-anchor="middle" '
             f'style="unicode-bidi:isolate">{lab(labels["create_spec_sim"])}</text>')
    o.append(f'<text x="{x1 - 120:.0f}" y="{y1 + 150:.0f}" font-size="16" font-weight="600" fill="#0f4c81" text-anchor="middle" '
             f'style="unicode-bidi:isolate">{lab(labels["add_spectrum_top"])}</text>')
    o.append("</svg>")
    return "".join(o)


def help_html(lang, labels):
    """The whole guide for one language. labels: the site's own captions of the buttons (so they always match the site)."""
    lang = "HE" if lang == "HE" else "EN"
    t = TEXT[lang]
    e = lambda s: _html.escape(labels.get(s, s))
    cap = "".join(f"<li>{c}</li>" for c in t["cap"])
    know = "<ul>" + "".join(f"<li>{x}</li>" for x in t["know_items"]) + "</ul>"
    return "".join([
        _CSS, f'<div class="mh" dir="{"rtl" if lang == "HE" else "ltr"}">',
        f'<h1>{t["title"]}</h1>',
        f'<div class="cite"><b>{t["cite"]}</b><span class="en">{CITATION}</span></div>',
        f'<p>{t["intro"]}</p>',
        f'<div class="fig">{_cycle_svg(lang, labels)}</div>',
        f"<ol>{cap}</ol>",
        f'<p>{t["back"]} <span class="btn">{e("return_all_btn")}</span></p>',
        f'<h2>{t["know"]}</h2><div class="note">{know}</div>',
        "</div>",
    ])
