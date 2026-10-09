"""The help guide of the site (opened with the "?" button next to the language switch), in Hebrew and English.

It shows how to move between the three main screens of the site as a triangle of pictures: create a spectrum, view and
compare spectra, interactive simulation. Each picture is a real screenshot of the site (Hebrew or English, as chosen); the
buttons that lead to another screen are circled in bright green, like a brush stroke, and every arrow starts at such a circle
and ends at the screen it leads to. Drawn at run time as one inline SVG; the screenshots are in help_guide_images.py (made by
build_help_images.py).
"""
import html as _html
import math

import help_guide_images as _img

TEXT = {
    "EN": {
        "tab_info": "About the project",
        "tab_guide": "Site guide",
        "close": "Close",
        "no_report": "The project report is not available.",
        "info_html": "<h2>About the project</h2><p>When a negative muon is captured by an atom, it descends through the energy levels to the ground state and emits X-rays whose energies identify the element. The MUDIRAC code solves the radial Dirac equation and computes the energies and transition rates of these lines, but it does not compute how many muons reach each level, so it does not predict line intensities.</p><p>This site runs MUDIRAC and builds on its results a model of the muon cascade (a random chain of radiative transitions, by Monte Carlo) and the X-ray spectrum, for several assumptions on the initial state of the muon. All energies and transition rates come from MUDIRAC; settings it cannot compute are disabled.</p><p class=\"ref\">The MUDIRAC article: S. Sturniolo and A. Hillier, <i>Mudirac: A Dirac equation solver for elemental analysis with muonic X-rays</i>, X-Ray Spectrom. 50, 180&ndash;196 (2021). <a href=\"https://doi.org/10.1002/xrs.3212\" target=\"_blank\" rel=\"noopener noreferrer\">https://doi.org/10.1002/xrs.3212</a></p>",
        "intro": "The site simulates the X-ray cascade of a negative muon captured by an atom. The energies and the transition "
                 "probabilities come from MUDIRAC, a solver of the radial Dirac equation. "
                 "The three main screens lead to each other: press the circled button to reach the screen its arrow points to.",
        "names": ["Create a spectrum", "View and compare spectra", "Interactive simulation"],
    },
    "HE": {
        "tab_info": "על הפרויקט",
        "tab_guide": "התמצאות באתר",
        "close": "סגירה",
        "no_report": "דוח הפרויקט אינו זמין.",
        "info_html": "<h2>על הפרויקט</h2><p>כאשר מיואון שלילי נלכד באטום, הוא יורד ברמות האנרגיה אל מצב היסוד ופולט קרני X שאנרגייתן מאפיינת את היסוד. הפותר MUDIRAC פותר את משוואת דיראק הרדיאלית ומחשב את האנרגיות ואת קצבי המעבר של הקווים האלה, אך אינו מחשב כמה מיואונים מגיעים לכל רמה, ולכן אינו מנבא את עוצמות הקווים.</p><p>האתר מריץ את MUDIRAC ומחשב על בסיס תוצאותיו את מפל המיואון (שרשרת מקרית של מעברים קרינתיים, בשיטת מונטה-קרלו) ואת ספקטרום קרני X, עבור כמה הנחות על המצב ההתחלתי של המיואון. כל האנרגיות וקצבי המעבר מגיעים מ-MUDIRAC, והגדרות שהוא אינו מסוגל לחשב מושבתות באתר.</p><p class=\"ref\">המאמר של MUDIRAC: <span dir=\"ltr\">S. Sturniolo and A. Hillier, <i>Mudirac: A Dirac equation solver for elemental analysis with muonic X-rays</i>, X-Ray Spectrom. 50, 180&ndash;196 (2021). <a href=\"https://doi.org/10.1002/xrs.3212\" target=\"_blank\" rel=\"noopener noreferrer\">https://doi.org/10.1002/xrs.3212</a></span></p>",
        "intro": "האתר מדמה את מפל קרני ה-X של מיואון שלילי שנלכד באטום. האנרגיות והסתברויות המעברים מגיעות מ-MUDIRAC, "
                 "פותר של משוואת דיראק הרדיאלית. "
                 "שלושת המסכים המרכזיים מובילים זה לזה: לוחצים על הלחצן המסומן כדי להגיע למסך שאליו מצביע החץ שלו.",
        "names": ["יצירת ספקטרום", "צפייה והשוואת ספקטרומים", "סימולציה אינטראקטיבית"],
    },
}

_CSS = """<style>
.mh{font-family:'Rubik','Segoe UI',Arial,sans-serif;color:#0f172a;line-height:1.55;font-size:15px}
.mh h1{font-size:25px;margin:0 0 12px 0;color:#0f4c81}
.mh p{margin:0 0 10px 0}
.mh a{color:#0f4c81;word-break:break-all}
.mh .fig{margin:14px 0 6px 0;padding:10px;background:#f8fafc;border:1px solid #dbe5f0;border-radius:10px;direction:ltr}
.mh svg{max-width:100%;height:auto;display:block;margin:0 auto}
</style>"""

_GREEN = "#16a34a"            # the green of the ellipses
_SC = 540.0 / 1100.0          # the pictures are 1100 px wide and drawn 540 wide


def _brush(cx, cy, rx, ry, phase=0.0):
    """An exact ellipse around a button (fresh green, on a thin white halo so that it stands out from the picture)."""
    return (f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="none" stroke="#ffffff" stroke-width="9" opacity="0.85"/>'
            f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="none" stroke="{_GREEN}" stroke-width="4.5"/>')


def _ring(im, key, x, y, pad_x=11, pad_y=10):
    """Centre and radii (in the figure) of the circle around the button box im[key] of the picture drawn at (x, y)."""
    bx0, by0, bx1, by1 = im[key]
    return (x + (bx0 + bx1) / 2 * _SC, y + (by0 + by1) / 2 * _SC, (bx1 - bx0) / 2 * _SC + pad_x, (by1 - by0) / 2 * _SC + pad_y)


def _edge(ring, deg, gap=8):
    """A point just outside the circle , in the direction deg (0 = right, 90 = down)."""
    cx, cy, rx, ry = ring
    a = math.radians(deg)
    return cx + (rx + gap) * math.cos(a), cy + (ry + gap) * math.sin(a)


def _cycle_svg(lang, labels):
    t = TEXT[lang]
    keys = ["create", "spectra", "sim"]
    imgs = [_img.IMAGES[(lang, k)] for k in keys]
    pos = [(330, 36), (650, 440), (10, 440)]                  # top, bottom right, bottom left
    W, H = 1200, 740
    o = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif">',
         '<defs><marker id="mhar2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#0f4c81"/></marker></defs>']
    sizes = []
    for i, (im, (x, y)) in enumerate(zip(imgs, pos)):
        w, h = im["w"] * _SC, im["h"] * _SC
        sizes.append((x, y, w, h))
        o.append(f'<rect x="{x - 1}" y="{y - 1}" width="{w + 2:.1f}" height="{h + 2:.1f}" rx="7" fill="#fff" stroke="#94a3b8" stroke-width="1.5"/>')
        o.append(f'<image href="data:image/webp;base64,{im["b64"]}" x="{x}" y="{y}" width="{w:.1f}" height="{h:.1f}"/>')
        # the title keeps its own reading direction, so that in Hebrew the number and its period stand at the right end
        o.append(f'<text x="{x + w / 2:.1f}" y="{y + h + 26:.1f}" font-size="19" font-weight="700" text-anchor="middle" fill="#0f172a" '
                 f'direction="{"rtl" if lang == "HE" else "ltr"}" style="unicode-bidi:isolate;direction:{"rtl" if lang == "HE" else "ltr"}">'
                 f'{_html.escape(t["names"][i])}</text>')
    (x1, y1, w1, h1), (x2, y2, w2, h2), (x3, y3, w3, h3) = sizes
    # the circles: the create button (1), the play button of a tab (2), "Create New Spectrum" and the two display buttons (3)
    r1 = _ring(imgs[0], "box", x1, y1)
    r2 = _ring(imgs[1], "box", x2, y2, 9, 9)
    r3a = _ring(imgs[2], "box", x3, y3)
    r3b = _ring(imgs[2], "box2", x3, y3, 12, 10)
    for k, r in enumerate((r1, r2, r3a, r3b)):
        o.append(_brush(*r, phase=0.9 * k))
    arrow = 'fill="none" stroke="#0f4c81" stroke-width="5" stroke-linecap="round" marker-end="url(#mhar2)"'
    # every arrow starts at its circle and ends at the screen it leads to
    sx, sy = _edge(r1, 55)                                            # 1 -> 2
    ex, ey = x2 + w2 * 0.62, y2 - 12
    o.append(f'<path d="M {sx:.0f} {sy:.0f} C {sx + 60:.0f} {sy + 70:.0f} {ex + 35:.0f} {ey - 130:.0f} {ex:.0f} {ey:.0f}" {arrow}/>')
    sx, sy = _edge(r2, 180)                                           # 2 -> 3
    ex, ey = x3 + w3 + 14, sy
    o.append(f'<path d="M {sx:.0f} {sy:.0f} L {ex:.0f} {ey:.0f}" {arrow}/>')
    sx, sy = _edge(r3a, 270)                                          # 3 -> 1  ("Create New Spectrum")
    ex, ey = x1 - 14, y1 + 150
    o.append(f'<path d="M {sx:.0f} {sy:.0f} C {sx - 35:.0f} {sy - 130:.0f} {ex - 170:.0f} {ey + 40:.0f} {ex:.0f} {ey:.0f}" {arrow}/>')
    sx, sy = _edge(r3b, 300)                                          # 3 -> 2  (the two display buttons)
    ex, ey = x2 + w2 * 0.2, y2 - 12
    o.append(f'<path d="M {sx:.0f} {sy:.0f} C {sx + 15:.0f} {sy - 95:.0f} {ex - 25:.0f} {ey - 100:.0f} {ex:.0f} {ey:.0f}" {arrow}/>')
    o.append("</svg>")
    return "".join(o)


def help_html(lang, labels):
    """The "site guide" (map of the three screens) for one language: intro + figure. labels: the site's own button
    captions (so they always match the site). Used in the guide tab of the "?" window and on the empty start page."""
    lang = "HE" if lang == "HE" else "EN"
    t = TEXT[lang]
    return "".join([
        _CSS, f'<div class="mh" dir="{"rtl" if lang == "HE" else "ltr"}">',
        f'<p>{t["intro"]}</p>',
        f'<div class="fig">{_cycle_svg(lang, labels)}</div>',
        "</div>",
    ])

def start_page_html(lang, labels):
    """The site guide for the start page (no spectrum yet): the text beside the map (Hebrew: right of it, English: left
    of it), and the map scaled to the height of its frame, so that the whole page fits without scrolling."""
    lang = "HE" if lang == "HE" else "EN"
    t = TEXT[lang]
    css = """<style>
html,body{margin:0;height:100%;background:transparent;overflow:hidden}
.side{display:flex;align-items:center;gap:26px;height:100%;box-sizing:border-box;padding:0 6px;
      font-family:'Rubik','Segoe UI',Arial,sans-serif;color:#0f172a}
.side p{flex:0 0 21%;margin:0;font-size:13.5px;line-height:1.6}
.side .fig{flex:1 1 auto;min-width:0;height:100%;display:flex;align-items:center;justify-content:center;
      box-sizing:border-box;padding:8px;background:#f8fafc;border:1px solid #dbe5f0;border-radius:10px;direction:ltr}
.side svg{width:100%;height:100%;display:block}   /* as large as the box allows; the drawing keeps its proportions */
</style>"""
    return "".join([
        css, f'<div class="side" dir="{"rtl" if lang == "HE" else "ltr"}">',
        f'<p>{t["intro"]}</p>',
        f'<div class="fig">{_cycle_svg(lang, labels)}</div>',
        "</div>",
    ])