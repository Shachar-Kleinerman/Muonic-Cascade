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
        "title": "How to move around the site",
        "close": "Close",
        "cite": "The calculations are based on MUDIRAC:",
        "intro": "The site simulates the X-ray cascade of a negative muon captured by an atom. The energies and the transition "
                 "probabilities come from MUDIRAC, a solver of the radial Dirac equation (the article above). "
                 "The three main screens lead to each other: press the circled button to reach the screen its arrow points to.",
        "names": ["1. Create a spectrum", "2. View and compare spectra", "3. Interactive simulation"],
    },
    "HE": {
        "title": "איך מסתובבים באתר",
        "close": "סגירה",
        "cite": "החישובים מתבססים על MUDIRAC:",
        "intro": "האתר מדמה את מפל קרני ה-X של מיואון שלילי שנלכד באטום. האנרגיות והסתברויות המעברים מגיעות מ-MUDIRAC, "
                 "פותר של משוואת דיראק הרדיאלית (המאמר שלמעלה). "
                 "שלושת המסכים המרכזיים מובילים זה לזה: לוחצים על הלחצן המסומן כדי להגיע למסך שאליו מצביע החץ שלו.",
        "names": ["1. יצירת ספקטרום", "2. צפייה והשוואת ספקטרומים", "3. סימולציה אינטראקטיבית"],
    },
}

CITATION = ("Sturniolo S, Hillier A. Mudirac: A Dirac equation solver for elemental analysis with muonic X-rays. "
            "<i>X-Ray Spectrom.</i> 2021;50:180–196. "
            '<a href="https://doi.org/10.1002/xrs.3212" target="_blank" rel="noopener noreferrer">https://doi.org/10.1002/xrs.3212</a>')

_CSS = """<style>
.mh{font-family:'Rubik','Segoe UI',Arial,sans-serif;color:#0f172a;line-height:1.55;font-size:15px}
.mh h1{font-size:25px;margin:0 0 12px 0;color:#0f4c81}
.mh p{margin:0 0 10px 0}
.mh a{color:#0f4c81;word-break:break-all}
.mh .cite{background:#f1f5f9;border-inline-start:4px solid #0f4c81;border-radius:6px;padding:10px 16px;margin:0 0 14px 0;font-size:16px}
.mh .cite b{display:block;margin-bottom:2px}
.mh .cite .en{direction:ltr;text-align:left;display:block}
.mh .fig{margin:14px 0 6px 0;padding:10px;background:#f8fafc;border:1px solid #dbe5f0;border-radius:10px;direction:ltr}
.mh svg{max-width:100%;height:auto;display:block;margin:0 auto}
</style>"""

_GREEN = "#22c55e"            # bright green of the circles
_GREEN_DARK = "#15803d"
_SC = 540.0 / 1100.0          # the pictures are 1100 px wide and drawn 540 wide


def _brush(cx, cy, rx, ry, phase=0.0):
    """A hand-drawn looking loop in bright green (a brush stroke): a slightly spiralling ellipse that overshoots its start,
    on a white halo so that it stands out from the picture, with a thinner darker stroke on top for body."""
    paths = []
    for sw, colour, op, dp in ((12.0, "#ffffff", 0.8, 0.0), (7.0, _GREEN, 1.0, 0.0), (2.6, _GREEN_DARK, 0.9, 0.5)):
        pts = []
        t0 = -0.35 * math.pi + dp + phase
        t1 = t0 + 2 * math.pi * 1.07
        n = 70
        for i in range(n + 1):
            t = t0 + (t1 - t0) * i / n
            grow = 1.0 + 0.09 * (t - t0) / (2 * math.pi) + 0.025 * math.sin(3 * t + phase)
            pts.append((cx + rx * grow * math.cos(t), cy + ry * grow * math.sin(t)))
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        paths.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{sw}" stroke-linecap="round" '
                     f'stroke-linejoin="round" opacity="{op}"/>')
    return "".join(paths)


def _ring(im, key, x, y, pad_x=11, pad_y=10):
    """Centre and radii (in the figure) of the circle around the button box im[key] of the picture drawn at (x, y)."""
    bx0, by0, bx1, by1 = im[key]
    return (x + (bx0 + bx1) / 2 * _SC, y + (by0 + by1) / 2 * _SC, (bx1 - bx0) / 2 * _SC + pad_x, (by1 - by0) / 2 * _SC + pad_y)


def _edge(ring, deg, gap=8):
    """A point just outside the circle (as drawn, it grows ~10 %), in the direction deg (0 = right, 90 = down)."""
    cx, cy, rx, ry = ring
    a = math.radians(deg)
    return cx + (rx * 1.12 + gap) * math.cos(a), cy + (ry * 1.12 + gap) * math.sin(a)


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
        o.append(f'<circle cx="{x + 4}" cy="{y + 4}" r="15" fill="#0f4c81" stroke="#fff" stroke-width="2"/>'
                 f'<text x="{x + 4}" y="{y + 10}" font-size="17" font-weight="700" text-anchor="middle" fill="#fff">{i + 1}</text>')
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
    # the names of the buttons stand beside the arrows (dark text on the empty space between the pictures), not on them
    lab = lambda s: _html.escape(s)
    txt = ('font-size="16" font-weight="600" fill="#0f172a" text-anchor="middle" style="unicode-bidi:isolate"')
    o.append(f'<text x="{x1 + w1 - 40:.0f}" y="{y2 - 70:.0f}" {txt}>{lab(labels["create_spec_sim"])}</text>')
    o.append(f'<text x="250" y="{y2 - 140:.0f}" {txt}>{lab(labels["add_spectrum_top"])}</text>')
    o.append(f'<text x="600" y="{y2 - 118:.0f}" {txt}>{lab(labels["return_all_btn"])}</text>')
    o.append(f'<text x="600" y="{y2 - 96:.0f}" {txt}>{lab(labels["view_current_btn"])}</text>')
    o.append("</svg>")
    return "".join(o)


def help_html(lang, labels):
    """The whole guide for one language. labels: the site's own captions of the buttons (so they always match the site)."""
    lang = "HE" if lang == "HE" else "EN"
    t = TEXT[lang]
    return "".join([
        _CSS, f'<div class="mh" dir="{"rtl" if lang == "HE" else "ltr"}">',
        f'<h1>{t["title"]}</h1>',
        f'<div class="cite"><b>{t["cite"]}</b><span class="en">{CITATION}</span></div>',
        f'<p>{t["intro"]}</p>',
        f'<div class="fig">{_cycle_svg(lang, labels)}</div>',
        "</div>",
    ])
