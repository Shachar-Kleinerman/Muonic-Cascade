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
_SC = 540.0 / 1840.0          # the pictures are 1840 px wide (help_guide_images.OUT_W) and drawn 540 wide


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

def start_page_html(lang, labels, reset_label="🔍 100%", wheel_label="", fs=1.0):
    """The site guide for the start page (no spectrum yet): the text beside the map (Hebrew: right of it, English: left
    of it), and the map scaled to the height of its frame, so that the whole page fits without scrolling.
    The zoom buttons (-, 100%, +) in the top-left corner of the map box look like those above the plots."""
    lang = "HE" if lang == "HE" else "EN"
    t = TEXT[lang]
    S = max(0.85, min(1.3, fs or 1.0))
    wheel_svg = ('<svg width="14" height="18" viewBox="0 0 14 20" fill="none"><rect x="1" y="1" width="12" height="18" '
                 'rx="6" stroke="#38bdf8" stroke-width="1.8"/><rect x="6" y="4" width="2" height="4.5" rx="1" '
                 'fill="#f59e0b"/></svg>')
    buttons = (
        '<div class="zrow">'
        f'<div class="zw first"><button id="zo" style="font-weight:800;">&minus;</button>'
        f'<div class="ztip">{wheel_svg}<span>{wheel_label}</span></div></div>'
        f'<button id="zr">{reset_label}</button>'
        f'<div class="zw"><button id="zi" style="font-weight:800;">+</button>'
        f'<div class="ztip">{wheel_svg}<span>{wheel_label}</span></div></div>'
        '</div>')
    css = """<style>
.side .fig{position:relative}
.zrow{position:absolute;top:8px;left:8px;z-index:5;display:inline-flex;align-items:center;gap:6px;direction:ltr;user-select:none}
.zrow button{font-family:'Calibri','Segoe UI',sans-serif;background:#ffffff;color:#1e293b;border:1px solid #64748b;
      border-radius:6px;padding:4px 9px;font-size:calc(13px * var(--fs));font-weight:600;cursor:pointer;transition:all 0.15s;
      display:inline-flex;align-items:center;justify-content:center;height:calc(28px * var(--fs));box-sizing:border-box}
.zrow button:hover{background:#f1f5f9}
.zw{position:relative;display:inline-flex;align-items:center}
.ztip{position:absolute;bottom:-34px;left:50%;transform:translateX(-50%);background:#0f172a;color:#ffffff;font-size:11.5px;
      font-weight:600;padding:4px 10px;border-radius:6px;white-space:nowrap;display:flex;align-items:center;gap:6px;
      opacity:0;pointer-events:none;transition:opacity 0.15s ease;z-index:120;box-shadow:0 3px 8px rgba(15,23,42,0.35);
      border:1px solid #334155;font-family:'Calibri','Segoe UI',sans-serif}
.zw:hover .ztip{opacity:1}
.zw.first .ztip{left:0;transform:none}   /* opens inwards, so the frame never clips it */
</style>""".replace("var(--fs)", f"{S:.3f}") + """<style>
html,body{margin:0;height:100%;background:transparent;overflow:hidden}
.side{display:flex;align-items:center;gap:26px;height:100%;box-sizing:border-box;padding:0 6px;
      font-family:'Rubik','Segoe UI',Arial,sans-serif;color:#0f172a}
.side p{flex:0 0 21%;margin:0;font-size:13.5px;line-height:1.6}
.side .fig{flex:1 1 auto;min-width:0;height:100%;display:flex;align-items:center;justify-content:center;
      box-sizing:border-box;padding:8px;background:#f8fafc;border:1px solid #dbe5f0;border-radius:10px;direction:ltr}
.side .fig > svg{width:100%;height:100%;display:block}   /* as large as the box allows; the drawing keeps its proportions */
</style>"""
    return "".join([
        css, f'<div class="side" dir="{"rtl" if lang == "HE" else "ltr"}">',
        f'<p>{t["intro"]}</p>',
        f'<div class="fig">{buttons}{_cycle_svg(lang, labels)}</div>',
        "</div>",
        _ZOOM_JS,
    ])


# wheel over the map: zoom in around the mouse (up to MAX times) and back out, never below the whole map (100 %).
# The zoom changes the viewBox of the SVG, so arrows and circles stay sharp; the screenshots are kept at their native
# resolution (help_guide_images, 1840 px wide), so they stay sharp up to about this zoom.
_ZOOM_JS = """<script>(function () {
  var svg = document.querySelector('.side .fig > svg'); if (!svg) return;
  var W = 1200, H = 740, MAX = 3.5, z = 1, vb = [0, 0, W, H];
  // zoom to nz keeping the map point (px, py) in place
  function zoomTo(nz, px, py) {
    nz = Math.min(MAX, Math.max(1, nz));
    if (nz === z) return;
    var w = W / nz, h = H / nz;
    var nx = px - (px - vb[0]) * (w / vb[2]), ny = py - (py - vb[1]) * (h / vb[3]);
    nx = Math.min(Math.max(0, nx), W - w); ny = Math.min(Math.max(0, ny), H - h);
    vb = [nx, ny, w, h]; z = nz;
    svg.setAttribute('viewBox', vb.join(' '));
  }
  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    var r = svg.getBoundingClientRect();
    var s = Math.min(r.width / vb[2], r.height / vb[3]);
    var ox = (r.width - vb[2] * s) / 2, oy = (r.height - vb[3] * s) / 2;
    var px = vb[0] + (e.clientX - r.left - ox) / s, py = vb[1] + (e.clientY - r.top - oy) / s;
    zoomTo(z * Math.exp(-e.deltaY * 0.0015), px, py);
  }, { passive: false });
  // the buttons zoom around the centre of the visible part (the same 1.3 step as the buttons above the plots)
  function centre(f) { zoomTo(z * f, vb[0] + vb[2] / 2, vb[1] + vb[3] / 2); }
  var zi = document.getElementById('zi'), zo = document.getElementById('zo'), zr = document.getElementById('zr');
  if (zi) zi.onclick = function () { centre(1.3); this.blur(); };
  if (zo) zo.onclick = function () { centre(1 / 1.3); this.blur(); };
  if (zr) zr.onclick = function () { z = 1; vb = [0, 0, W, H]; svg.setAttribute('viewBox', vb.join(' ')); this.blur(); };
})();</script>"""