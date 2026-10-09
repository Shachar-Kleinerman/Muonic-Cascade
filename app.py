import io
import os
import base64
import math
import hashlib
import re
import json
import time
import uuid
import random
import threading
import itertools
import importlib.util
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import streamlit as st
import streamlit.components.v1 as components

import muonic_cascade123 as mc
import help_guide

# Light theme only, with a restrained navy as the primary colour (instead of Streamlit's bright red/orange).
try:
    for _opt, _val in (
        ("theme.base", "light"),
        ("theme.primaryColor", "#0f4c81"),
        ("theme.backgroundColor", "#ffffff"),
        ("theme.secondaryBackgroundColor", "#f1f5f9"),
        ("theme.textColor", "#0f172a"),
    ):
        st._config.set_option(_opt, _val)
except Exception:
    pass

st.set_page_config(page_title="Muonic X-Ray Spectroscopy", layout="wide")
# counts the full script runs (fragment reruns do not touch it); shown as a hidden marker at the very end of the script
st.session_state["_run_seq"] = st.session_state.get("_run_seq", 0) + 1

plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Calibri", "Arial", "sans-serif"]
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False


@st.cache_resource
def get_shared_resources():
    """Holds thread-safe locks and shared MUDIRAC cache across background worker threads."""
    return {
        "lock": threading.Lock(),
        "plot_lock": threading.Lock(),
        "cache": {}
    }


shared_res = get_shared_resources()
mc.live_cache = shared_res["cache"]

# --- Session State Initialization ---
if "spectra_list" not in st.session_state:
    st.session_state.spectra_list = []

if "editing_id" not in st.session_state:
    st.session_state.editing_id = "NEW"

if "open_dialog_flag" not in st.session_state:
    st.session_state.open_dialog_flag = False

if "active_anim_id" not in st.session_state:
    st.session_state.active_anim_id = None

if "lang" not in st.session_state:
    st.session_state.lang = "HE"

if "font_scale" not in st.session_state:
    st.session_state.font_scale = 115   # default text size: second from the right on the slider (right = larger)

if "editor_params" not in st.session_state:
    st.session_state.editor_params = {
        "element": "Fe",
        "start_level": "5g_9/2",
        "num_muons": 10,
        "nuclear_model": "FERMI2",
        "uehling": True,
        "screening": True,
    }
for _k, _v in (("distribution", "statistical"), ("isotope", None)):
    st.session_state.editor_params.setdefault(_k, _v)

# --- Crash recovery: the spectra live server-side under a per-browser id kept in the URL (?sid=...),
# so a browser refresh (e.g. after a frozen / white page) restores everything instead of starting empty.
_sid = st.query_params.get("sid")
if not _sid:
    _sid = uuid.uuid4().hex[:10]
    st.query_params["sid"] = _sid
_sessions = shared_res.setdefault("sessions", {})
if not st.session_state.get("_restored"):
    st.session_state["_restored"] = True
    _saved = _sessions.get(_sid)
    if _saved and not st.session_state.spectra_list:
        st.session_state.spectra_list = _saved["spectra"]
        st.session_state.active_anim_id = _saved.get("active")
        st.session_state.lang = _saved.get("lang", st.session_state.lang)
        st.session_state.font_scale = _saved.get("font_scale", st.session_state.font_scale)
        for _s in st.session_state.spectra_list:
            _s["notified_done"] = _s.get("status") not in ("running", "simulating")
            _s["notified_ready"] = True
_sessions[_sid] = {
    "spectra": st.session_state.spectra_list,
    "active": st.session_state.active_anim_id,
    "lang": st.session_state.lang,
    "font_scale": st.session_state.font_scale,
}
while len(_sessions) > 20:
    _sessions.pop(next(iter(_sessions)))


def _apply_n_wheel_step():
    """Callback: the mouse wheel over the 'n' selector reports 'timestamp:+1' / 'timestamp:-1'."""
    raw = st.session_state.get("_n_bridge", "")
    try:
        delta = int(raw.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    key = st.session_state.get("_dlg_n_key")
    opts = st.session_state.get("_dlg_n_opts") or []
    cur = st.session_state.get(key)
    if key and cur in opts:
        st.session_state[key] = opts[max(0, min(len(opts) - 1, opts.index(cur) + delta))]


def _apply_color_choice():
    """Callback: the client-side palette popup reports 'timestamp:spectrum_id:#hex'."""
    raw = st.session_state.get("_color_bridge", "")
    parts = raw.split(":", 2)
    if len(parts) != 3:
        return
    _, sid, col = parts
    if col.lower() not in {c.lower() for c in PALETTE_40}:
        return
    for item in st.session_state.spectra_list:
        if item["id"] == sid:
            item["color"] = col
            break


def _apply_custom_card_order():
    """Callback triggered when user drags & drops a spectrum card via the ↕ handle."""
    raw = st.session_state.get("_card_order_bridge", "")
    if not raw or ":" not in raw:
        return
    order_part = raw.split(":", 1)[1]
    id_list = [x.strip() for x in order_part.split(",") if x.strip()]
    if not id_list:
        return
    lookup = {s["id"]: s for s in st.session_state.spectra_list}
    if len(id_list) == len(lookup) and set(id_list) == set(lookup.keys()):
        st.session_state.spectra_list = [lookup[i] for i in id_list]


# ==============================================================================
# STANDARD IUPAC PERIODIC TABLE (WITH BOTH ENGLISH & HEBREW NAMES)
# ==============================================================================
MAIN_PERIODIC_TABLE = [
    # Period 1 (Row 0)
    (0, 0, 1, "H", "Hydrogen", "מימן"), (0, 17, 2, "He", "Helium", "הליום"),
    # Period 2 (Row 1)
    (1, 0, 3, "Li", "Lithium", "ליתיום"), (1, 1, 4, "Be", "Beryllium", "בריליום"),
    (1, 12, 5, "B", "Boron", "בורון"), (1, 13, 6, "C", "Carbon", "פחמן"),
    (1, 14, 7, "N", "Nitrogen", "חנקן"), (1, 15, 8, "O", "Oxygen", "חמצן"),
    (1, 16, 9, "F", "Fluorine", "פלואור"), (1, 17, 10, "Ne", "Neon", "ניאון"),
    # Period 3 (Row 2)
    (2, 0, 11, "Na", "Sodium", "נתרן"), (2, 1, 12, "Mg", "Magnesium", "מגנזיום"),
    (2, 12, 13, "Al", "Aluminum", "אלומיניום"), (2, 13, 14, "Si", "Silicon", "צורן"),
    (2, 14, 15, "P", "Phosphorus", "זרחן"), (2, 15, 16, "S", "Sulfur", "גופרית"),
    (2, 16, 17, "Cl", "Chlorine", "כלור"), (2, 17, 18, "Ar", "Argon", "ארגון"),
    # Period 4 (Row 3)
    (3, 0, 19, "K", "Potassium", "אשלגן"), (3, 1, 20, "Ca", "Calcium", "סידן"),
    (3, 2, 21, "Sc", "Scandium", "סקנדיום"), (3, 3, 22, "Ti", "Titanium", "טיטניום"),
    (3, 4, 23, "V", "Vanadium", "ונדיום"), (3, 5, 24, "Cr", "Chromium", "כרום"),
    (3, 6, 25, "Mn", "Manganese", "מנגן"), (3, 7, 26, "Fe", "Iron", "ברזל"),
    (3, 8, 27, "Co", "Cobalt", "קובלט"), (3, 9, 28, "Ni", "Nickel", "ניקל"),
    (3, 10, 29, "Cu", "Copper", "נחושת"), (3, 11, 30, "Zn", "Zinc", "אבץ"),
    (3, 12, 31, "Ga", "Gallium", "גליום"), (3, 13, 32, "Ge", "Germanium", "גרמניום"),
    (3, 14, 33, "As", "Arsenic", "ארסן"), (3, 15, 34, "Se", "Selenium", "סלניום"),
    (3, 16, 35, "Br", "Bromine", "ברום"), (3, 17, 36, "Kr", "Krypton", "קריפטון"),
    # Period 5 (Row 4)
    (4, 0, 37, "Rb", "Rubidium", "רובידיום"), (4, 1, 38, "Sr", "Strontium", "סטרונציום"),
    (4, 2, 39, "Y", "Yttrium", "איטריום"), (4, 3, 40, "Zr", "Zirconium", "זירקוניום"),
    (4, 4, 41, "Nb", "Niobium", "ניוביום"), (4, 5, 42, "Mo", "Molybdenum", "מוליבדן"),
    (4, 6, 43, "Tc", "Technetium", "טכנציום"), (4, 7, 44, "Ru", "Ruthenium", "רותניום"),
    (4, 8, 45, "Rh", "Rhodium", "רודיום"), (4, 9, 46, "Pd", "Palladium", "פלדיום"),
    (4, 10, 47, "Ag", "Silver", "כסף"), (4, 11, 48, "Cd", "Cadmium", "קדמיום"),
    (4, 12, 49, "In", "Indium", "אינדיום"), (4, 13, 50, "Sn", "Tin", "בדיל"),
    (4, 14, 51, "Sb", "Antimony", "אנטימון"), (4, 15, 52, "Te", "Tellurium", "טלור"),
    (4, 16, 53, "I", "Iodine", "יוד"), (4, 17, 54, "Xe", "Xenon", "קסנון"),
    # Period 6 (Row 5)
    (5, 0, 55, "Cs", "Cesium", "צזיום"), (5, 1, 56, "Ba", "Barium", "בריום"),
    (5, 3, 72, "Hf", "Hafnium", "הפניום"), (5, 4, 73, "Ta", "Tantalum", "טנטלום"),
    (5, 5, 74, "W", "Tungsten", "טונגסטן"), (5, 6, 75, "Re", "Rhenium", "רניום"),
    (5, 7, 76, "Os", "Osmium", "אוסמיום"), (5, 8, 77, "Ir", "Iridium", "אירידיום"),
    (5, 9, 78, "Pt", "Platinum", "פלטינה"), (5, 10, 79, "Au", "Gold", "זהב"),
    (5, 11, 80, "Hg", "Mercury", "כספית"), (5, 12, 81, "Tl", "Thallium", "תליום"),
    (5, 13, 82, "Pb", "Lead", "עופרת"), (5, 14, 83, "Bi", "Bismuth", "ביסמוט"),
    (5, 15, 84, "Po", "Polonium", "פולוניום"), (5, 16, 85, "At", "Astatine", "אסטטין"),
    (5, 17, 86, "Rn", "Radon", "רדון"),
    # Period 7 (Row 6)
    (6, 0, 87, "Fr", "Francium", "פרנציום"), (6, 1, 88, "Ra", "Radium", "רדיום"),
    (6, 3, 104, "Rf", "Rutherfordium", "רתרפורדיום"), (6, 4, 105, "Db", "Dubnium", "דובניום"),
    (6, 5, 106, "Sg", "Seaborgium", "סיבורגיום"), (6, 6, 107, "Bh", "Bohrium", "בוהריום"),
    (6, 7, 108, "Hs", "Hassium", "האסיום"), (6, 8, 109, "Mt", "Meitnerium", "מייטנריום"),
    (6, 9, 110, "Ds", "Darmstadtium", "דרמשטטיום"), (6, 10, 111, "Rg", "Roentgenium", "רנטגניום"),
    # 112-118 are shown faded and cannot be selected (MUDIRAC only handles Z <= MAX_SELECTABLE_Z)
    (6, 11, 112, "Cn", "Copernicium", "קופרניקיום"), (6, 12, 113, "Nh", "Nihonium", "ניהוניום"),
    (6, 13, 114, "Fl", "Flerovium", "פלרוביום"), (6, 14, 115, "Mc", "Moscovium", "מוסקוביום"),
    (6, 15, 116, "Lv", "Livermorium", "ליברמוריום"), (6, 16, 117, "Ts", "Tennessine", "טנסין"),
    (6, 17, 118, "Og", "Oganesson", "אוגנסון"),
]

POINT_MAX_Z = 75         # highest Z for which MUDIRAC's point-nucleus p1/2 states converge (see mudirac_can_run)
MAX_SELECTABLE_Z = 111  # MUDIRAC can solve the Dirac equation only up to Z = 111 (inclusive)

LANTHANIDES_ROW = [
    (2, 57, "La", "Lanthanum", "לנתן"), (3, 58, "Ce", "Cerium", "צריום"),
    (4, 59, "Pr", "Praseodymium", "פרסאודימיום"), (5, 60, "Nd", "Neodymium", "נאודימיום"),
    (6, 61, "Pm", "Promethium", "פרומתיום"), (7, 62, "Sm", "Samarium", "סמריום"),
    (8, 63, "Eu", "Europium", "אירופיום"), (9, 64, "Gd", "Gadolinium", "גדוליניום"),
    (10, 65, "Tb", "Terbium", "טרביום"), (11, 66, "Dy", "Dysprosium", "דיספרוסיום"),
    (12, 67, "Ho", "Holmium", "הולמיום"), (13, 68, "Er", "Erbium", "ארביום"),
    (14, 69, "Tm", "Thulium", "תוליום"), (15, 70, "Yb", "Ytterbium", "איטרביום"),
    (16, 71, "Lu", "Lutetium", "לוטציום"),
]

ACTINIDES_ROW = [
    (2, 89, "Ac", "Actinium", "אקטיניום"), (3, 90, "Th", "Thorium", "תוריום"),
    (4, 91, "Pa", "Protactinium", "פרוטקטיניום"), (5, 92, "U", "Uranium", "אורניום"),
    (6, 93, "Np", "Neptunium", "נפטוניום"), (7, 94, "Pu", "Plutonium", "פלוטוניום"),
    (8, 95, "Am", "Americium", "אמריציום"), (9, 96, "Cm", "Curium", "קיוריום"),
    (10, 97, "Bk", "Berkelium", "ברקליום"), (11, 98, "Cf", "Californium", "קליפורניום"),
    (12, 99, "Es", "Einsteinium", "איינשטייניום"), (13, 100, "Fm", "Fermium", "פרמיום"),
    (14, 101, "Md", "Mendelevium", "מנדליביום"), (15, 102, "No", "Nobelium", "נובליום"),
    (16, 103, "Lr", "Lawrencium", "לורנסיום"),
]

ELEMENT_INFO = {}
for _, _, z, s, n_en, n_he in MAIN_PERIODIC_TABLE:
    ELEMENT_INFO[s] = (z, n_en, n_he)
for _, z, s, n_en, n_he in LANTHANIDES_ROW + ACTINIDES_ROW:
    ELEMENT_INFO[s] = (z, n_en, n_he)

# --- Bilingual Dictionary ---
TRANSLATIONS = {
    "EN": {
        "app_title": "Muonic Atom Cascade & X-Ray Spectroscopy",
        "add_spectrum_top": "Create New Spectrum",
        "select_all": "☑️ Select All",
        "deselect_all": "⬜ Deselect All",
        "edit_spec_title": "Edit Spectrum",
        "new_spec_title": "New Spectrum",
        "muon_count": "Number of Muons",
        "distribution_label": "Muon distribution",
        "create_spec": "Create Spectrum",
        "create_spec_sim": "Create Spectrum & Simulation",
        "update_spec": "Update Spectrum",
        "update_spec_sim": "Update Spectrum & Simulation",
        "branching": "Branching Ratios",
        "ground_reached": "Ground state 1s<sub>1/2</sub> reached.",
        "no_transition": "No transition from this level occurs in this simulation.",
        "mudirac_error": "MUDIRAC could not compute the level {level} of {name} with these settings.",
        "dist_delta": "Delta (single level + sublevel)",
        "dist_uniform": "Uniform (equal split over all sublevels of n)",
        "dist_uniform_short": "Uniform",
        "dist_delta_short": "Delta",
        "dist_delta_tip": "Single initial sublevel",
        "dist_stat_short": "Statistical",
        "sim_limit_tip": "Simulation is available only below {limit} muons.",
        "sim_disabled_note": "From {limit} muons:<br>spectrum only, no simulation",
        "isotope_label": "Isotope",
        "isotope_main": "Main isotope",
        "isotope_natural": "Natural mix",
        "isotope_default": "MUDIRAC default",
        "nuclear_model": "Nuclear Model",
        "need_other_isotope": "not available for the chosen isotope: choose another isotope first",
        "need_sphere": "SPHERE requires the measured nuclear charge radius of this isotope, which is not available.",
        "need_fermi": "No measured radius is available for this isotope.\nFERMI2 then uses R = 1.2·A^(1/3) fm,\nwhich is possible only with vacuum polarization (Uehling) switched off.",
        "model_off_point": "POINT is not available at this atomic number: MUDIRAC's solver does not converge for the p1/2 states of a point nucleus at this atomic number.",
        "need_point": "Not available with POINT: MUDIRAC's solver does not converge for the p1/2 states of a point nucleus at this atomic number.",
        "model_off_sphere": "SPHERE requires a measured nuclear charge radius, which is not available for the selected isotope.",
        "model_off_fermi": "With vacuum polarization on, FERMI2 requires a measured nuclear charge radius, which is not available for the selected isotope.",
        "mudirac_cannot_run": "MUDIRAC cannot run this element with this nuclear model (SPHERE needs a nuclear charge radius that MUDIRAC does not have for it; FERMI2 without one works only with vacuum polarization switched off). Choose POINT, change the vacuum-polarization setting, or choose another isotope or element.",
        "qed_label": "Vacuum Polarization (Uehling)",
        "qed_card_label": "Vacuum Polarization",      # the spectrum tab is too narrow for the full label
        "qed_help": "First-order vacuum-polarization correction (Uehling potential) to the muon-nucleus interaction.",
        "screening_label": "Electronic Screening",
        "screening_help": "Electronic background charge, using the electron configuration of the atom with Z−1.",
        "screening_help_h": "Not available for hydrogen: the muon takes the place of the only electron, so no electrons are left (Z−1 = 0).",
        "initial_level_row_label": "Initial Level",
        "create_run": "Create",
        "update_run": "Update",
        "return_all_btn": "Display & Compare All Spectra",
        "view_current_btn": "Show This Spectrum Only",
        "display_mode": "Display Mode",
        "mode_grouped": "Side-by-Side Bars",
        "mode_stacked": "Stacked Graphs",
        "col_width_label": "Column Width",
        "width_thin": "Thin",
        "width_medium": "Medium",
        "width_wide": "Wide",
        "width_full": "Full",
        "log_y": "Logarithmic\nY-Axis",              # two lines (the label is shown with white-space: pre-line)
        "rel_intensity": "Relative\nIntensity (%)",
        "select_one_or_more": "Select one or more spectra to display",
        "anim_header": "Live Cascade Simulation:",
        "anim_computing": "Computing cascade tree in background...",
        "help_btn": "Information",
        "play": "▶ Play",
        "pause": "⏸ Pause",
        "replay": "⟲ Replay",
        "space_tooltip": "⌨ Space",
        "prev_trans": "⏮ Prev Transition",
        "next_trans": "Next Transition ⏭",
        "start": "⟲ Start",
        "end": "⇥ End",
        "fullscreen": "⛶ Fullscreen",
        "exit_fullscreen": "🗗 Exit Fullscreen",
        "reset_zoom": "🔍 100%",
        "wheel_tooltip": "Mouse Wheel",
        "plot_export": "Save as image",
        "all_probs": "Show All Probabilities",
        "photon_anim": "Show Photon Emission (𝛾)",
        "gaussian": "Gaussian Profile",
        "speed": "Speed",
        "timeline_hint": "Master Timeline — Drag or scroll wheel to scrub manually (Click any transition badge for Wavefunctions)",
        "wf_modal_title": "Radial Wavefunctions & Branching Ratios",
        "wf_initial": "Initial state",
        "wf_target": "Target state",
        "wf_legend": "solid: P(r), dashed: Q(r), shaded: P²+Q²",
        "wf_approx": "MUDIRAC radial wavefunctions",
        "wf_unavailable": "MUDIRAC wavefunction not available for this state",
        "wf_radius_fb": "[nuclear radius: empirical R = 1.2·A^(1/3) fm, as in the MUDIRAC paper]",
        "wf_norm": "Vertical axis: arbitrary units, each panel normalized separately (P and Q to the maximum of P, P²+Q² to its own maximum)",
        "wf_axis": "Radial coordinate r",
        "wf_nuc_model": "Nuclear model",
        "wf_table_title": "Branching ratios from",
        "wf_th_target": "Target state",
        "wf_th_energy": "Energy ΔE (keV)",
        "wf_th_rate": "Rate (s⁻¹)",
        "wf_th_prob": "Probability (%)",
        "wf_prob": "Probability",
        "wf_close": "Close",
    },
    "HE": {
        "app_title": "סימולטור מפל מיואוני וספקטרוסקופיית קרני X",
        "add_spectrum_top": "יצירת ספקטרום חדש",
        "select_all": "☑️ בחירת הכל",
        "deselect_all": "⬜ ביטול בחירת הכל",
        "edit_spec_title": "עריכת ספקטרום",
        "new_spec_title": "ספקטרום חדש",
        "muon_count": "מספר מיואונים",
        "distribution_label": "התפלגות מיואונים",
        "create_spec": "יצירת ספקטרום",
        "create_spec_sim": "יצירת ספקטרום וסימולציה",
        "update_spec": "עדכן ספקטרום",
        "update_spec_sim": "עדכן ספקטרום וסימולציה",
        "branching": "יחסי הסתעפות",
        "ground_reached": "הגענו למצב היסוד 1s<sub>1/2</sub>.",
        "no_transition": "אף מעבר מרמה זו לא מתרחש בסימולציה הזו.",
        "mudirac_error": "MUDIRAC לא הצליח לחשב את הרמה ⁦{level}⁩ של ⁦{name}⁩ עם ההגדרות האלה.",
        "dist_delta": "Delta (single level + sublevel)",
        "dist_uniform": "Uniform (equal split over all sublevels of n)",
        "dist_uniform_short": "Uniform",
        "dist_delta_short": "Delta",
        "dist_delta_tip": "תת-רמה התחלתית יחידה",
        "dist_stat_short": "Statistical",
        "sim_limit_tip": "סימולציה אפשרית רק מתחת ל‑{limit} מיואונים.",
        "sim_disabled_note": "החל מ‑{limit} מיואונים:<br>ספקטרום בלבד, ללא סימולציה",
        "isotope_label": "איזוטופ",
        "isotope_main": "איזוטופ ראשי",
        "isotope_natural": "ממוצע טבעי",
        "isotope_default": "ברירת מחדל (MUDIRAC)",
        "nuclear_model": "מודל גרעין",
        "need_other_isotope": "אינו זמין לאיזוטופ שנבחר: בחר קודם איזוטופ אחר",
        "need_sphere": "המודל הכדורי (SPHERE) דורש את רדיוס המטען הגרעיני המדוד של האיזוטופ, אשר אינו זמין.",
        "need_fermi": "לאיזוטופ אין רדיוס מדוד.\nב-FERMI2 משתמשים אז ב-R = 1.2·A^(1/3) fm,\nוהדבר אפשרי רק כשקיטוב הריק (Uehling) כבוי.",
        "model_off_point": "המודל הנקודתי (POINT) אינו זמין במספר אטומי זה: הפותר של MUDIRAC אינו מתכנס עבור מצבי p1/2 של גרעין נקודתי.",
        "need_point": "אינו זמין במודל הנקודתי (POINT): הפותר של MUDIRAC אינו מתכנס עבור מצבי p1/2 של גרעין נקודתי במספר אטומי זה.",
        "model_off_sphere": "המודל הכדורי (SPHERE) דורש רדיוס מטען גרעיני מדוד, אשר אינו זמין לאיזוטופ שנבחר.",
        "model_off_fermi": "כשקיטוב הריק דלוק, FERMI2 דורש רדיוס מטען גרעיני מדוד, אשר אינו זמין לאיזוטופ שנבחר.",
        # English words are isolated (LRI ... PDI) and the whole text is a right-to-left paragraph (RLI ... PDI)
        "mudirac_cannot_run": "⁧⁦MUDIRAC⁩ לא יכול להריץ יסוד זה עם מודל הגרעין שנבחר (המודל הכדורי דורש רדיוס מטען גרעיני שאין ל-⁦MUDIRAC⁩ עבורו, ו-⁦FERMI2⁩ בלי רדיוס כזה עובד רק כשקיטוב הריק כבוי). בחר ⁦POINT⁩, שנה את הגדרת קיטוב הריק, או בחר איזוטופ או יסוד אחר.⁩",
        "qed_label": "קיטוב הריק (Uehling)",
        "qed_card_label": "קיטוב הריק (Uehling)",
        "qed_help": "תיקון קיטוב הריק מסדר ראשון (פוטנציאל Uehling) לאינטראקציה בין המיואון לגרעין.",
        "screening_label": "מיסוך אלקטרוני",
        "screening_help": "מטען אלקטרוני ברקע, לפי ההרכב האלקטרוני של האטום עם ⁦Z−1⁩.",
        "screening_help_h": "לא זמין במימן: המיואון תופס את מקום האלקטרון היחיד, ולכן לא נשארים אלקטרונים (⁦Z−1 = 0⁩).",
        "initial_level_row_label": "רמה התחלתית",
        "create_run": "יצירת",
        "update_run": "עדכן",
        "return_all_btn": "הצגה והשוואה בין כל הספקטרומים",
        "view_current_btn": "הצגת הספקטרום הנוכחי בלבד",
        "display_mode": "תצוגת ספקטרומים",
        "mode_grouped": "עמודות זו לצד זו",
        "mode_stacked": "גרפים זה מעל זה",
        "col_width_label": "עובי עמודות",
        "width_thin": "דק",
        "width_medium": "בינוני",
        "width_wide": "רחב",
        "width_full": "מלא",
        "log_y": "ציר Y\nלוגריתמי",
        "rel_intensity": "עוצמה\nיחסית (%)",
        "select_one_or_more": "בחר ספקטרום אחד או יותר להצגה",
        "anim_header": "סימולציית מפל חיה:",
        "anim_computing": "מחשב את עץ המעברים ברקע...",
        "help_btn": "מידע",
        "play": "▶ הפעל",
        "pause": "⏸ השהה",
        "replay": "⟲ הפעל שוב",
        "space_tooltip": "⌨ מקש רווח",
        "prev_trans": "⏮ מעבר קודם",
        "next_trans": "מעבר הבא ⏭",
        "start": "⟲ התחלה",
        "end": "⇥ סוף",
        "fullscreen": "⛶ מסך מלא",
        "exit_fullscreen": "🗗 יציאה ממסך מלא",
        "reset_zoom": "🔍 100%",
        "wheel_tooltip": "גלגלת עכבר",
        "plot_export": "שמירה כתמונה",
        "all_probs": "הצגת כל המעברים",
        "photon_anim": "הצגת פליטת פוטון (𝛾)",
        "gaussian": "פרופיל גאוסיאני",
        "speed": "מהירות",
        "timeline_hint": "ציר זמן ראשי — גרור או גלגל בעכבר לשליטה ידנית (לחץ על תווית מעבר לפונקציות גל וניתוח)",
        "wf_modal_title": "פונקציות גל רדיאליות ויחסי הסתעפות",
        "wf_initial": "מצב התחלתי",
        "wf_target": "מצב סופי",
        "wf_legend": "רציף: P(r), מקווקו: Q(r), מוצל: P²+Q²",
        "wf_approx": "פונקציות גל רדיאליות של MUDIRAC",
        "wf_unavailable": "פונקציית הגל של MUDIRAC אינה זמינה למצב זה",
        "wf_radius_fb": "[רדיוס גרעיני: נוסחה אמפירית R = 1.2·A^(1/3) fm, כמו במאמר של MUDIRAC]",
        "wf_norm": "ציר אנכי: יחידות שרירותיות, כל גרף מנורמל בנפרד (P ו-Q לפי המקסימום של P, ‏P²+Q² לפי המקסימום שלו)",
        "wf_axis": "קואורדינטה רדיאלית r",
        "wf_nuc_model": "מודל גרעיני",
        "wf_table_title": "יחסי הסתעפות מהמצב",
        "wf_th_target": "מצב סופי",
        "wf_th_energy": "אנרגיה ΔE (keV)",
        "wf_th_rate": "קצב (s⁻¹)",
        "wf_th_prob": "הסתברות (%)",
        "wf_prob": "הסתברות",
        "wf_close": "סגירה",
    }
}

# Sixteen strongly different colours (4 x 4) offered by the spectrum colour picker; new tabs take them in this order.
PALETTE_40 = [
    "#1d4ed8", "#dc2626", "#16a34a", "#ea580c",     # blue, red, green, orange
    "#7c3aed", "#06b6d4", "#ec4899", "#78350f",     # violet, cyan, pink, brown
    "#111827", "#84cc16", "#facc15", "#94a3b8",     # black, lime, lemon yellow, grey
    "#0f766e", "#a21caf", "#1e3a8a", "#4d7c0f",     # teal, magenta, navy, dark olive
]
PALETTE = list(PALETTE_40)
SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def tr(key):
    return TRANSLATIONS[st.session_state.lang][key]


def pick_next_distinct_color(exclude_color=None):
    """Picks a color from PALETTE not currently used (or different from exclude_color)."""
    used = {s.get("color", "").lower() for s in st.session_state.spectra_list}
    if exclude_color:
        used.add(exclude_color.lower())
    for c in PALETTE:
        if c.lower() not in used:
            return c
    for c in PALETTE:
        if not exclude_color or c.lower() != exclude_color.lower():
            return c
    return PALETTE[0]


def format_level_unicode(level_name):
    """Formats '5g_9/2' into '5g₉/₂' with an explicit '/' so Matplotlib legends never show a box."""
    if "_" in level_name:
        orb, j_val = level_name.split("_", 1)
        return f"{orb}{j_val.translate(SUBSCRIPT_DIGITS)}"
    return level_name


def format_level_html(level_name):
    """Formats '5g_9/2' into HTML '5g<sub>9/2</sub>' so the slash is in true subscript."""
    if "_" in level_name:
        orb, j_val = level_name.split("_", 1)
        return f"{orb}<sub>{j_val}</sub>"
    return level_name


def format_level_sub_btn(level_name):
    """Formats '5g_9/2' into '5g`9/2`' — styled via CSS `button code` as a true subscript."""
    if "_" in level_name:
        orb, j_val = level_name.split("_", 1)
        return f"{orb}`{j_val}`"
    return level_name


PAUSE_ICON = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'>"
              "<rect x='9' y='7' width='8' height='26' rx='2' fill='white'/><rect x='23' y='7' width='8' height='26' rx='2' fill='white'/></svg>")
PERIODIC_TABLE_BOX_HEIGHT = 700   # the table scrolls inside this box; the dialog itself never scrolls
NUCLEAR_RECOIL = True     # always on (the reduced mass of the muon-nucleus system, as in the MUDIRAC paper, Sec. 2.1). It is not
#                           a choice for the user: with the recoil switched off this MUDIRAC build is not reproducible (random
#                           aborts and, in some runs, the electronic screening silently dropped).
MAX_START_N = 8          # highest starting shell offered: the MUDIRAC paper's examples stop at n = 5-6; above n = 7 our own runs start to fail
SIM_DISABLE_FROM = 5000  # from this many muons on: exact spectrum only, no simulation (keeps the page responsive)
MAX_ANIM_MUONS = SIM_DISABLE_FROM  # every muon below the limit is simulated

# Isotope selector lists and natural abundances: NUBASE2020 (IAEA-AMDC), generated by build_isotope_data.py.
# Elements without a natural terrestrial composition have no NATURAL_ABUNDANCE entry: for them "Natural mix"
# is replaced by MUDIRAC's own default isotope.
from isotope_data import STABLE_ISOTOPES, NATURAL_ABUNDANCE, LONGEST_LIVED
from mudirac_support import POINT_ISOTOPES, RADIUS_ISOTOPES, SPHERE_ISOTOPES, FALLBACK_FERMI, DEFAULT_ISOTOPE   # what MUDIRAC can really run
# "Natural mix" simulates every isotope with at least this abundance (weights re-normalised);
# rarer isotopes would only add invisible lines but multiply the number of MUDIRAC runs.
NAT_MIN_ABUNDANCE = 0.0   # every naturally occurring isotope takes part (each one costs its own set of MUDIRAC runs)

SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def spec_name_unicode(spec):
    """'⁶³Cu' for a specific isotope, the plain symbol for a natural mix / MUDIRAC's default."""
    el = spec["element"]
    if spec.get("isotope"):
        return f"{str(spec['isotope']).translate(SUPERSCRIPT_DIGITS)}{el}"
    return el


def spec_name_html(spec):
    el = spec["element"]
    if spec.get("isotope"):
        return f"<sup>{spec['isotope']}</sup>{el}"
    return el


def spec_ready(spec):
    return bool(spec.get("spectrum_ready")) or spec.get("status") in ("completed", "spectrum_only")


def spec_is_uniform(spec):
    return spec.get("distribution", "delta") == "uniform"


def spec_n_only(spec):
    """True when the distribution spreads the muons over the sublevels of one n (everything except delta)."""
    return spec.get("distribution", "delta") != "delta"


def spec_dist_name(spec):
    d = spec.get("distribution", "delta")
    if d == "uniform":
        return tr("dist_uniform_short")
    if d == "statistical":
        return tr("dist_stat_short")
    return tr("dist_delta_short")


def spec_level_parts_html(spec):
    """(distribution name, start level) of a tab, each for its own line."""
    if spec_n_only(spec):
        return spec_dist_name(spec), f"n={mc.get_n(spec['start_level'])}"
    return spec_dist_name(spec), format_level_html(spec['start_level'])


def spec_level_html(spec):
    """Start-level label for a spectrum: 'n=5' for the n-wide distributions, else '5g<sub>9/2</sub>'."""
    if spec_n_only(spec):
        return f"<span class='spec-dist'>{spec_dist_name(spec)}:</span> n={mc.get_n(spec['start_level'])}"
    return f"<span class='spec-dist'>{spec_dist_name(spec)}:</span> {format_level_html(spec['start_level'])}"


def spec_level_unicode(spec):
    if spec_n_only(spec):
        return f"{spec_dist_name(spec)}: n={mc.get_n(spec['start_level'])}"
    return f"{spec_dist_name(spec)}: {format_level_unicode(spec['start_level'])}"


def initial_population_weight(level_name):
    """Statistical initial population of the fine-structure level n l j at capture: weight 2j+1
    (all magnetic substates equally likely). Summed over j = l+-1/2 this gives P(l) ~ 2l+1."""
    two_j = int(level_name.split("_", 1)[1].split("/")[0])
    return two_j + 1

def is_sublevel_allowed_for_element(level_name, element):
    """Checks whether a starting sublevel is physically allowed for cascade."""
    if level_name == "1s_1/2":        # the ground state has nothing to decay to (2s is allowed: it decays to 2p when 2p lies lower)
        return False
    if mc.get_n(level_name) > MAX_START_N:
        return False
    return True


# --- Inject CSS: Strict Locked Zero-Scroll Main Page & Dialog, 5-Line Card Button, Wedge Slider ---
scale_factor = st.session_state.font_scale / 100.0
base_rem = round(0.94 * scale_factor, 3)

_TOP_ROW = '[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-muon_slider_box)'
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&display=swap');

    /* STRICT ZERO-SCROLL ON OUTER MAIN PAGE */
    html, body, .stApp, [data-testid="stAppViewContainer"] {{
        overflow: hidden !important;
        height: 100vh !important;
        max-height: 100vh !important;
    }}
    /* The app keeps its designed size: when the window is smaller (e.g. browser zoom) it scrolls
       instead of re-flowing or clipping, so the layout is never "broken" by Ctrl + wheel. */
    [data-testid="stMain"] {{
        align-items: flex-start !important;
        overflow: hidden !important;
        height: 100vh !important;
        max-height: 100vh !important;
    }}
    div[data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap !important;
    }}
    div[data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    div[data-testid="stHorizontalBlock"] > [data-testid="column"] {{
        min-width: 0 !important;
    }}

    /* Hide Streamlit top bar & Deploy button */
    header[data-testid="stHeader"] {{
        background: transparent !important;
        height: 0.6rem !important;
        min-height: 0.6rem !important;
    }}
    .stAppDeployButton {{
        display: none !important;
    }}

    /* Calibri-first clean typography without overriding Material Icon spans */
    html, body, h1, h2, h3, h4, p, label, button {{
        font-family: 'Calibri', 'Segoe UI', 'Rubik', Arial, sans-serif !important;
    }}
    span.material-symbols-rounded, [data-testid="stIconMaterial"] {{
        font-family: 'Material Symbols Rounded' !important;
        font-weight: normal !important;
        font-style: normal !important;
        font-size: 1.08rem !important;
        line-height: 1 !important;
    }}
    html, body {{
        font-size: {base_rem}rem !important;
        color: #0f172a;
    }}
    .block-container {{
        padding-top: 0.25rem !important;
        padding-bottom: 0.1rem !important;
        /* the page margin equals the header's (1.3rem) on both sides; the left one also holds the thin scrollbar of the
           spectra list (8px bar + 6px gap) */
        padding-left: calc(1.3rem + 14px) !important;
        padding-right: 1.3rem !important;
        max-width: 100% !important;
        height: 100vh !important;
        overflow: visible !important;
    }}
    div[data-testid="stVerticalBlock"] {{
        gap: 0.16rem !important;
    }}
    div[data-testid="stHorizontalBlock"] {{
        gap: 0.16rem !important;
    }}

    /* Replace Streamlit top-right status icons with Scientific Spinning Atom */
    [data-testid="stStatusWidget"] svg {{
        display: none !important;
    }}
    [data-testid="stStatusWidget"] > div {{
        display: flex !important;
        align-items: center !important;
        gap: 7px !important;
        background: #f1f5f9 !important;
        border: 1.5px solid #0f4c81 !important;
        border-radius: 18px !important;
        padding: 2px 10px !important;
    }}
    [data-testid="stStatusWidget"] > div::before {{
        content: "";
        width: 20px;
        height: 20px;
        display: inline-block;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 28 28'><ellipse cx='14' cy='14' rx='10' ry='3.8' fill='none' stroke='%230284c7' stroke-width='1.6'/><ellipse cx='14' cy='14' rx='10' ry='3.8' fill='none' stroke='%230284c7' stroke-width='1.6' transform='rotate(60 14 14)'/><ellipse cx='14' cy='14' rx='10' ry='3.8' fill='none' stroke='%230284c7' stroke-width='1.6' transform='rotate(120 14 14)'/><circle cx='14' cy='14' r='2.5' fill='%23c1121f'/></svg>");
        background-size: contain;
        animation: atomSpin 1.4s linear infinite;
    }}
    @keyframes atomSpin {{
        0%   {{ transform: rotate(0deg); }}
        100% {{ transform: rotate(360deg); }}
    }}

    /* ===== Spectrum cards — flat, professional look. All sizes in px so browser zoom never reflows them. ===== */
    [class*="st-key-spectrum_card_"] {{
        --cp: 26px;
        background-color: #ffffff !important;
        border: 1px solid #d5dce6 !important;
        border-left: 4px solid #0f4c81 !important;
        border-radius: 12px !important;
        padding: 10px 12px 10px 10px !important;
        min-width: 360px !important;
        box-sizing: border-box !important;
        margin-bottom: 8px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .06) !important;
        transition: box-shadow .15s ease, opacity .15s ease !important;
    }}
    [class*="st-key-spectrum_card_"]:hover {{
        box-shadow: 0 3px 10px rgba(15, 23, 42, .12) !important;
    }}
    /* Direct children of the card (e.g. the loading bar) must keep their full height inside the frame */
    [class*="st-key-spectrum_card_"] > [data-testid="stElementContainer"] {{
        flex-shrink: 0 !important;
        height: auto !important;
    }}
    [class*="st-key-spectrum_card_"] > [data-testid="stElementContainer"] [data-testid="stMarkdown"],
    [class*="st-key-spectrum_card_"] > [data-testid="stElementContainer"] [data-testid="stMarkdown"] > div,
    [class*="st-key-spectrum_card_"] > [data-testid="stElementContainer"] [data-testid="stMarkdownContainer"] {{
        height: auto !important;
        min-height: 22px;
    }}
    [class*="st-key-spectrum_card_"].dragging-card {{
        opacity: .35 !important;
    }}
    /* Keep the three columns on one row and inside the frame at every zoom level / window width */
    [class*="st-key-spectrum_card_"] [data-testid="stHorizontalBlock"] {{
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 8px !important;
        align-items: center !important;
    }}
    [class*="st-key-spectrum_card_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    [class*="st-key-spectrum_card_"] [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
        min-width: 0 !important;
    }}
    [class*="st-key-spectrum_card_"] [data-testid="stHorizontalBlock"] > *:nth-child(1) {{
        flex: 0 0 36px !important; width: 36px !important;
    }}
    [class*="st-key-spectrum_card_"] [data-testid="stHorizontalBlock"] > *:nth-child(2) {{
        flex: 1 1 0 !important; width: auto !important;
    }}
    [class*="st-key-spectrum_card_"] [data-testid="stHorizontalBlock"] > *:nth-child(3) {{
        flex: 0 0 40px !important; width: 40px !important;
    }}

    [class*="st-key-spectrum_summary_"] {{
        position: relative !important;
        background: #f6f8fb !important;
        border: 1px solid #dde3ec !important;
        border-radius: 10px !important;
        min-height: 104px !important;
        padding: 0 !important;
        overflow: hidden !important;
    }}
    [class*="st-key-spectrum_summary_"] [data-testid="stMarkdownContainer"] p {{
        margin: 0 !important;
    }}
    .spec-sum {{
        position: relative;
        display: grid;
        grid-template-columns: minmax(0, 40fr) minmax(0, 60fr);
        min-height: 102px;
        color: #1e293b;
    }}
    .spec-left {{
        border-right: 1px solid #d5dce6;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 4px;
        padding: 8px 26px 8px 6px;
        min-width: 0;
    }}
    /* four centred lines, one font: only the element symbol is larger and bold, and the muon count is bold */
    .spec-left > div {{ width: 100%; text-align: center; font-family: inherit; }}
    .spec-el {{ font-size: 22px; font-weight: 700; line-height: 1.1; color: #0f172a; letter-spacing: .2px; }}
    .spec-n {{ font-size: 13px; font-weight: 700; line-height: 1.2; color: #334155; font-variant-numeric: tabular-nums; }}
    .spec-dist, .spec-lvl {{ font-size: 13px; font-weight: 400; line-height: 1.2; color: #334155; }}
    .spec-lvl sub {{ font-size: .68em; font-weight: 400; vertical-align: -0.25em; }}
    .spec-right {{
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        gap: 7px;
        padding: 8px 8px 8px 38px;
        min-width: 0;
    }}
    .spec-model {{
        font-size: 11.5px; font-weight: 700; letter-spacing: .6px;
        color: #0f4c81; background: #e6eef7; border-radius: 6px;
        padding: 2px 8px; line-height: 1.5;
    }}
    .spec-corr {{ width: auto; max-width: 100%; min-width: 0; }}
    .spec-corr span {{
        display: block; font-size: 12.5px; line-height: 1.75; color: #94a3b8;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .spec-corr span::before {{ content: "○"; display: inline-block; width: 16px; }}
    .spec-corr span.on {{ color: #334155; }}
    .spec-corr span.on::before {{ content: "✓"; color: #15803d; font-weight: 700; }}

    /* Simulation-loading ring (replaces the Play button until the animation data set is ready) */
    .play-ring {{
        position: absolute; left: 40%; top: 50%;
        width: 44px; height: 44px;
        transform: translate(-50%, -50%);
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        background: conic-gradient(var(--ringc, #0f4c81) calc(var(--p, 0) * 1%), #dbe2ec 0);
        z-index: 3;
    }}
    .play-ring::before {{
        content: ""; position: absolute; inset: 5px; border-radius: 50%; background: #ffffff;
    }}
    .play-ring span {{ position: relative; font-size: 11px; font-weight: 700; color: #0f172a; }}
    .play-ring.idle {{ background: #dbe2ec; }}
    .play-ring.off {{ background: #e3e8ef; cursor: help; }}

    /* Round play button on the divider */
    [class*="st-key-spectrum_summary_"] [class*="st-key-card_anim_"] {{
        position: absolute !important;
        left: 40% !important;
        top: 50% !important;
        transform: translate(-50%, -50%) !important;
        width: auto !important;
        z-index: 3 !important;
    }}
    [class*="st-key-card_anim_"] [data-testid="stButton"] button {{
        width: 44px !important;
        height: 44px !important;
        min-width: 44px !important;
        min-height: 44px !important;
        border-radius: 50% !important;
        border: 3px solid #ffffff !important;
        background-color: #0f4c81;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'><path d='M13 8 L33 20 L13 32 Z' fill='white'/></svg>") !important;
        background-repeat: no-repeat !important;
        background-position: 55% 50% !important;
        background-size: 22px 22px !important;
        padding: 0 !important;
        box-shadow: 0 2px 6px rgba(15, 23, 42, .3) !important;
    }}
    [class*="st-key-card_anim_"] [data-testid="stButton"] button p {{ display: none !important; }}
    [class*="st-key-card_anim_"] [data-testid="stButton"] button:hover {{
        transform: scale(1.08) !important;
        filter: brightness(1.1);
        border-color: #ffffff !important;
    }}

    /* Edit / copy / delete: quiet icon buttons */
    div[data-testid="stVerticalBlock"][class*="st-key-spectrum_actions_"] {{
        gap: 6px !important;
        align-items: center !important;
    }}
    /* the button itself never changes (no fill, border, glow or shadow in any state): only the icon takes a colour on hover */
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button,
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button:hover,
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button:focus,
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button:focus-visible,
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button:active {{
        width: 32px !important;
        min-width: 32px !important;
        height: 32px !important;
        min-height: 32px !important;
        border-radius: 8px !important;
        background: transparent !important;
        background-color: transparent !important;
        border: 1px solid transparent !important;
        box-shadow: none !important;
        outline: none !important;
        filter: none !important;
        transform: none !important;
        padding: 0 !important;
        color: #64748b;
    }}
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button * {{ color: inherit !important; }}
        /* on hover: a plain square (no outline) in the grey of the details box behind the icon, and the icon changes colour */
    div[class*="st-key-spectrum_actions_"] div[data-testid="stButton"] > button:hover {{ background: #f6f8fb !important; background-color: #f6f8fb !important; }}
    div[class*="st-key-spectrum_actions_"] div[class*="st-key-edit_"] div[data-testid="stButton"] > button:hover {{ color: #16a34a !important; }}
    div[class*="st-key-spectrum_actions_"] div[class*="st-key-copy_"] div[data-testid="stButton"] > button:hover {{ color: #000000 !important; }}
    div[class*="st-key-spectrum_actions_"] div[class*="st-key-del_"] div[data-testid="stButton"] > button:hover {{ color: #dc2626 !important; }}

    /* Right column: colour swatch / drag grip / show checkbox */
    div[data-testid="stVerticalBlock"][class*="st-key-spectrum_side_"] {{
        gap: 12px !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    [class*="st-key-spectrum_side_"] > * {{
        flex: 0 0 auto !important;
        height: auto !important;
    }}
    [class*="st-key-spectrum_side_"] [data-testid="stMarkdown"],
    [class*="st-key-spectrum_side_"] [data-testid="stMarkdown"] > div,
    [class*="st-key-spectrum_side_"] [data-testid="stMarkdownContainer"] {{
        flex: 0 0 auto !important;
        height: auto !important;
        min-height: 26px !important;
    }}
    [class*="st-key-spectrum_side_"] [data-testid="stMarkdownContainer"] p {{ margin: 0 !important; }}
    [class*="st-key-spectrum_side_"] [data-testid="stCheckbox"] {{
        display: flex !important;
        justify-content: center !important;
        width: auto !important;
    }}
    [class*="st-key-spectrum_side_"] [data-testid="stCheckbox"] label {{
        padding: 0 !important;
        margin: 0 !important;
        min-height: 0 !important;
    }}
    [class*="st-key-spectrum_side_"] [data-testid="stCheckbox"] label > span:first-child {{
        width: 22px !important;
        height: 22px !important;
        margin: 0 !important;
        border-radius: 6px !important;
        background-color: #ffffff !important;
        border: 1.5px solid #94a3b8 !important;
    }}
    [class*="st-key-spectrum_side_"] [data-testid="stCheckbox"] label:has(input:checked) > span:first-child {{
        background-color: #0f4c81 !important;
        border-color: #0f4c81 !important;
    }}
    [class*="st-key-spectrum_side_"] [data-testid="stCheckbox"] label > span:first-child svg {{
        color: #ffffff !important;
        fill: #ffffff !important;
        width: 16px !important;
        height: 16px !important;
    }}

    /* STRICT CIRCULAR COLOR PICKER (24px by default, --cp inside spectrum cards) */
    div[data-testid="stColorPicker"] {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: var(--cp, 24px) !important;
        height: var(--cp, 24px) !important;
        margin: 0 auto !important;
    }}
    div[data-testid="stColorPicker"] > div,
    div[data-testid="stColorPicker"] [data-baseweb="popover"],
    div[data-testid="stColorPicker"] [data-baseweb="popover"] > div {{
        width: var(--cp, 24px) !important;
        height: var(--cp, 24px) !important;
        min-width: var(--cp, 24px) !important;
        min-height: var(--cp, 24px) !important;
        max-width: var(--cp, 24px) !important;
        max-height: var(--cp, 24px) !important;
        border-radius: 50% !important;
        overflow: hidden !important;
        padding: 0 !important;
        margin: 0 !important;
        border: none !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    div[data-testid="stColorPicker"] [data-testid="stColorBlock"],
    div[data-testid="stColorPicker"] button,
    div[data-testid="stColorPicker"] input {{
        width: var(--cp, 24px) !important;
        height: var(--cp, 24px) !important;
        min-width: var(--cp, 24px) !important;
        min-height: var(--cp, 24px) !important;
        max-width: var(--cp, 24px) !important;
        max-height: var(--cp, 24px) !important;
        border-radius: 50% !important;
        overflow: hidden !important;
        padding: 0 !important;
        margin: 0 !important;
        border: 2px solid #ffffff !important;
        box-shadow: 0 0 0 1px #94a3b8 !important;
        box-sizing: border-box !important;
        cursor: pointer !important;
    }}

    /* ZERO-SCROLL FLOATING DIALOG WITH ULTRA-COMPACT PERIODIC TABLE */
    div[role="dialog"] {{
        width: 94vw !important;
        max-width: 1340px !important;
        max-height: 95vh !important;
        overflow: hidden !important;
        padding: 0.25rem 0.75rem 0.4rem 0.75rem !important;
    }}
    div[role="dialog"] > div {{
        overflow: hidden !important;
    }}
    div[role="dialog"] [data-testid="stDialogHeader"] {{
        padding-bottom: 0.05rem !important;
        padding-top: 0.15rem !important;
        min-height: 1.4rem !important;
    }}
    div[role="dialog"] div[data-testid="stVerticalBlock"] {{
        gap: 0.07rem !important;
        overflow: hidden !important;
    }}
    div[role="dialog"] div[data-testid="stHorizontalBlock"] {{
        gap: 0.09rem !important;
    }}
    div[role="dialog"] div[data-testid="stButton"] > button {{
        min-height: 20px !important;
        height: 20px !important;
        padding: 0px 1px !important;
        border-radius: 4px !important;
    }}
    div[role="dialog"] div[data-testid="stButton"] > button p {{
        font-size: 0.75rem !important;
        line-height: 1.0 !important;
    }}

    /* Vibrant Green Single-Word "Create" / "צור" Button inside the Dialog */
    .st-key-dlg_green_create_btn button {{
        background-color: #16a34a !important;
        border-color: #15803d !important;
        color: #ffffff !important;
        min-height: 36px !important;
        height: 36px !important;
        font-size: 1.0rem !important;
        font-weight: 700 !important;
        box-shadow: 0 2px 6px rgba(22, 163, 74, 0.3) !important;
    }}
    .st-key-dlg_green_create_btn button:hover {{
        background-color: #15803d !important;
        border-color: #166534 !important;
    }}
    /* tooltips wrap inside a fixed width (long English words never leave the box) */
    [data-testid="stTooltipContent"] {{ max-width: 300px !important; white-space: normal !important; overflow-wrap: anywhere;
        direction: {'rtl' if st.session_state.lang == 'HE' else 'ltr'} !important; text-align: start !important; }}
    /* "select one or more spectra": the text is centred in its box */
    .st-key-select_hint [data-testid="stAlert"] * {{ text-align: center !important; }}
    /* the box reaches down the page: its distance from the bottom edge equals its distance from the header line above it
       (top of the box 70.8 px - header band bottom 52.9 px = 17.9 px) */
    .st-key-select_hint [data-testid="stAlert"] {{ min-height: calc(100vh - 70.8px - 17.9px) !important; align-items: center !important; }}
    .st-key-select_hint [data-testid="stAlertContainer"],
    .st-key-select_hint [data-testid="stAlert"] > div {{ justify-content: center !important; }}
    /* "Computing cascade tree in background...": same box as above, but its top edge lies on the top edge of the first
       spectrum tab (109.6 px) and its text is centred (English and Hebrew) */
    .st-key-anim_wait_box {{ margin-top: 6.9px !important; }}
    .st-key-anim_wait_box [data-testid="stAlert"] * {{ text-align: center !important; }}
    /* Hebrew: the sentence runs right to left, so its three dots stand at the left end */
    .st-key-anim_wait_box [data-testid="stAlert"] p {{ direction: {'rtl' if st.session_state.lang == 'HE' else 'ltr'} !important; unicode-bidi: isolate; }}
    .st-key-anim_wait_box [data-testid="stAlert"] {{
        min-height: calc(100vh - 109.6px - 17.9px) !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }}
    .st-key-anim_wait_box [data-testid="stAlertContainer"],
    .st-key-anim_wait_box [data-testid="stAlert"] > div {{ justify-content: center !important; }}
    /* the two buttons above the simulator (current spectrum / all spectra): their centre line is the centre line of the
       "Create new spectrum" button (34 px high, the two buttons are 28 px high: 3 px lower) */
    .st-key-return_all_spectra_btn, .st-key-view_current_spectrum_btn {{ position: relative; top: 3px; }}
    /* tooltips are above everything, also above the fixed header band (z-index 2000000) */
    div:has(> [data-testid="stTooltipContent"]) {{ z-index: 2147483000 !important; }}
    /* MUDIRAC cannot run the chosen element with the chosen nuclear model: the button is faded and does nothing */
    .st-key-dlg_green_create_btn button:disabled {{
        opacity: 0.35 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
    }}

    /* Select boxes: chosen value and every option centred (English and Hebrew) */
    [data-testid="stSelectbox"] input,
    [data-testid="stSelectbox"] [data-baseweb="select"] > div > div {{
        text-align: center !important;
        text-align-last: center !important;
        justify-content: center !important;
    }}
    [data-testid="stSelectbox"] input {{
        width: 100% !important;
        padding-left: 30px !important;   /* balances the arrow button on the right: text sits at the box centre */
        padding-right: 0 !important;
    }}
    [role="listbox"] [role="option"],
    [data-baseweb="menu"] li,
    [data-baseweb="menu"] [role="option"] {{
        display: flex !important;
        text-align: center !important;
        justify-content: center !important;
    }}
    [role="listbox"] [role="option"] > *,
    [data-baseweb="menu"] li > * {{
        text-align: center !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }}

    /* Hebrew labels that contain Latin letters / symbols (Y axis, %, QED) must read right-to-left */
    {'[data-testid="stCheckbox"] label [data-testid="stMarkdownContainer"] { direction: rtl; }' if st.session_state.lang == "HE" else ''}

    /* Light appearance only, and a professional navy for every primary control */
    :root {{ color-scheme: light; }}
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
        background-color: #ffffff !important;
        color: #0f172a;
    }}
    [data-testid="stBaseButton-primary"], button[kind="primary"] {{
        background-color: #0f4c81 !important;
        border-color: #0f4c81 !important;
        color: #ffffff !important;
    }}
    [data-testid="stBaseButton-primary"]:hover, button[kind="primary"]:hover {{
        background-color: #0c3b66 !important;
        border-color: #0c3b66 !important;
    }}
    [data-testid="stSlider"] [role="slider"], [data-testid="stSlider"] input[type="range"] {{ accent-color: #0f4c81; }}
    /* never fade / dim elements while a rerun is in progress (the spinning atom in the header signals the wait) */
    [data-stale="true"], [data-stale="true"] *, .stale-element {{ opacity: 1 !important; transition: none !important; }}
    .sim-loading-marker, .run-marker {{ display: none; }}
    [data-testid="stElementContainer"]:has(.sim-loading-marker), [data-testid="stElementContainer"]:has(.run-marker) {{ display: none !important; }}
    /* frozen copy of the create window shown while a language / text-size switch reruns the page */
    .dlg-ghost, .dlg-ghost * {{ pointer-events: none !important; animation: none !important; transition: none !important; }}
    /* spinning atom beside the "i" button (10 px from it, on the title side), only while such a switch is running;
       it takes no room, so nothing in the row moves */
    .st-key-font_size_slider {{ position: relative; }}
    .hdr-atom {{ display: block; width: 22px; height: 22px; visibility: hidden;
        position: absolute; right: calc(2 * 39px + 10px + 10px); top: 50%; margin-top: -11px; }}
    body.hdr-wait .hdr-atom {{ visibility: visible; animation: atomSpin 1.2s linear infinite; }}
    /* Compact font-size slider */
    /* the text-size control stands as far from the language switch (58 px) as the language switch from the "?" button */
    .st-key-font_size_slider {{ width: 126px; max-width: 126px; margin-left: auto; }}
    /* header row: the title takes the free width; text-size slider, language switch and the i / ? buttons keep their own
       width and stand exactly 10 px apart at every text size (a larger text pushes them to the left, never closer) */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) {{ gap: 10px !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) > [data-testid="stColumn"] {{
        flex: 0 0 auto !important; width: auto !important; min-width: 0 !important;
    }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) > [data-testid="stColumn"]:nth-child(3) {{
        flex: 1 1 auto !important;
    }}
    /* the title stands in the middle of the whole row, whatever the widths of the two side groups */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) {{ position: relative; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) > [data-testid="stColumn"]:nth-child(3),
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) > [data-testid="stColumn"]:nth-child(3) *:not(h3.app-title) {{
        position: static !important;
    }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-lang_toggle) > [data-testid="stColumn"]:nth-child(3) h3.app-title {{
        position: absolute; left: 50%; top: 50%; transform: translate(calc(-50% + var(--title-dx, 0px)), -50%); white-space: nowrap;
    }}
    /* (--title-dx: set by centreFix in the page script, so that the middle of the title is exactly the middle of the page) */
    .st-key-font_size_slider [data-testid="stSliderThumbValue"],
    .st-key-font_size_slider [data-testid="stSliderTickBar"] {{ display: none !important; }}
    .st-key-font_size_slider .fs-icon {{ display: flex; align-items: center; justify-content: center; transform: translateY(-7px); cursor: pointer; }}
    .st-key-font_size_slider .fs-icon:hover svg {{ stroke: #0f4c81; }}
    .st-key-font_size_slider [data-testid="stHorizontalBlock"] {{ gap: 2px !important; }}

    /* Font-size slider: four fixed dots (no fill line); the thumb marks the chosen one */
    .st-key-font_size_slider [data-testid="stSlider"] div:has(> [data-testid="stSliderTickBar"]) > div:first-child {{
        scale: 1 !important;
        /* dots are inset from the ends of the track so the two end dots are drawn completely */
        background:
            radial-gradient(circle at calc(4px + (100% - 8px) * 0)      50%, #94a3b8 3px, transparent 3.5px),
            radial-gradient(circle at calc(4px + (100% - 8px) * 0.3333) 50%, #94a3b8 3px, transparent 3.5px),
            radial-gradient(circle at calc(4px + (100% - 8px) * 0.6667) 50%, #94a3b8 3px, transparent 3.5px),
            radial-gradient(circle at calc(4px + (100% - 8px) * 1)      50%, #94a3b8 3px, transparent 3.5px) !important;
        height: 8px !important;
    }}

    /* Plot controls row: starts at the Y axis of the graph, buttons spread as far apart as possible */
    .st-key-plot_controls_row {{ padding-left: 0; padding-right: 0; position: relative; z-index: 30; margin-bottom: 10px; }}
    .st-key-plot_controls_row [data-testid="stHorizontalBlock"] {{
        justify-content: space-between !important;
        gap: 0 !important;
    }}
    .st-key-plot_controls_row [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        flex: 0 0 auto !important;
        width: auto !important;
    }}
    /* the columns INSIDE the column-width control keep real widths (wedge 120px + caption) */
    .st-key-plot_controls_row .st-key-col_width_wedge [data-testid="stHorizontalBlock"] {{
        justify-content: flex-start !important;
        gap: 8px !important;
    }}
    .st-key-plot_controls_row .st-key-col_width_wedge [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {{
        flex: 0 0 120px !important;
        width: 120px !important;
    }}
    .st-key-plot_controls_row .st-key-col_width_wedge [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {{
        flex: 0 0 auto !important;
        width: auto !important;
    }}
    .st-key-display_mode_box {{ width: fit-content; min-width: 105px; }}
    /* zoom / save buttons: a small frame that sits in the settings row; its tooltips reach down over the plot */
    .st-key-plot_btns {{ width: fit-content; }}
    .st-key-plot_btns [data-testid="stElementContainer"] {{ margin-bottom: -28px !important; position: relative; z-index: 40; }}
    .st-key-plot_btns iframe {{ display: block; border: 0 !important; background: transparent !important; width: 260px; }}
    /* full screen: the whole right-hand column (settings row + plot) is shown, with the same settings */
    [data-testid="stColumn"][data-plotfs] {{ background: #ffffff !important; padding: 14px 18px 8px 18px !important; overflow: auto; box-sizing: border-box; }}
    [data-testid="stColumn"][data-plotfs] .st-key-plot_frame iframe {{ height: calc(100vh - 100px) !important; }}
    [data-testid="stColumn"][data-plotfs] .st-key-plot_controls_row {{ padding-left: 0; padding-right: 0; }}
    /* the two buttons above the simulator: a little room between them */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-return_all_spectra_btn) {{ gap: 10px !important; }}
    /* a small gap between the list of spectrum tabs and what is shown next to it */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-spectra_cards_scroll) {{ gap: 12px !important; }}
    /* the plot always ends inside the window (its x axis stays visible) */
    .st-key-plot_frame iframe {{ height: clamp(340px, calc(100vh - 150px), 1100px) !important; }}
    /* Column width: no text at all - an elongated wedge, thin at one end and thick at the other; the four
       positions are fixed and the round thumb sits on the chosen one */
    .st-key-col_width_wedge [data-testid="stSliderTickBar"],
    .st-key-col_width_wedge [data-testid="stSliderThumbValue"],
    .st-key-col_width_wedge [data-testid="stSlider"] div:has(> [data-testid="stSliderTickBar"]) > div:first-child {{
        scale: 1 !important;
        height: 12px !important;
        background: linear-gradient(90deg, #d3dae4 0%, #c2cbd8 55%, #aab5c5 100%) !important;
        clip-path: polygon(0% 38%, 100% 0%, 100% 100%, 0% 62%);   /* elongated trapezoid: blunt thin end */
        border-radius: 2px;
    }}

    /* Plot controls row: one common font for every caption (radio rows, column-width caption, checkboxes) */
    .st-key-plot_controls_row label p,
    .st-key-plot_controls_row [data-testid="stCheckbox"] p,
    .st-key-plot_controls_row [data-testid="stMarkdownContainer"] p,
    .st-key-plot_controls_row .cw-label {{
        font-family: 'Calibri', 'Segoe UI', 'Rubik', Arial, sans-serif !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        line-height: 16px !important;
        color: #1e293b !important;
    }}
    /* the two check-box captions are written on two lines, like the column-width caption */
    .st-key-plot_controls_row [data-testid="stCheckbox"] p {{
        white-space: pre-line !important;
        text-align: center !important;
    }}

    /* Caption of the column-width control: two lines, 22px each (aligned with the two display-mode rows) */
    .cw-label {{ line-height: 16px; font-size: 0.92rem; text-align: center; white-space: nowrap; }}
    /* Every control of the row (radio rows, column-width caption + wedge, the two check boxes, the button frame) is
       centred on ONE horizontal line: the centre of the row. No translate hacks: each caption is exactly two
       16px lines (or two radio rows), and the check-box square sits on the line between its two text lines. */
    .st-key-plot_controls_row [data-testid="stCheckbox"] label {{ display: flex !important; align-items: center !important; }}
    .st-key-plot_controls_row [data-testid="stCheckbox"] label > div:nth-child(2) {{ margin-top: 0 !important; }}
    .st-key-plot_controls_row [data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] {{ line-height: 16px !important; font-size: 14px !important; }}
    .st-key-plot_controls_row [data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] p {{ display: block !important; margin: 0 !important; }}
    /* the column-width caption: its Streamlit wrappers are 17px tall while the text is two lines (32px); make them 32px */
    .st-key-col_width_wedge [data-testid="stColumn"]:has(.cw-label),
    .st-key-col_width_wedge [data-testid="stColumn"]:has(.cw-label) > [data-testid="stVerticalBlock"],
    .st-key-col_width_wedge [data-testid="stColumn"]:has(.cw-label) [data-testid="stElementContainer"],
    .st-key-col_width_wedge [data-testid="stColumn"]:has(.cw-label) [data-testid="stMarkdown"],
    .st-key-col_width_wedge [data-testid="stColumn"]:has(.cw-label) [data-testid="stMarkdown"] > div {{ height: 32px !important; min-height: 32px !important; }}
    .st-key-col_width_wedge [data-testid="stMarkdown"] > div:has(.cw-label) {{ align-items: flex-start !important; }}
    /* no hover pop-ups / value bubbles / tick labels on the wedge, whatever the Streamlit version calls them */
    .st-key-col_width_wedge [data-testid*="ThumbValue"],
    .st-key-col_width_wedge [data-testid*="TickBar"],
    .st-key-col_width_wedge [role="tooltip"] {{ display: none !important; visibility: hidden !important; }}
    .st-key-col_width_wedge [data-testid="stSlider"] div:has(> [data-testid="stSliderTickBar"]) > div:first-child {{ pointer-events: none; }}
    .st-key-col_width_wedge [data-testid="stSlider"] [data-testid="stWidgetLabel"] {{ display: none !important; }}
    .st-key-col_width_wedge {{ width: 171px; }}   /* = slider 120px + gap + caption: no empty margin, so the gaps of the row are equal */

    /* Display mode: two rows, exactly one checked (radio behaviour, checkbox look) */
    .st-key-display_mode_box [data-testid="stRadioGroup"] {{
        flex-direction: column !important;
        gap: 0 !important;
    }}
    /* exactly two 16px rows: the line between them is the centre line of the whole settings row */
    .st-key-display_mode_box [data-testid="stRadioGroup"],
    .st-key-display_mode_box [data-testid="stRadio"],
    .st-key-display_mode_box [data-testid="stElementContainer"],
    .st-key-display_mode_box [data-testid="stVerticalBlock"] {{ height: 32px !important; min-height: 32px !important; }}
    /* a little off the left edge: by the diameter of the radio circle (12px) */
    .st-key-display_mode_box {{ margin-left: 12px !important; }}
    .st-key-display_mode_box label[data-testid="stRadioOption"] {{
        margin: 0 !important;
        padding: 0 !important;
        height: 16px;
        display: flex; align-items: center;
        cursor: pointer;
    }}
    .st-key-display_mode_box label[data-testid="stRadioOption"] > div > div:first-child {{
        width: 12px !important; height: 12px !important;
        border: 1.5px solid #94a3b8 !important;
        border-radius: 50% !important;
        background: #ffffff !important;
        display: flex; align-items: center; justify-content: center;
    }}
    .st-key-display_mode_box label[data-testid="stRadioOption"] > div > div:first-child > div {{ display: none !important; }}
    .st-key-display_mode_box label[data-testid="stRadioOption"][data-selected="true"] > div > div:first-child {{
        background: #0f4c81 !important;
        border-color: #0f4c81 !important;
        box-shadow: inset 0 0 0 2px #ffffff;
    }}
    /* no title over the two options */
    .st-key-display_mode_box [data-testid="stRadio"] > [data-testid="stWidgetLabel"],
    .st-key-display_mode_box [data-testid="stWidgetLabel"] {{ display: none !important; }}
    .st-key-display_mode_box label[data-testid="stRadioOption"] p {{ margin: 0 !important; font-size: 0.92rem; line-height: 16px; }}

    /* Spectra list: scrollable, but without a visible scrollbar, so the cards never get narrower than the buttons above */
    div[data-testid="stVerticalBlock"]:has([class*="st-key-spectrum_card_"]) {{
        scrollbar-width: none !important;
        -ms-overflow-style: none !important;
    }}
    div[data-testid="stVerticalBlock"]:has([class*="st-key-spectrum_card_"])::-webkit-scrollbar {{
        display: none !important;
        width: 0 !important;
    }}

    /* Periodic-table element buttons: half of the previous height */
    /* the 9 rows share the box height evenly, so the whole table is visible without scrolling and no space is wasted */
    .st-key-periodic_table_box [data-testid="stButton"] button {{
        height: max(20px, calc((clamp(90px, calc(100vh - 235px), 1400px) - 60px) / 9)) !important;
        min-height: max(20px, calc((clamp(90px, calc(100vh - 235px), 1400px) - 60px) / 9)) !important;
        max-height: max(20px, calc((clamp(90px, calc(100vh - 235px), 1400px) - 60px) / 9)) !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }}
    .st-key-periodic_table_box [data-testid="stButton"] button {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
    }}
    .st-key-periodic_table_box [data-testid="stButton"] button > div,
    .st-key-periodic_table_box [data-testid="stButton"] button [data-testid="stMarkdownContainer"] {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 100%;
        height: 100%;
        margin: 0 !important;
        padding: 0 !important;
    }}
    .st-key-periodic_table_box [data-testid="stButton"] button p {{
        font-size: 0.85rem !important;
        line-height: 1 !important;
        margin: 0 !important;
        padding: 0 !important;
        text-align: center !important;
    }}
    .st-key-periodic_table_box [data-testid="stVerticalBlock"] {{ gap: 4px !important; }}

    /* The spectrum dialog never scrolls; only the periodic-table box inside it does */
    [role="dialog"], [role="dialog"] > div {{
        overflow: hidden !important;
    }}
    .st-key-periodic_table_box {{
        overflow-y: auto !important;
        overflow-x: hidden !important;
        /* the box shrinks with the window, so the whole dialog always fits and only the table scrolls */
        height: clamp(90px, calc(100vh - 235px), 1400px) !important;
        max-height: clamp(90px, calc(100vh - 235px), 1400px) !important;
    }}
    [data-testid="stLayoutWrapper"]:has(> .st-key-periodic_table_box) {{
        height: clamp(90px, calc(100vh - 235px), 1400px) !important;
        max-height: clamp(90px, calc(100vh - 235px), 1400px) !important;
    }}
    [data-testid="stDialog"] {{ overflow: hidden !important; }}
    [role="dialog"] {{ max-height: calc(100vh - 24px) !important; }}

    /* Dialog header: grey band separated from the body (same look as the wavefunctions window),
       with the close button in a white circle */
    [role="dialog"] h2 {{
        display: flex !important;
        align-items: center;
        height: 56px;
        margin: 0 !important;
        padding: 0 22px !important;
        background: #e2e8f0;
        border-bottom: 1.5px solid #94a3b8;
    }}
    [role="dialog"] h2 * {{ font-size: 16px !important; font-weight: 700 !important; color: #0f172a; }}
    [role="dialog"] button[aria-label="Close"] {{
        width: 30px !important;
        height: 30px !important;
        top: 13px !important;
        right: 20px !important;
        border-radius: 50% !important;
        background: #ffffff !important;
        color: #1e293b !important;
        border: 1.8px solid #475569 !important;
        display: flex !important;
        align-items: center;
        justify-content: center;
        padding: 0 !important;
        transition: all .15s ease;
        z-index: 40;
    }}
    [role="dialog"] button[aria-label="Close"]:hover {{
        background: #c1121f !important;
        color: #ffffff !important;
        border-color: #991b1b !important;
        transform: scale(1.08);
    }}

    /* Main header: a band of a different grey, fixed at the very top, above every window (dialog included) */
    .st-key-app_header {{
        position: fixed !important;
        top: 0;
        left: 0;
        width: 100vw !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 8px 1.3rem 6px 1.3rem;
        box-sizing: border-box;
        background: #eef1f6;
        border-bottom: 1.5px solid #cbd5e1;
        z-index: 2000000;
    }}
    [data-testid="stMainBlockContainer"].block-container {{ padding-top: 66px !important; }}
    /* the dialog starts under the header band */
    [data-testid="stDialog"] {{
        top: var(--hdr-h, 54px) !important;
        height: calc(100vh - var(--hdr-h, 54px)) !important;
        align-items: flex-start !important;
        padding-top: 0 !important;
    }}
    /* our own close button (white circle, red on hover) replaces Streamlit's X */
    /* same top and height (36px) as the green create button, so the centre of the circle lies exactly on that button's centre line */
    [role="dialog"] .st-key-dlg_close_x {{
        position: absolute !important;
        top: 10px !important;
        right: 20px !important;
        width: auto !important;
        height: 36px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;   /* vertical centring of the 30px circle in the 36px band */
        align-items: center !important;
        z-index: 45;
    }}
    .st-key-dlg_close_x, .st-key-dlg_close_x > *, .st-key-dlg_close_x [data-testid="stButton"] {{ margin: 0 !important; padding: 0 !important; }}
    .st-key-dlg_close_x [data-testid="stButton"] {{ display: flex !important; align-items: center !important; }}
    .st-key-dlg_close_x div[data-testid="stButton"] > button {{
        width: 30px !important;
        height: 30px !important;
        min-height: 30px !important;
        min-width: 30px !important;
        padding: 0 !important;
        border-radius: 50% !important;
        background: #ffffff !important;
        color: #1e293b !important;
        border: 1.8px solid #475569 !important;
        font-size: 15px !important;
        font-weight: 800 !important;
        line-height: 1 !important;
    }}
    .st-key-dlg_close_x.st-key-dlg_close_x div[data-testid="stButton"] > button:hover,
    .st-key-dlg_close_x.st-key-dlg_close_x div[data-testid="stButton"] > button:hover:focus {{
        background: #c1121f !important;
        background-color: #c1121f !important;
        color: #ffffff !important;
        border-color: #991b1b !important;
        transform: scale(1.08);
    }}
    .st-key-dlg_close_x div[data-testid="stButton"] > button p {{ margin: 0 !important; font-size: 0 !important; line-height: 0 !important; color: transparent !important; }}
    .st-key-dlg_close_x div[data-testid="stButton"] > button {{ position: relative !important; overflow: hidden !important; }}

    /* Every close "X" of the site: two perpendicular strokes, each one a full diameter of its circle
       (the button has no padding, so the pseudo-elements span exactly the inner circle) */
    .st-key-dlg_close_x div[data-testid="stButton"] > button::before,
    .st-key-dlg_close_x div[data-testid="stButton"] > button::after,
    [role="dialog"] button[aria-label="Close"]::before,
    [role="dialog"] button[aria-label="Close"]::after {{
        content: "";
        position: absolute;
        left: 0;
        top: 50%;
        width: 100%;
        height: 1.3px;
        margin-top: -0.65px;
        background: currentColor;
        transform: rotate(45deg);
        pointer-events: none;
    }}
    .st-key-dlg_close_x div[data-testid="stButton"] > button::after,
    [role="dialog"] button[aria-label="Close"]::after {{ transform: rotate(-45deg); }}
    [role="dialog"] button[aria-label="Close"] {{ overflow: hidden !important; }}
    [role="dialog"] button[aria-label="Close"] svg {{ display: none !important; }}

    /* element buttons that MUDIRAC cannot handle (Z > 111): faded, not clickable */
    .st-key-periodic_table_box [data-testid="stButton"] button:disabled {{
        opacity: 0.3 !important;
        cursor: not-allowed !important;
        pointer-events: auto;
    }}

    /* The create/edit window is a full page under the header: opaque background, nothing dimmed behind it */
    [data-testid="stDialog"] {{
        background: #ffffff !important;
        backdrop-filter: none !important;
    }}
    [data-testid="stDialog"] {{ padding: 0 !important; }}
    [data-testid="stDialog"] > div {{
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        max-width: none !important;
        height: 100% !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        border: none !important;
    }}
    [role="dialog"] {{
        margin: 0 !important;
        top: 0 !important;
        width: 100vw !important;
        max-width: 100vw !important;
        height: calc(100vh - var(--hdr-h, 54px)) !important;
        max-height: calc(100vh - var(--hdr-h, 54px)) !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }}

    /* no spectrum yet: the "Create new spectrum" button takes the whole width of the page (same height as before), the
       other column is hidden; its label stays centred */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-top_add_full) > [data-testid="stColumn"]:has(.st-key-top_add_full) {{
        flex: 1 1 100% !important; width: 100% !important; min-width: 100% !important;
    }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-top_add_full) > [data-testid="stColumn"]:not(:has(.st-key-top_add_full)) {{
        display: none !important;
    }}
    /* the page container is 99.4 % wide and sits at the left, which leaves 0.6 % more room on the right than on the left:
       this button takes that strip too, so its distances from the two edges of the page are equal */
    .st-key-top_add_full {{ width: calc(100% + 0.6vw) !important; max-width: none !important; }}
    .st-key-top_add_full > * {{ width: 100% !important; }}
    .st-key-top_add_full button {{ justify-content: center !important; }}
    /* start page: a narrower create button, centred, with the site guide under it */
    .st-key-top_add_full [data-testid="stButton"] {{ display: flex !important; justify-content: center !important; }}
    .st-key-top_add_full .st-key-top_add_spec_btn button {{ width: min(440px, 100%) !important; height: 40px !important; min-height: 40px !important; max-height: 40px !important; }}
    .st-key-top_add_full .st-key-top_add_spec_btn button p {{ font-size: 1.13em !important; }}
    /* the "+" stands beside the label without taking room, so the label itself is the centred part of the button
       (centreFix in the page script then puts the middle of the label exactly in the middle of the page) */
    .st-key-top_add_full .st-key-top_add_spec_btn button span:has(> span > [data-testid="stIconMaterial"]) {{ position: relative; }}
    .st-key-top_add_full .st-key-top_add_spec_btn button span:has(> [data-testid="stIconMaterial"]) {{
        position: absolute; right: calc(100% + 8px); top: 50%; transform: translateY(-50%); margin: 0 !important;
    }}
    /* the guide fills the rest of the window (the page itself never scrolls) */
    .st-key-empty_site_guide {{ margin: 30px 0 0 0 !important; }}
    .st-key-empty_site_guide iframe {{ height: calc(100vh - var(--hdr-h, 54px) - 102px) !important; min-height: 260px; }}
    .st-key-top_add_full button > div {{ justify-content: center !important; }}
    /* "Create new spectrum" and "Select all" buttons: identical height, on the same line */
    .st-key-top_add_spec_btn button,
    .st-key-toggle_select_all_btn button {{
        height: 34px !important;
        min-height: 34px !important;
        max-height: 34px !important;
        box-sizing: border-box !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }}

    /* captions of the isotope / initial-level rows: same look as the other setting titles */
    .dlg-cap {{
        font-family: 'Calibri', 'Segoe UI', 'Rubik', Arial, sans-serif !important;   /* same font as "Nuclear model" etc. */
        font-size: 0.875rem !important;
        font-weight: 400 !important;
        color: #0f172a;
        line-height: 16px;
        height: 16px;
        margin: 0 !important;
        text-align: center;
        width: 100%;
        white-space: nowrap;
    }}

    /* label above the muon-count slider thumb (from 5,000 muons on) */
    .st-key-muon_slider_box {{ position: relative; z-index: 50; }}
    /* the label pokes up over the grey band: the window body must not clip it and the band stays underneath */
    [data-testid="stDialog"] section > div:not(:has(h2)) {{ overflow: visible !important; }}
    [data-testid="stDialog"] h2 {{ position: relative !important; z-index: 0 !important; }}
    .st-key-muon_slider_box [data-testid="stElementContainer"] {{ position: static !important; }}
    .sim-tip {{
        position: absolute;
        top: auto;
        bottom: calc(100% + 6px);
        text-align: center;
        line-height: 1.35;
        transform: translateX(-50%);
        background: #0f172a;
        color: #ffffff;
        font-size: 11.5px;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 6px;
        white-space: nowrap;
        border: 1px solid #334155;
        box-shadow: 0 3px 8px rgba(15, 23, 42, 0.35);
        z-index: 60;
        pointer-events: none;
    }}

    /* ===== Create / edit window: the settings row =====
       left to right: number of muons | muon distribution | initial level | isotope | nuclear model | 3 corrections.
       Every title sits above its box; the free room is split into equal gaps. The initial-level group holds two
       boxes for the delta distribution and one otherwise, and is built so that the row keeps the same height. */
    {_TOP_ROW} {{
        gap: 16px !important; justify-content: space-between !important; flex-wrap: nowrap !important;
        align-items: flex-start !important; min-height: 80px;
    }}
    {_TOP_ROW} > [data-testid="stColumn"] {{ flex: 0 1 auto !important; min-width: 0 !important; }}
    {_TOP_ROW} > [data-testid="stColumn"]:nth-child(1) {{ width: calc((100% - 12px) * 0.196) !important; }}
    {_TOP_ROW} > [data-testid="stColumn"]:nth-child(2) {{ width: calc((100% - 12px) * 0.108) !important; }}
    {_TOP_ROW} > [data-testid="stColumn"]:nth-child(3) {{ width: calc((100% - 12px) * 0.108) !important; }}
    {_TOP_ROW} > [data-testid="stColumn"]:nth-child(4) {{ width: calc((100% - 12px) * 0.142) !important; }}
    {_TOP_ROW} > [data-testid="stColumn"]:nth-child(5) {{ width: calc((100% - 12px) * 0.108) !important; }}
    /* the corrections column has the same fixed width in every language (it fits the longest, English, captions), so the
       other columns - spread with space-between - never move when the language changes */
    {_TOP_ROW} > [data-testid="stColumn"]:nth-child(6) {{ width: 14rem !important; flex-shrink: 0 !important; }}
    /* titles: one look and one height everywhere in the row */
    {_TOP_ROW} [data-testid="stWidgetLabel"] {{ min-height: 0 !important; height: 16px !important; margin: 0 0 2px 0 !important; padding: 0 !important; }}
    {_TOP_ROW} [data-testid="stWidgetLabel"] p {{ line-height: 16px !important; margin: 0 !important; }}
    /* select boxes of the row: 30 px high */
    {_TOP_ROW} [data-testid="stSelectbox"] div[role="group"] {{ height: 30px !important; min-height: 30px !important; }}
    {_TOP_ROW} [data-testid="stSelectbox"] > div:has(> div[role="group"]) {{ min-height: 0 !important; }}
    div[data-testid="stVerticalBlock"].st-key-dlg_lvl_group,
    div[data-testid="stVerticalBlock"].st-key-dlg_iso_group,
    div[data-testid="stVerticalBlock"].st-key-dlg_corr_group {{ gap: 2px !important; }}
    .st-key-dlg_lvl_group [data-testid="stMarkdownContainer"] p,
    .st-key-dlg_iso_group [data-testid="stMarkdownContainer"] p {{ margin: 0 !important; }}
    .st-key-dlg_lvl_group [data-testid="stMarkdownContainer"],
    .st-key-dlg_iso_group [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
    /* Streamlit gives an HTML-only markdown block a 1 px height: give the two titles their real height */
    .st-key-dlg_lvl_group [data-testid="stElementContainer"]:has(.dlg-cap),
    .st-key-dlg_iso_group [data-testid="stElementContainer"]:has(.dlg-cap),
    .st-key-dlg_lvl_group [data-testid="stElementContainer"]:has(.dlg-cap) *,
    .st-key-dlg_iso_group [data-testid="stElementContainer"]:has(.dlg-cap) * {{ height: 16px !important; min-height: 16px !important; }}

    /* the "?" button of the help guide, right of the language switch */
    .help-q {{
        width: 39px; height: 39px; min-width: 39px; flex: 0 0 39px; border-radius: 50%; box-sizing: border-box;
        border: 1px solid #e2e8f0; background: #e2e8f0; color: #334155;      /* the grey of the chosen language segment */
        font-weight: 700; font-size: 22.5px; line-height: 37px; text-align: center;
        cursor: pointer; user-select: none; margin: 0 0 0 auto; position: relative; top: -7.5px;
    }}
    .help-q:hover, .help-q:focus-visible {{ background: #cbd5e1; border-color: #cbd5e1; outline: none; }}
    /* two buttons: "about the project" (i) and the site guide (?) */
    .help-btns {{ display: flex; justify-content: flex-end; gap: 10px; position: relative; top: {-7.5 * scale_factor:.2f}px; direction: ltr; }}
    .help-btns .help-q {{ margin: 0; top: 0; }}
    .help-q.help-i {{ font-family: Georgia, 'Times New Roman', serif; font-style: italic; font-size: 24px; }}

    /* Language switch: two segments, the chosen one filled, the other faded (no radio dots) */
    .st-key-lang_toggle [data-testid="stRadioGroup"] {{
        display: inline-flex !important;
        flex-direction: row !important;
        gap: 2px !important;
        background: transparent;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1px;
        height: 39px; box-sizing: border-box; align-items: stretch !important;   /* = the diameter of the i / ? buttons */    }}
    .st-key-lang_toggle [data-testid="stRadioGroup"] > * {{ height: 100% !important; }}
    .st-key-lang_toggle label[data-testid="stRadioOption"] {{ display: flex !important; align-items: center !important; height: 100% !important; box-sizing: border-box; }}
    .st-key-lang_toggle label[data-testid="stRadioOption"] {{
        margin: 0 !important;
        padding: 1px 8px !important;
        border-radius: 6px;
        cursor: pointer;
        opacity: 0.4;
        transition: background-color .12s ease, opacity .12s ease;
    }}
    .st-key-lang_toggle label[data-testid="stRadioOption"] > div > div:first-child {{
        display: none !important;
    }}
    .st-key-lang_toggle label[data-testid="stRadioOption"] p {{
        margin: 0 !important;
        font-weight: 500;
        font-size: 0.72rem !important;
        color: #64748b;
    }}
    .st-key-lang_toggle label[data-testid="stRadioOption"][data-selected="true"] {{
        background: #e2e8f0;
        opacity: 1;
    }}
    .st-key-lang_toggle label[data-testid="stRadioOption"][data-selected="true"] p {{
        color: #334155 !important;
    }}

    /* Dialog: widget titles centred over their select box / slider */
    [role="dialog"] [data-testid="stSelectbox"] [data-testid="stWidgetLabel"],
    [role="dialog"] [data-testid="stSlider"] [data-testid="stWidgetLabel"] {{
        justify-content: center !important;
        width: 100% !important;
    }}
    [role="dialog"] [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] > span,
    [role="dialog"] [data-testid="stSlider"] [data-testid="stWidgetLabel"] > span,
    [role="dialog"] [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"],
    [role="dialog"] [data-testid="stSlider"] [data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"],
    [role="dialog"] [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] p,
    [role="dialog"] [data-testid="stSlider"] [data-testid="stWidgetLabel"] p {{
        width: 100% !important;
        text-align: center !important;
    }}

    /* "Create" button in the top row of the dialog, left of the close (X) button */
    [role="dialog"] {{ position: relative; }}
    [role="dialog"] .st-key-dlg_green_create_btn {{
        position: absolute !important;
        top: 10px !important;
        right: 64px !important;
        width: auto !important;
        min-width: 230px;
        z-index: 30;
    }}

    /* Streamlit sliders lay their thumb out right-to-left when the browser language is Hebrew, while the
       coloured fill and the end labels were drawn left-to-right. Mirror them so all three agree. */
    [data-testid="stSlider"] div:has(> [data-testid="stSliderTickBar"]) > div:first-child {{
        scale: -1 1;
    }}
    [data-testid="stSlider"] [data-testid="stSliderTickBar"] {{
        direction: rtl !important;
    }}

    /* Centered widget labels above the display-mode selector and the column-width slider */
    .st-key-display_mode_box [data-testid="stWidgetLabel"],
    .st-key-col_width_wedge [data-testid="stWidgetLabel"] {{
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
    }}
    .st-key-display_mode_box [data-testid="stWidgetLabel"] p,
    .st-key-col_width_wedge [data-testid="stWidgetLabel"] p {{
        text-align: center !important;
        width: 100%;
    }}

    /* ELONGATED TRIANGLE / WEDGE SLIDER FOR COLUMN WIDTH (4 STATIONS, NO NUMBERS) */
    .st-key-col_width_wedge [data-testid="stThumbValue"],
    .st-key-col_width_wedge [data-testid="stTickBar"] {{
        display: none !important;
    }}
    .st-key-col_width_wedge [data-baseweb="slider"] > div > div:first-child {{
        height: 14px !important;
        background: linear-gradient(90deg, #94a3b8 0%, #0f4c81 100%) !important;
        clip-path: polygon(0% 50%, 100% 0%, 100% 100%) !important;
        border-radius: 2px !important;
    }}

    /* Standard Main Workspace Buttons + Instant True Subscript for fractions (9/2) */
    div[data-testid="stButton"] > button {{
        min-height: 28px !important;
        padding: 1px 3px !important;
        min-width: 0px !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        transition: transform 0.10s ease, box-shadow 0.10s ease, background-color 0.10s ease !important;
    }}
    div[data-testid="stButton"] > button p {{
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        font-size: 0.88rem !important;
        margin: 0 !important;
    }}
    div[data-testid="stButton"] > button code {{
        font-family: 'Calibri', 'Segoe UI', sans-serif !important;
        font-size: 0.74em !important;
        font-weight: 700 !important;
        vertical-align: -0.25em !important;
        background: transparent !important;
        color: inherit !important;
        padding: 0 !important;
        border: none !important;
    }}
    div[data-testid="stButton"] > button:hover {{
        transform: scale(1.03) !important;
        z-index: 30 !important;
        box-shadow: 0 2px 7px rgba(2, 132, 199, 0.32) !important;
        border-color: #0284c7 !important;
    }}
    div[data-testid="stButton"] > button[kind="secondary"]:hover {{
        background-color: #e0f2fe !important;
        color: #0f4c81 !important;
    }}

    /* Hide the internal drag-order bridge input off-screen */
    .st-key-_card_order_bridge, .st-key-_color_bridge, .st-key-_n_bridge {{
        position: fixed !important;
        left: -9999px !important;
        top: -9999px !important;
        width: 1px !important;
        height: 1px !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }}

    /* Colour swatch (opens the fixed palette popup) */
    .color-swatch {{
        width: 26px; height: 26px; margin: 0 auto;
        border-radius: 50%;
        border: 2px solid #ffffff;
        box-shadow: 0 0 0 1px #94a3b8;
        cursor: pointer;
        transition: transform .12s ease;
    }}
    .color-swatch:hover {{ transform: scale(1.12); }}

    /* Drag handle ↕ styling */
    .drag-handle-box {{
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 38px;
        margin: 0 auto;
        font-size: 19px;
        font-weight: 600;
        color: #94a3b8;
        cursor: grab;
        user-select: none;
        -webkit-user-select: none;
        border-radius: 8px;
        touch-action: none;
    }}
    .drag-handle-box:hover {{
        background-color: #eef2f7;
        color: #0f4c81;
    }}
    .drag-handle-box:active {{
        cursor: grabbing;
    }}

    /* the list of spectrum cards scrolls a little past the last card, so its checkbox is fully visible */
    .st-key-spectra_cards_scroll::after {{ content: ""; display: block; flex: 0 0 44px; height: 44px; }}

    /* Lock Matplotlib plot aspect ratio & height so main page never scrolls */
    [data-testid="stImage"] img {{
        max-height: calc(100vh - 140px) !important;
        width: auto !important;
        margin: 0 auto !important;
        display: block !important;
        object-fit: contain !important;
    }}
</style>
""", unsafe_allow_html=True)


# JS engine injected into the parent page (card drag & drop, wheel-on-sliders, colour popover).
PARENT_UI_JS = r'''
(function () {
    // This code runs in the PARENT (Streamlit page) context, so it never goes stale
    // when the small helper iframe that installs it is re-created on a rerun.
    var W = window, D = document;
    if (W.__muonUI && W.__muonUI.destroy) { try { W.__muonUI.destroy(); } catch (err) {} }
    var cleanups = [];
    function on(target, type, fn, opts) {
        target.addEventListener(type, fn, opts);
        cleanups.push(function () { target.removeEventListener(type, fn, opts); });
    }

    // ------------------------------------------------------------------ card drag & drop
    var CARD_SEL = '[class*="st-key-spectrum_card_"]';
    function allCards() {
        return Array.prototype.slice.call(D.querySelectorAll(CARD_SEL)).filter(function (c) {
            return !c.classList.contains('drag-ghost') && c.querySelector('.drag-handle-box');
        });
    }
    function cardId(card) {
        var m = /st-key-spectrum_card_([A-Za-z0-9-]+)/.exec(String(card.className));
        return m ? m[1] : null;
    }
    function findCard(id) {
        var cards = allCards();
        for (var i = 0; i < cards.length; i++) { if (cardId(cards[i]) === id) return cards[i]; }
        return null;
    }
    function scrollParentOf(el) {
        var p = el.parentElement;
        while (p && p !== D.body && p !== D.documentElement) {
            var oy = W.getComputedStyle(p).overflowY;
            if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight + 1) return p;
            p = p.parentElement;
        }
        return null;
    }
    function commitOrder(ids) { commitBridge('.st-key-_card_order_bridge input', Date.now() + ':' + ids.join(',')); }
    function commitBridge(selector, payload) {
        var input = D.querySelector(selector);
        if (!input) return;
        var setter = Object.getOwnPropertyDescriptor(W.HTMLInputElement.prototype, 'value').set;
        setter.call(input, payload);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.focus();
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
        input.blur();
    }

    var g = null;
    var raf = 0;

    function computeDrop() {
        var src = findCard(g.id);
        if (!src) return null;
        var others = allCards().filter(function (c) { return c !== src; });
        var center = (g.y - g.offY) + g.h / 2;
        var idx = 0;
        for (var i = 0; i < others.length; i++) {
            var r = others[i].getBoundingClientRect();
            if (r.top + r.height / 2 < center) idx = i + 1;
        }
        return { src: src, others: others, idx: idx };
    }

    function endGesture() {
        if (!g) return;
        clearInterval(raf);
        if (g.ghost && g.ghost.parentNode) g.ghost.parentNode.removeChild(g.ghost);
        if (g.line && g.line.parentNode) g.line.parentNode.removeChild(g.line);
        var src = findCard(g.id);
        if (src) src.classList.remove('dragging-card');
        D.body.style.cursor = g.prevCursor || '';
        D.body.style.userSelect = g.prevSelect || '';
        g = null;
    }

    function tick() {
        if (!g) return;
        var drop = computeDrop();
        if (!drop) { endGesture(); return; }
        var top = g.y - g.offY;
        g.ghost.style.top = top + 'px';
        g.ghost.style.left = (g.x - g.offX) + 'px';

        var view = g.scroller ? g.scroller.getBoundingClientRect()
                              : { top: 0, bottom: W.innerHeight, left: 0, right: W.innerWidth };
        // Auto-scroll as soon as the (transparent) ghost touches the top / bottom edge of the list.
        if (g.scroller && g.moved) {
            var edge = 8, amt = 0;
            if (top < view.top + edge) {
                amt = -(6 + Math.min(28, (view.top + edge - top) * 0.3));
            } else if (top + g.h > view.bottom - edge) {
                amt = 6 + Math.min(28, (top + g.h - (view.bottom - edge)) * 0.3);
            }
            if (amt) g.scroller.scrollTop += amt;
        }

        // Drop indicator line
        var y;
        if (drop.idx < drop.others.length) y = drop.others[drop.idx].getBoundingClientRect().top - 4;
        else if (drop.others.length) y = drop.others[drop.others.length - 1].getBoundingClientRect().bottom + 2;
        else y = drop.src.getBoundingClientRect().top;
        y = Math.max(view.top, Math.min(view.bottom - 6, y));
        var sr = drop.src.getBoundingClientRect();
        g.line.style.top = y + 'px';
        g.line.style.left = sr.left + 'px';
        g.line.style.width = sr.width + 'px';
    }

    on(D, 'pointerdown', function (e) {
        if (e.button !== undefined && e.button !== 0) return;
        var handle = e.target && e.target.closest ? e.target.closest('.drag-handle-box') : null;
        if (!handle) return;
        var card = handle.closest(CARD_SEL);
        if (!card) return;
        e.preventDefault();
        e.stopPropagation();
        var rect = card.getBoundingClientRect();

        var ghost = card.cloneNode(true);
        Array.prototype.forEach.call(ghost.querySelectorAll('[id]'), function (n) { n.removeAttribute('id'); });
        ghost.classList.remove('dragging-card');
        ghost.classList.add('drag-ghost');
        ghost.style.cssText = 'position:fixed;margin:0;box-sizing:border-box;pointer-events:none;' +
            'z-index:2147483000;opacity:0.55;transition:none;transform:scale(1.02);' +
            'box-shadow:0 14px 30px rgba(15,76,129,0.35);' +
            'left:' + rect.left + 'px;top:' + rect.top + 'px;width:' + rect.width + 'px;height:' + rect.height + 'px;';
        D.body.appendChild(ghost);

        var line = D.createElement('div');
        line.style.cssText = 'position:fixed;height:6px;border-radius:3px;background:#0f4c81;' +
            'pointer-events:none;z-index:2147482999;box-shadow:0 0 6px rgba(15,76,129,0.6);';
        D.body.appendChild(line);

        card.classList.add('dragging-card');
        g = {
            id: cardId(card), ghost: ghost, line: line,
            x: e.clientX, y: e.clientY, startY: e.clientY,
            offX: e.clientX - rect.left, offY: e.clientY - rect.top, h: rect.height,
            scroller: scrollParentOf(card), moved: false, pointerId: e.pointerId,
            prevCursor: D.body.style.cursor, prevSelect: D.body.style.userSelect
        };
        D.body.style.cursor = 'grabbing';
        D.body.style.userSelect = 'none';
        try { handle.setPointerCapture(e.pointerId); } catch (err) {}
        raf = setInterval(tick, 16);
    }, true);

    on(D, 'pointermove', function (e) {
        if (!g || e.pointerId !== g.pointerId) return;
        e.preventDefault();
        g.x = e.clientX;
        g.y = e.clientY;
        if (Math.abs(e.clientY - g.startY) > 4) g.moved = true;
    }, true);

    on(D, 'pointerup', function (e) {
        if (!g || e.pointerId !== g.pointerId) return;
        e.preventDefault();
        var drop = computeDrop();
        var moved = g.moved;
        var id = g.id;
        var before = allCards().map(cardId);
        endGesture();
        if (!drop || !moved) return;
        var ids = drop.others.map(cardId);
        ids.splice(drop.idx, 0, id);
        if (ids.join(',') !== before.join(',')) commitOrder(ids);
    }, true);

    on(D, 'pointercancel', function (e) { if (g && e.pointerId === g.pointerId) endGesture(); }, true);
    on(D, 'keydown', function (e) {
        if (g && e.key === 'Escape') { endGesture(); return; }
        var handle = e.target && e.target.closest ? e.target.closest('.drag-handle-box') : null;
        if (!handle || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
        var ids = allCards().map(cardId);
        var from = ids.indexOf(cardId(handle.closest(CARD_SEL)));
        var to = from + (e.key === 'ArrowUp' ? -1 : 1);
        if (from < 0 || to < 0 || to >= ids.length) return;
        e.preventDefault();
        var tmp = ids[from]; ids[from] = ids[to]; ids[to] = tmp;
        commitOrder(ids);
    }, true);

    // ------------------------------------------------------------------ fixed colour palette popup
    var PALETTE = __PALETTE__;
    var pal = null;
    function closePalette() { if (pal && pal.parentNode) pal.parentNode.removeChild(pal); pal = null; }
    function rgbToHex(rgb) {
        var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(rgb || '');
        if (!m) return '';
        return '#' + [m[1], m[2], m[3]].map(function (v) { return ('0' + parseInt(v, 10).toString(16)).slice(-2); }).join('');
    }
    function openPalette(sw) {
        var card = sw.closest(CARD_SEL);
        var id = card ? cardId(card) : null;
        if (!id) return;
        closePalette();
        var current = rgbToHex(W.getComputedStyle(sw).backgroundColor).toLowerCase();
        pal = D.createElement('div');
        pal.style.cssText = 'position:fixed;z-index:2147483001;background:#fff;border:1px solid #cfd6e0;' +
            'border-radius:10px;padding:8px;box-shadow:0 10px 28px rgba(15,23,42,.28);' +
            'display:grid;grid-template-columns:repeat(4,28px);gap:10px;';
        PALETTE.forEach(function (col) {
            var b = D.createElement('div');
            var sel = (col.toLowerCase() === current);
            b.style.cssText = 'width:28px;height:28px;border-radius:8px;cursor:pointer;background:' + col + ';' +
                (sel ? 'box-shadow:0 0 0 2px #fff,0 0 0 4px #0f4c81;' : 'box-shadow:inset 0 0 0 1px rgba(0,0,0,.15);');
            b.setAttribute('data-col', col);
            pal.appendChild(b);
        });
        D.body.appendChild(pal);
        var r = sw.getBoundingClientRect();
        var pw = pal.offsetWidth, ph = pal.offsetHeight;
        var left = r.left - pw - 10;
        if (left < 6) left = Math.min(W.innerWidth - pw - 6, r.right + 10);
        var top = Math.max(6, Math.min(W.innerHeight - ph - 6, r.top + r.height / 2 - ph / 2));
        pal.style.left = left + 'px';
        pal.style.top = top + 'px';
        pal._cardId = id;
    }
    on(D, 'click', function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        if (pal && pal.contains(t)) {
            var col = t.getAttribute('data-col');
            if (col) { var id = pal._cardId; closePalette(); commitBridge('.st-key-_color_bridge input', Date.now() + ':' + id + ':' + col); }
            return;
        }
        var sw = t.closest('.color-swatch');
        if (sw) { e.preventDefault(); e.stopPropagation(); openPalette(sw); return; }
        closePalette();
    }, true);
    on(D, 'keydown', function (e) { if (e.key === 'Escape') closePalette(); }, true);
    on(D, 'scroll', function () { closePalette(); }, true);

    // ------------------------------------------------------------------ dialogs start exactly where the header band ends
    function syncHeaderHeight() {
        var h = D.querySelector('.st-key-app_header');
        if (h) D.documentElement.style.setProperty('--hdr-h', Math.round(h.getBoundingClientRect().bottom) + 'px');
    }
    syncHeaderHeight();
    var hdrTimer = setInterval(syncHeaderHeight, 400);
    cleanups.push(function () { clearInterval(hdrTimer); });
    on(W, 'resize', syncHeaderHeight);

    // ------------------------------------------------------------------ keep the fixed top header usable while a dialog is open
    // (a modal marks the whole app root "inert"; the dark overlay still blocks everything except the header band)
    function unInert() {
        Array.prototype.forEach.call(D.querySelectorAll('body > div[inert]'), function (el) { el.removeAttribute('inert'); });
    }
    var inertObserver = new MutationObserver(unInert);
    inertObserver.observe(D.body, { attributes: true, attributeFilter: ['inert'], childList: true, subtree: true });
    cleanups.push(function () { inertObserver.disconnect(); });
    unInert();

    // ------------------------------------------------------------------ language / text-size switch while the create window is open
    // Streamlit drops the window for the length of the rerun. A frozen copy of it is shown meanwhile, and the
    // spinning atom next to the text-size slider is on until the rerun has finished.
    var ghost = null, snap = null, snapTime = 0, busyStart = 0, idleSince = 0;
    function realDialog() { return D.querySelector('body > [data-testid="stDialog"]:not(.dlg-ghost)'); }
    function switchTouched(e) {
        var t = e.target && e.target.closest ? e.target.closest('.st-key-lang_toggle, .st-key-font_size_slider') : null;
        if (!t) return;
        var dlg = realDialog();
        if (dlg && !ghost && Date.now() - snapTime > 700) { snap = dlg.cloneNode(true); snapTime = Date.now(); }
        busyStart = Date.now(); idleSince = 0;
        D.body.classList.add('hdr-busy');
    }
    ['pointerdown', 'keydown', 'wheel', 'click'].forEach(function (ev) { on(D, ev, switchTouched, true); });
    // The atom spins from the user's action until its result is really on screen. The server tells the page when a run
    // has finished: '.run-marker.full-marker' changes at the end of every full script run, '.dlg-marker' at the end of
    // every run of the create window. After that the page also waits for images / frames to finish loading.
    var runSince = 0, actAt = 0, actFull0 = '', actDlg0 = '', actCur = '', actLastMark = 0, actSawRun = false, actRunEnd = 0;
    function markSeq(sel) { var m = D.querySelector(sel); return m ? m.getAttribute('data-seq') : ''; }
    function startAction() {
        actAt = Date.now(); actFull0 = markSeq('.run-marker.full-marker'); actDlg0 = markSeq('.dlg-marker');
        actCur = actFull0 + '/' + actDlg0; actLastMark = 0; actSawRun = false; actRunEnd = 0;
    }
    on(D, 'pointerdown', function (e) {
        var t = e.target;
        // a faded (disabled) button / option does nothing, so it must not start the spinning atom either
        if (t && t.closest && t.closest('button:disabled, [aria-disabled="true"], [data-disabled="true"]')) return;
        if (t && t.closest && !t.closest('.color-swatch, .drag-handle-box') &&
            t.closest('button, [role="button"], [role="option"], [role="slider"], label, input, [data-baseweb], [data-testid="stSlider"], .fs-icon')) {
            startAction();
        }
    }, true);
    on(D, 'keydown', function (e) {
        if (e.key === 'Enter' || e.key.indexOf('Arrow') === 0) {
            if (e.target && e.target.closest && e.target.closest('button:disabled, [aria-disabled="true"]')) return;
            startAction();
        }
    }, true);

    // isotope menu: entries that MUDIRAC cannot run with the chosen nuclear model carry an invisible marker
    // (two zero-width spaces at the end of the text); they are shown faded and cannot be chosen
    function fadeUnavailableOptions() {
        var opts = D.querySelectorAll('[role="option"]');
        for (var i = 0; i < opts.length; i++) {
            var o = opts[i], off = /\u200b\u200b\s*$/.test(o.textContent || '');
            if (off) {
                if (o.getAttribute('aria-disabled') !== 'true') {
                    o.setAttribute('aria-disabled', 'true'); o.style.opacity = '0.35'; o.style.cursor = 'not-allowed';
                }
            } else if (o.getAttribute('aria-disabled') === 'true') {
                o.removeAttribute('aria-disabled'); o.style.opacity = ''; o.style.cursor = '';
            }
        }
    }
    // browser zoom: the layout is built for 100 %, so the zoom shortcuts (Ctrl + wheel, Ctrl + / Ctrl -) are switched off
    // (Ctrl 0 still resets). A page can not stop the zoom of the browser menu; the app has its own text-size slider.
    D.addEventListener('wheel', function (e) { if (e.ctrlKey) e.preventDefault(); }, { passive: false, capture: true });
    on(D, 'keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && ['+', '-', '=', '_', 'Add', 'Subtract'].indexOf(e.key) >= 0) e.preventDefault();
    }, true);
    // the same inside every frame of the page (spectra, start-page guide ...): a wheel over a frame never reaches this page
    function guardZoom(doc) {
        if (!doc || doc.__muonZoomGuard) return;
        doc.__muonZoomGuard = true;
        doc.addEventListener('wheel', function (e) { if (e.ctrlKey) e.preventDefault(); }, { passive: false, capture: true });
        doc.addEventListener('keydown', function (e) {
            if ((e.ctrlKey || e.metaKey) && ['+', '-', '=', '_', 'Add', 'Subtract'].indexOf(e.key) >= 0) e.preventDefault();
        }, true);
    }
    // the middle of the site title, and of the label of the start-page create button, is exactly the middle of the page
    // (the columns around them are not symmetric): each is shifted by the measured difference
    function centreFix() {
        var cx = D.documentElement.clientWidth / 2;
        var t = D.querySelector('h3.app-title');
        if (t) {
            var r = t.getBoundingClientRect(), dx = parseFloat(t.style.getPropertyValue('--title-dx')) || 0;
            var nd = dx + cx - (r.left + r.right) / 2;
            if (r.width && Math.abs(nd - dx) > 0.25) t.style.setProperty('--title-dx', nd.toFixed(2) + 'px');
        }
        var p = D.querySelector('.st-key-top_add_full .st-key-top_add_spec_btn button p');
        var wrap = p && p.closest('[data-testid="stButton"]');
        if (wrap) {
            var q = p.getBoundingClientRect(), m = /translateX\(([-\d.]+)px\)/.exec(wrap.style.transform), bx = m ? parseFloat(m[1]) : 0;
            var nb = bx + cx - (q.left + q.right) / 2;
            if (q.width && Math.abs(nb - bx) > 0.25) wrap.style.transform = 'translateX(' + nb.toFixed(2) + 'px)';
        }
    }
    on(W, 'resize', centreFix);
    var zoomGuardTimer = setInterval(function () {
        var fr = D.querySelectorAll('iframe');
        for (var k = 0; k < fr.length; k++) { try { guardZoom(fr[k].contentDocument); } catch (err) {} }
        centreFix();
    }, 500);
    cleanups.push(function () { clearInterval(zoomGuardTimer); });
    // a faded entry can be hovered (its explanation appears) but not chosen: every press on it is swallowed
    ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'].forEach(function (ev) {
        on(D, ev, function (e) {
            var o = e.target && e.target.closest ? e.target.closest('[role="option"][aria-disabled="true"]') : null;
            if (o) { e.preventDefault(); e.stopImmediatePropagation(); }
        }, true);
    });
    var fadeTimer = setInterval(fadeUnavailableOptions, 100);
    cleanups.push(function () { clearInterval(fadeTimer); });
    on(D, 'wheel', function (e) {
        var t = e.target;
        if (t && t.closest && t.closest('[data-testid="stSlider"], [data-baseweb="select"]')) startAction();
    }, true);
    function pendingLoads() {
        var i, imgs = D.images;
        for (i = 0; i < imgs.length; i++) { if (imgs[i].src && !imgs[i].complete) return true; }
        var frames = D.querySelectorAll('iframe');
        for (i = 0; i < frames.length; i++) {
            try { var fd = frames[i].contentDocument; if (fd && fd.readyState !== 'complete') return true; } catch (err) {}
        }
        return false;
    }
    function waitTick() {
        var now = Date.now();
        var app = D.querySelector('[data-testid="stApp"]');
        var running = !!app && app.getAttribute('data-test-script-state') === 'running';
        var loadingTab = !!D.querySelector('.sim-loading-marker');
        if (running) { if (!runSince) runSince = now; } else { runSince = 0; }
        if (actAt) {
            if (running) { actSawRun = true; actRunEnd = now; }
            var cur = markSeq('.run-marker.full-marker') + '/' + markSeq('.dlg-marker');
            var changed = cur !== (actFull0 + '/' + actDlg0);
            if (cur !== actCur) { actCur = cur; actLastMark = now; }
            var done = false;
            if (now - actAt > 60000) done = true;
            else if (loadingTab) {
                // the 0.5 s loading poll keeps the script state flickering: only the server's markers count
                if (changed && now - actLastMark > 600 && !pendingLoads()) done = true;
                else if (!changed && now - actAt > 10000) done = true;
            } else if (!running && !pendingLoads()) {
                if ((actSawRun || changed) && now - Math.max(actRunEnd, actLastMark) > 700) done = true;
                else if (!actSawRun && !changed && now - actAt > 1500) done = true;   // nothing was rerun
            }
            if (done) actAt = 0;
        }
        var on = !!actAt || (running && !loadingTab && now - runSince > 250);
        D.body.classList.toggle('hdr-wait', on);
    }
    function ghostTick() {
        waitTick();
        var dlg = realDialog();
        if (dlg) {
            if (ghost) { ghost.remove(); ghost = null; }
        } else if (snap && !ghost && D.body.classList.contains('hdr-busy')) {
            ghost = snap;
            ghost.classList.add('dlg-ghost');
            D.body.appendChild(ghost);
        }
        if (!D.body.classList.contains('hdr-busy')) return;
        var app = D.querySelector('[data-testid="stApp"]');
        var running = app && app.getAttribute('data-test-script-state') === 'running';
        if (running || Date.now() - busyStart < 700) { idleSince = 0; return; }
        if (!idleSince) idleSince = Date.now();
        if (Date.now() - idleSince > 500) {          // the rerun is over
            D.body.classList.remove('hdr-busy');
            if (ghost) { ghost.remove(); ghost = null; }
            snap = null;
        }
    }
    var ghostObserver = new MutationObserver(ghostTick);
    ghostObserver.observe(D.body, { childList: true });
    var ghostTimer = setInterval(ghostTick, 100);
    cleanups.push(function () {
        ghostObserver.disconnect(); clearInterval(ghostTimer);
        if (ghost) { ghost.remove(); ghost = null; }
        D.body.classList.remove('hdr-busy'); D.body.classList.remove('hdr-wait');
    });

    // ------------------------------------------------------------------ Play buttons stay clickable while other spectra load
    // The card list re-renders every 0.5 s while something loads; if that replaces the button between
    // mouse-down and mouse-up the browser drops the click. Here the click is replayed on the fresh button.
    var PLAY_SEL = '[class*="st-key-card_anim_"]';
    var playDown = null, playClicked = false;
    function playKeyOf(el) {
        var box = el && el.closest ? el.closest(PLAY_SEL) : null;
        var m = box ? /st-key-card_anim_([A-Za-z0-9-]+)/.exec(String(box.className)) : null;
        return m ? m[1] : null;
    }
    on(D, 'pointerdown', function (e) {
        if (e.button) return;
        playDown = playKeyOf(e.target); playClicked = false;
    }, true);
    on(D, 'click', function (e) { if (playKeyOf(e.target)) playClicked = true; }, true);
    on(D, 'pointerup', function (e) {
        if (e.button || !playDown) return;
        var key = playDown; playDown = null;
        if (playKeyOf(e.target) !== key) return;
        setTimeout(function () {
            if (playClicked) return;
            var box = D.querySelector('.st-key-card_anim_' + key + ' button');
            if (box) box.click();
        }, 60);
    }, true);

    // ------------------------------------------------------------------ sublevel names: the "/" of j = 9/2 is a subscript like its digits
    var SUBFRAC = /([₀-₉]+)\/([₀-₉]+)/g;
    var SUBFRAC_TEST = /[₀-₉]\/[₀-₉]/;
    function subFracHtml(txt) {
        return txt.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(SUBFRAC, function (m, a, b) {
            return a + '<span data-fr="1" style="display:inline-block;font-size:.7em;line-height:1;vertical-align:-.32em;margin:0 .03em;">/</span>' + b;
        });
    }
    var fracOverlays = [];
    function fixSubSlash() {
        try {
            // entries of an open menu
            var opts = D.querySelectorAll('[role="listbox"] [role="option"]');
            for (var i = 0; i < opts.length; i++) {
                var o = opts[i], t = o.textContent;
                if (!SUBFRAC_TEST.test(t) || o.querySelector('[data-fr]')) continue;
                var leaf = o;
                while (leaf.firstElementChild && leaf.firstElementChild.textContent === leaf.textContent) leaf = leaf.firstElementChild;
                leaf.innerHTML = subFracHtml(leaf.textContent);
            }
            // the chosen value of the select boxes of the create window: a matching overlay replaces the (unstyleable) input text
            var inputs = D.querySelectorAll('[data-testid="stDialog"] [data-testid="stSelectbox"] input');
            var used = 0;
            for (var j = 0; j < inputs.length; j++) {
                var inp = inputs[j];
                if (SUBFRAC_TEST.test(inp.value)) {
                    var ov = fracOverlays[used];
                    if (!ov) {
                        ov = D.createElement('div');
                        ov.style.cssText = 'position:fixed;z-index:2147483001;pointer-events:none;display:flex;align-items:center;justify-content:center;padding-left:30px;box-sizing:border-box;white-space:nowrap;';
                        D.body.appendChild(ov);
                        fracOverlays[used] = ov;
                    }
                    var r = inp.getBoundingClientRect(), cs = W.getComputedStyle(inp);
                    ov.style.left = r.left + 'px'; ov.style.top = r.top + 'px'; ov.style.width = r.width + 'px'; ov.style.height = r.height + 'px';
                    ov.style.font = cs.font; ov.style.fontSize = cs.fontSize; ov.style.fontFamily = cs.fontFamily;
                    ov.style.color = '#0f172a'; ov.style.display = 'flex';
                    var html = '<span>' + subFracHtml(inp.value) + '</span>';
                    if (ov.__html !== html) { ov.innerHTML = html; ov.__html = html; }
                    inp.style.color = 'transparent'; inp.setAttribute('data-fracdone', '1');
                    used++;
                } else if (inp.getAttribute('data-fracdone')) {
                    inp.style.color = ''; inp.removeAttribute('data-fracdone');
                }
            }
            for (var k = used; k < fracOverlays.length; k++) fracOverlays[k].style.display = 'none';
        } catch (err) {}
    }
    var fracTimer = setInterval(fixSubSlash, 120);
    cleanups.push(function () { clearInterval(fracTimer); fracOverlays.forEach(function (o) { if (o.parentNode) o.parentNode.removeChild(o); }); fracOverlays = []; });

    // ------------------------------------------------------------------ short label on every entry of the distribution menu
    var DIST_TIPS = __DIST_TIPS__;   // {name of the distribution in the current language: its short description}
    // the same for the nuclear-model menu, and for the chosen model when the menu is closed
    var NUC_TIPS = { 'POINT': 'point charge', 'SPHERE': 'finite size, uniformly charged spherical nucleus', 'FERMI2': 'Fermi 2-term charge distribution' };
    var distTip = null, tipTimer = 0, tipPending = null;
    var TIP_DELAY_OFF = 500;      // the explanation of a faded (unavailable) entry appears after half a second of hovering
    function hideDistTip() {
        if (tipTimer) { clearTimeout(tipTimer); tipTimer = 0; }
        tipPending = null;
        if (distTip && distTip.parentNode) distTip.parentNode.removeChild(distTip);
        distTip = null;
    }
    // -> { el, text, below, delay } for the element the pointer is on, or null
    function tipTarget(e) {
        var t = e.target && e.target.closest ? e.target : null;
        if (!t) return null;
        var opt = t.closest('[role="option"]');
        if (opt) {
            var raw = String(opt.textContent), off = /​​\s*$/.test(raw);   // off = faded (cannot be chosen)
            var key = raw.replace(/​/g, '').trim();
            var mi = D.querySelector('.st-key-dlg_model_group input'), cur = mi ? String(mi.value).replace(/​/g, '').trim() : '';
            if (NUC_TIPS[key]) {   // nuclear-model menu: a usable entry shows what the model is, a faded one only why it cannot be chosen
                return off ? { el: opt, text: key === 'SPHERE' ? __MODEL_OFF_SPHERE__ : (key === 'POINT' ? __MODEL_OFF_POINT__ : __MODEL_OFF_FERMI__), left: true, delay: TIP_DELAY_OFF }
                           : { el: opt, text: NUC_TIPS[key], left: true, delay: 0 };
            }
            if (DIST_TIPS[key]) return { el: opt, text: DIST_TIPS[key], left: false, delay: 0 };
            if (!off) return null;
            // a faded isotope: the reason depends on the nuclear model that is chosen right now
            return { el: opt, text: cur === 'SPHERE' ? __NEED_SPHERE__ : (cur === 'POINT' ? __NEED_POINT__ : __NEED_FERMI__), left: false, delay: TIP_DELAY_OFF };
        }
        // the closed select box: the chosen value sits in its combobox input (Streamlit's React-Aria select; older
        // versions used BaseWeb, where the value is the text of the box)
        var sel = t.closest('.st-key-dlg_model_group [role="group"], .st-key-dlg_model_group [data-baseweb="select"], ' +
                            '.st-key-dlg_dist_group [role="group"], .st-key-dlg_dist_group [data-baseweb="select"]');
        if (sel) {
            var inp = sel.querySelector('input[role="combobox"], input');
            if (sel.querySelector('[aria-expanded="true"]')) return null;   // menu open: the option labels are used instead
            var val = String((inp && inp.value) || sel.textContent).replace(/​/g, '').trim();
            var mt = NUC_TIPS[val] || DIST_TIPS[val];
            // closed box: centred under the box
            return mt ? { el: sel, text: mt, below: true, delay: 0 } : null;
        }
        return null;
    }
    function showTip(tg) {
        tipTimer = 0;
        distTip = D.createElement('div');
        distTip.textContent = tg.text;
        // white label, like the help texts of the three corrections
        distTip.style.cssText = 'position:fixed;z-index:2147483002;background:#ffffff;color:#0f172a;font:500 13px Calibri,Segoe UI,sans-serif;' +
            'padding:6px 12px;border-radius:8px;border:1px solid #cbd5e1;box-shadow:0 4px 14px rgba(15,23,42,.18);' +
            'max-width:340px;white-space:pre-line;pointer-events:none;unicode-bidi:plaintext;';
        D.body.appendChild(distTip);
        // closed select box: centred UNDER the box; menu entries: nuclear-model labels to the LEFT, the others to the right
        var r = tg.el.getBoundingClientRect(), w = distTip.offsetWidth, vw = W.innerWidth;
        var left = tg.below ? r.left + r.width / 2 - w / 2 : (tg.left ? r.left - 8 - w : r.right + 8);
        if (left + w > vw - 6) left = vw - 6 - w;
        left = Math.max(6, left);
        distTip.style.left = left + 'px';
        distTip.style.top = (tg.below ? r.bottom + 6 : r.top + r.height / 2 - distTip.offsetHeight / 2) + 'px';
    }
    on(D, 'mouseover', function (e) {
        var tg = tipTarget(e);
        if (tg && tg.el === tipPending) return;          // still on the same entry: keep the running timer / the shown label
        hideDistTip();
        if (!tg) return;
        if (tg.delay) { tipPending = tg.el; tipTimer = setTimeout(function () { showTip(tg); }, tg.delay); }
        else { tipPending = tg.el; showTip(tg); }
    }, true);
    on(D, 'mouseout', function (e) {
        var tg = tipTarget(e);
        if (tg && (!e.relatedTarget || !tg.el.contains(e.relatedTarget))) hideDistTip();
    }, true);
    on(D, 'pointerdown', hideDistTip, true);
    on(D, 'keydown', hideDistTip, true);

    // ------------------------------------------------------------------ no native hover tooltips on Streamlit buttons
    on(D, 'mouseover', function (e) {
        var t = e.target && e.target.closest ? e.target.closest('[data-testid="stButton"] button') : null;
        if (!t) return;
        var titled = t.querySelectorAll('[title]');
        for (var i = 0; i < titled.length; i++) titled[i].removeAttribute('title');
    }, true);

    // ------------------------------------------------------------------ magnifier +/- : one step on the font-size slider
    on(D, 'click', function (e) {
        var ic = e.target && e.target.closest ? e.target.closest('.st-key-font_size_slider .fs-icon') : null;
        if (!ic) return;
        var box = D.querySelector('.st-key-font_size_slider [data-testid="stSlider"]');
        if (!box) return;
        e.preventDefault();
        // options are listed "largest first": + = one step towards index 0, - = one step away from it
        queueSliderSteps(box, ic.classList.contains('fs-plus') ? -1 : 1);
    }, true);

    // ------------------------------------------------------------------ mouse wheel on every slider
    // Wheel ticks are batched (a few ms) and replayed as arrow keys: one keyup per batch keeps
    // Streamlit's slider from dropping every second tick while it re-renders.
    var sliderQueue = null;
    function sliderThumb(box) {
        return box.querySelector('input[type="range"]') || box.querySelector('[role="slider"]');
    }
    function flushSlider() {
        var q = sliderQueue;
        sliderQueue = null;
        if (!q || !q.count) return;
        var box = q.box;
        if (!box.isConnected) {
            var again = Array.prototype.slice.call(D.querySelectorAll('[data-testid="stSlider"], [data-testid="stSelectSlider"]'))
                .filter(function (b) { var l = b.querySelector('label'); return l && l.innerText === q.label; });
            box = again[0];
        }
        var thumb = box ? sliderThumb(box) : null;
        if (!thumb) return;
        thumb.focus();
        var inc = q.count > 0;
        // Up / Down increase / decrease in every slider implementation and in RTL pages too.
        var key = inc ? 'ArrowUp' : 'ArrowDown';
        var code = inc ? 38 : 40;
        var init = { key: key, code: key, keyCode: code, which: code, bubbles: true, cancelable: true };
        // One step per event turn: the slider derives each step from its current value, so steps must not overlap.
        var remaining = Math.abs(q.count);
        (function step() {
            var th = box.isConnected ? sliderThumb(box) : thumb;
            if (!th) return;
            th.focus();
            th.dispatchEvent(new KeyboardEvent('keydown', init));
            th.dispatchEvent(new KeyboardEvent('keyup', init));
            if (--remaining > 0) setTimeout(step, 90);
        })();
    }
    function queueSliderSteps(box, dir) {
        var label = box.querySelector('label');
        if (sliderQueue && sliderQueue.box !== box) flushSlider();
        if (!sliderQueue) sliderQueue = { box: box, label: label ? label.innerText : '', count: 0, timer: 0, first: Date.now() };
        sliderQueue.count += dir;
        clearTimeout(sliderQueue.timer);
        var wait = (Date.now() - sliderQueue.first > 220) ? 0 : 60;
        sliderQueue.timer = setTimeout(flushSlider, wait);
    }
    on(D, 'wheel', function (e) {
        var t = e.target && e.target.nodeType === 1 ? e.target : (e.target ? e.target.parentElement : null);
        if (!t || !t.closest) return;
        var box = t.closest('[data-testid="stSlider"], [data-testid="stSelectSlider"]');
        if (box) {
            var thumb = box.querySelector('input[type="range"]') || box.querySelector('[role="slider"]');
            if (!thumb) return;
            e.preventDefault();
            e.stopPropagation();
            // These two sliders list their options "largest first" (right end = larger): wheel up must grow.
            var flip = box.closest('.st-key-font_size_slider, .st-key-col_width_wedge') ? -1 : 1;
            queueSliderSteps(box, (e.deltaY < 0 ? 1 : -1) * flip);
            return;
        }
        var range = t.closest('input[type="range"]');
        if (range && !range.closest('[data-testid="stSlider"], [data-testid="stSelectSlider"]')) {
            e.preventDefault();
            e.stopPropagation();
            if (e.deltaY < 0) range.stepUp(); else range.stepDown();
            range.dispatchEvent(new Event('input', { bubbles: true }));
            range.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }, { passive: false, capture: true });

    // ------------------------------------------------------------------ mouse wheel on selectboxes (closed or open)
    var selBusy = 0;
    function pressKey(el, key, code) {
        var init = { key: key, code: key, keyCode: code, which: code, bubbles: true, cancelable: true };
        el.dispatchEvent(new KeyboardEvent('keydown', init));
        el.dispatchEvent(new KeyboardEvent('keyup', init));
    }
    on(D, 'wheel', function (e) {
        var t = e.target && e.target.nodeType === 1 ? e.target : (e.target ? e.target.parentElement : null);
        if (!t || !t.closest) return;
        var list = t.closest('[role="listbox"]');
        var box = t.closest('[data-testid="stSelectbox"]');
        if (!list && !(box && box.querySelector('input[aria-label="n"]'))) return;
        if (!list) {
            e.preventDefault();
            e.stopPropagation();
        }
        var now = Date.now();
        if (!list && now - selBusy < 90) return;
        selBusy = now;
        var inc = e.deltaY < 0;
        if (list) {
            // Open menu: scroll it manually (Streamlit's modal scroll-lock swallows the native wheel scroll).
            var node = t, target = null, hops = 0;
            while (node && node !== D.body && hops < 8) {
                var oy = W.getComputedStyle(node).overflowY;
                if ((oy === 'auto' || oy === 'scroll') && node.scrollHeight > node.clientHeight + 1) { target = node; break; }
                node = node.parentElement; hops++;
            }
            if (!target) {
                var cand = list.parentElement;
                if (cand && cand.scrollHeight > cand.clientHeight + 1) target = cand;
                else if (list.scrollHeight > list.clientHeight + 1) target = list;
            }
            if (target) {
                e.preventDefault();
                e.stopPropagation();
                target.scrollTop += e.deltaY;
            }
            return;
        }
        // closed 'n' selector: step through the Python-side bridge (deterministic, no popup needed)
        var input = box.querySelector('input');
        if (input && input.getAttribute('aria-label') === 'n') {
            commitBridge('.st-key-_n_bridge input', Date.now() + ':' + (inc ? 1 : -1));
        }
    }, { passive: false, capture: true });

    // ------------------------------------------------------------------ help window: the "?" button right of the language switch
    // A layer under the header band with a fixed title band (two wide tabs + the X on the right, like the other windows of
    // the site) and a scrolling body. Tab "info" (right) shows the pages of the project report (images, window.__muonReportPages);
    // tab "guide" (left) shows the site map (HTML in the chosen language, window.__muonHelp). The last tab shown is
    // remembered; the first time, "info" opens.
    var helpEl = D.getElementById('muon-help');        // a window that is open while this script is re-installed (language switch) stays open
    var helpTab = W.__muonHelpTab;
    if (!helpTab) { try { helpTab = W.localStorage.getItem('muonHelpTab'); } catch (err) {} }
    if (helpTab !== 'guide') helpTab = 'info';
    function reportHtml() {
        var pg = W.__muonReportPages;
        if (!pg || !pg.length) return null;
        var s = '';
        for (var i = 0; i < pg.length; i++)
            s += '<img class="mh-page" alt="" width="' + pg[i][0] + '" height="' + pg[i][1] + '" src="data:image/webp;base64,' + pg[i][2] + '">';
        return s;
    }    function helpClose() { if (helpEl) { if (helpEl.parentNode) helpEl.parentNode.removeChild(helpEl); helpEl = null; } }
    function helpOpen(tab) {
        var h = W.__muonHelp;
        if (!h) return;
        if (tab) {
            helpTab = tab; W.__muonHelpTab = tab;
            try { W.localStorage.setItem('muonHelpTab', tab); } catch (err) {}
        }
        var keep = (helpEl && helpEl.getAttribute('data-tab') === helpTab && helpEl.querySelector('.mh-scroll')) ?
            helpEl.querySelector('.mh-scroll').scrollTop : 0;
        helpClose();
        if (!D.getElementById('muon-help-style')) {
            var stl = D.createElement('style');
            stl.id = 'muon-help-style';
            stl.textContent =
                '#muon-help{position:fixed;left:0;right:0;bottom:0;top:var(--hdr-h,54px);z-index:1999990;background:rgba(15,23,42,.38)}' +
                '#muon-help .mh-wrap{position:absolute;left:18px;right:18px;top:12px;bottom:12px;background:#fff;border:2px solid #334155;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.28);overflow:hidden;display:flex;flex-direction:column}' +
                '#muon-help .mh-head{direction:ltr;flex:0 0 auto;display:flex;align-items:center;gap:14px;background:#e2e8f0;border-bottom:1.5px solid #94a3b8;padding:8px 16px}' +
                '#muon-help .mh-sp{flex:0 0 30px}#muon-help .mh-title{flex:1 1 auto;text-align:center;font:700 16px Rubik,"Segoe UI",Arial,sans-serif;color:#0f172a}' +
                '#muon-help .mh-tabs{flex:1 1 auto;display:flex;gap:12px;min-width:0}' +
                '#muon-help .mh-tab{flex:1 1 0;text-align:center;padding:6px 10px;border-radius:8px;border:1.5px solid #64748b;background:#fff;color:#0f172a;font:700 16px Rubik,"Segoe UI",Arial,sans-serif;cursor:pointer;opacity:.42;transition:opacity .15s,box-shadow .15s,background .15s;user-select:none}' +
                '#muon-help .mh-tab:hover,#muon-help .mh-tab:focus-visible{opacity:.85;background:#f8fafc;box-shadow:0 2px 6px rgba(15,23,42,.18);outline:none}' +
                '#muon-help .mh-tab.on{opacity:1;box-shadow:0 1px 4px rgba(15,23,42,.18);cursor:default}' +
                '#muon-help .mh-body{position:relative;flex:1 1 auto;min-height:0}' +
                '#muon-help .mh-scroll{position:absolute;left:0;right:0;top:0;bottom:0;overflow-y:auto;padding:22px clamp(18px,4vw,60px) 36px;box-sizing:border-box}' +
                '#muon-help .mh-scroll>.mh{max-width:1260px;margin:0 auto}' +
                '#muon-help .mh-info{max-width:900px!important;font:16px/1.7 Rubik,"Segoe UI",Arial,sans-serif;color:#0f172a}#muon-help .mh-info h2{font-size:22px;color:#0f4c81;margin:6px 0 14px}#muon-help .mh-info p{margin:0 0 12px}#muon-help .mh-info .ref{margin-top:22px;padding:10px 14px;background:#f1f5f9;border-inline-start:4px solid #0f4c81;border-radius:6px;font-size:14.5px}#muon-help .mh-info a{color:#0f4c81;word-break:break-all}' +
                '#muon-help .mh-report{background:#e2e8f0}#muon-help .mh-page{display:block;width:100%;max-width:980px;height:auto;margin:0 auto 16px auto;background:#fff;box-shadow:0 2px 10px rgba(15,23,42,.25)}' +
                '#muon-help .mh-none{padding:30px;text-align:center;color:#475569;font:600 16px Rubik,"Segoe UI",Arial,sans-serif}' +
                '#muon-help .mh-x{flex:0 0 30px;position:relative;width:30px;height:30px;border-radius:50%;background:#fff;border:1.8px solid #475569;cursor:pointer;box-sizing:border-box}' +
                '#muon-help .mh-x:before,#muon-help .mh-x:after{content:"";position:absolute;left:50%;top:50%;width:25px;height:2px;margin:-1px 0 0 -12.5px;background:#1e293b}' +
                '#muon-help .mh-x:before{transform:rotate(45deg)}#muon-help .mh-x:after{transform:rotate(-45deg)}' +
                '#muon-help .mh-x:hover{background:#c1121f;border-color:#991b1b}#muon-help .mh-x:hover:before,#muon-help .mh-x:hover:after{background:#fff}';
            D.head.appendChild(stl);
        }
        var body;
        if (helpTab === 'info') {
            var rep = reportHtml();
            body = rep ? '<div class="mh-scroll mh-report">' + rep + '</div>' : h.info_html ?
                '<div class="mh-scroll"><div class="mh mh-info" dir="' + h.dir + '">' + h.info_html + '</div></div>' :
                '<div class="mh-none" dir="' + h.dir + '">' + h.no_report + '</div>';
        } else {
            body = '<div class="mh-scroll">' + h.html + '</div>';
        }
        helpEl = D.createElement('div');
        helpEl.id = 'muon-help';
        helpEl.setAttribute('data-lang', h.lang);
        helpEl.setAttribute('data-tab', helpTab);
        helpEl.innerHTML = '<div class="mh-wrap"><div class="mh-head"><div class="mh-sp"></div>' +
            '<div class="mh-title" dir="' + h.dir + '">' + (helpTab === 'info' ? h.tab_info : h.tab_guide) + '</div>' +
            '<div class="mh-x" tabindex="0" aria-label="' + h.close + '" title="' + h.close + '"></div></div>' +
            '<div class="mh-body">' + body + '</div></div>';
        D.body.appendChild(helpEl);
        var sc = helpEl.querySelector('.mh-scroll');
        if (sc) sc.scrollTop = keep;
    }
    // "?" opens the site guide, "i" the about-the-project window; pressing the button of the open window closes it
    function helpToggle(t) {
        if (t.classList.contains('mh-x')) { helpClose(); return; }
        var tab = t.getAttribute('data-tab') || 'guide';
        if (helpEl && helpEl.getAttribute('data-tab') === tab) helpClose(); else helpOpen(tab);
    }
    on(D, 'click', function (e) {
        var t = e.target && e.target.closest ? e.target.closest('.help-q, #muon-help .mh-x') : null;
        if (t) { e.preventDefault(); e.stopPropagation(); helpToggle(t); return; }
        if (helpEl && e.target === helpEl) helpClose();
    }, true);
    on(D, 'keydown', function (e) {
        if (e.key === 'Escape' && helpEl) { helpClose(); return; }
        var t = e.target;
        if ((e.key === 'Enter' || e.key === ' ') && t && t.classList && (t.classList.contains('help-q') || t.classList.contains('mh-x'))) {
            e.preventDefault(); helpToggle(t);
        }
    }, true);    // the language was changed while the window is open: show it in the new language (the server has sent the new text)
    var helpTimer = setInterval(function () {
        if (helpEl && W.__muonHelp && W.__muonHelp.lang !== helpEl.getAttribute('data-lang')) helpOpen();
    }, 400);
    cleanups.push(function () { clearInterval(helpTimer); });
    // ------------------------------------------------------------------ thin scrollbar on the left edge of the spectra list
    // (the list scrolls with the wheel, but without a visible scrollbar: this one shows it and can be clicked / dragged)
    var SB_W = 8, SB_GAP = 6;
    var sbTrack = D.createElement('div');
    sbTrack.id = 'muon-vscroll';
    sbTrack.style.cssText = 'position:fixed;z-index:50;width:' + SB_W + 'px;border-radius:4px;background:#dfe5ee;display:none;cursor:pointer;touch-action:none;';
    var sbThumb = D.createElement('div');
    sbThumb.style.cssText = 'position:absolute;left:0;right:0;border-radius:4px;background:#94a3b8;cursor:grab;touch-action:none;';
    sbTrack.appendChild(sbThumb);
    D.body.appendChild(sbTrack);
    cleanups.push(function () { if (sbTrack.parentNode) sbTrack.parentNode.removeChild(sbTrack); });
    function sbList() { return D.querySelector('.st-key-spectra_cards_scroll'); }
    function sbSync() {
        var s = sbList();
        var r = s ? s.getBoundingClientRect() : null;
        if (!s || r.width <= 0 || r.height <= 0 || s.scrollHeight <= s.clientHeight + 1) { sbTrack.style.display = 'none'; return; }
        sbTrack.style.display = 'block';
        sbTrack.style.left = (r.left - SB_W - SB_GAP) + 'px';
        sbTrack.style.top = Math.round(r.top) + 'px';
        sbTrack.style.height = Math.round(r.height) + 'px';
        var th = Math.max(28, Math.round(r.height * s.clientHeight / s.scrollHeight));
        var span = s.scrollHeight - s.clientHeight;
        sbThumb.style.height = th + 'px';
        sbThumb.style.top = Math.round((r.height - th) * (span > 0 ? s.scrollTop / span : 0)) + 'px';
    }
    var sbDrag = null;
    function sbScrollTo(clientY, grab) {          // puts the thumb centre (or the grabbed point of it) at clientY
        var s = sbList();
        if (!s) return;
        var tr = sbTrack.getBoundingClientRect(), th = sbThumb.offsetHeight;
        var frac = Math.min(1, Math.max(0, (clientY - tr.top - grab) / Math.max(1, tr.height - th)));
        return frac * (s.scrollHeight - s.clientHeight);
    }
    on(sbTrack, 'pointerdown', function (e) {
        var s = sbList();
        if (!s) return;
        e.preventDefault();
        if (e.target === sbThumb) {
            sbDrag = { grab: e.clientY - sbThumb.getBoundingClientRect().top };
            sbThumb.style.cursor = 'grabbing';
            try { sbTrack.setPointerCapture(e.pointerId); } catch (err) {}
        } else {                                      // click on the track: jump there
            s.scrollTo({ top: sbScrollTo(e.clientY, sbThumb.offsetHeight / 2), behavior: 'smooth' });
        }
    });
    on(sbTrack, 'pointermove', function (e) {
        var s = sbList();
        if (sbDrag && s) s.scrollTop = sbScrollTo(e.clientY, sbDrag.grab);
    });
    function sbEnd() { sbDrag = null; sbThumb.style.cursor = 'grab'; }
    on(sbTrack, 'pointerup', sbEnd);
    on(sbTrack, 'pointercancel', sbEnd);
    on(sbTrack, 'mouseenter', function () { sbThumb.style.background = '#64748b'; });
    on(sbTrack, 'mouseleave', function () { sbThumb.style.background = '#94a3b8'; });
    on(D, 'scroll', sbSync, true);
    on(W, 'resize', sbSync);
    sbSync();
    var sbTimer = setInterval(sbSync, 150);
    cleanups.push(function () { clearInterval(sbTimer); });

    W.__muonUI = { destroy: function () { endGesture(); cleanups.forEach(function (fn) { fn(); }); cleanups = []; } };
})();
'''


def embed_html(html, height):
    """Embeds an HTML document in an iframe (st.iframe when available, else the legacy components.html)."""
    if hasattr(st, "iframe"):
        try:
            st.iframe(html, height=max(1, int(height)))
            return
        except Exception:
            pass
    components.html(html, height=height)


def embed_html_zero(html, height=0):
    """Zero-height helper iframe used only to run a script in the parent page."""
    if hasattr(st, "iframe"):
        try:
            st.iframe(html, height=1)
            return
        except Exception:
            pass
    components.html(html, height=0)


PLOT_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
        margin: 0; padding: 0;
        font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
        background: transparent; color: #0f172a;
        user-select: none; overflow: hidden;
    }
    .card {
        position: relative; display: flex; flex-direction: column; height: 100%;
        border: 1.5px solid #64748b; border-radius: 10px; background: #ffffff; overflow: hidden;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
    }
    button {
        font-family: 'Calibri', 'Segoe UI', sans-serif;
        background: #ffffff; color: #1e293b; border: 1px solid #64748b;
        border-radius: 6px; padding: 4px 9px; font-size: calc(13px * var(--fs));
        font-weight: 600; cursor: pointer; transition: all 0.15s;
    }
    button:hover { background: #f1f5f9; }
    .stage { position: relative; flex: 1 1 auto; min-height: 0; }
    canvas { position: absolute; left: 0; top: 0; width: 100%; height: 100%; cursor: grab; touch-action: none; }
    canvas.drag { cursor: grabbing; }
    #tip {
        position: absolute; display: none; pointer-events: none; z-index: 50;
        background: #0f172a; color: #fff; font-size: 12px; line-height: 1.45; padding: 6px 10px;
        border-radius: 6px; border: 1px solid #334155; box-shadow: 0 3px 8px rgba(15,23,42,.35);
        white-space: nowrap;
    }
    #tip b { font-weight: 700; }
</style>
</head>
<body>
<div class="card">
    <div class="stage" id="stage"><canvas id="cv"></canvas><div id="tip"></div></div>
</div>
<script>
(function () {
    var D = __DATA__;
    var UI = __UI__;
    var S = Math.max(0.85, Math.min(1.3, UI.fs || 1));
    document.documentElement.style.setProperty('--fs', S);

    var cv = document.getElementById('cv'), ctx = cv.getContext('2d');
    var tip = document.getElementById('tip'), stage = document.getElementById('stage');
    // full screen: the whole right-hand column (settings row + plot) goes full screen, so every setting stays usable
    function fsTarget() { try { return window.frameElement.closest('[data-testid="stColumn"]'); } catch (err) { return null; } }
    function fsOn() {
        var t = fsTarget();
        try { return !!t && (window.parent.document.fullscreenElement === t || t.getAttribute('data-pfs') === '1'); } catch (err) { return false; }
    }
    function syncFs() {
        var t = fsTarget();
        if (t) { if (fsOn()) t.setAttribute('data-plotfs', '1'); else t.removeAttribute('data-plotfs'); }
        setTimeout(resize, 60);
    }
    // browsers that refuse real full screen get a full-window column instead
    function setPseudo(on) {
        var t = fsTarget();
        if (!t) return;
        if (on) {
            t.setAttribute('data-pfs', '1'); t.setAttribute('data-oldstyle', t.getAttribute('style') || '');
            ['position:fixed', 'left:0', 'top:0', 'width:100vw', 'height:100vh', 'max-width:none', 'z-index:2147483000', 'margin:0', 'flex:none'].forEach(function (d) {
                var kv = d.split(':'); t.style.setProperty(kv[0], kv[1], 'important');
            });
        } else {
            t.removeAttribute('data-pfs'); t.setAttribute('style', t.getAttribute('data-oldstyle') || '');
        }
        syncFs();
    }
    function toggleFs() {
        var t = fsTarget();
        if (!t) return;
        var pd = window.parent.document;
        if (pd.fullscreenElement === t) { pd.exitFullscreen(); return; }
        if (t.getAttribute('data-pfs') === '1') { setPseudo(false); return; }
        var pr = null;
        try { pr = t.requestFullscreen ? t.requestFullscreen() : null; } catch (err) { pr = null; }
        if (pr && pr.catch) pr.catch(function () { setPseudo(true); }); else if (!pr) setPseudo(true);
    }
    function escPseudo(e) { var t = fsTarget(); if (e.key === 'Escape' && t && t.getAttribute('data-pfs') === '1') setPseudo(false); }
    try { window.parent.document.addEventListener('fullscreenchange', syncFs); } catch (err) {}
    document.addEventListener('keydown', escPseudo);
    try { window.parent.document.addEventListener('keydown', escPseudo); } catch (err) {}
    var FONT = "'Calibri','Segoe UI',Arial,sans-serif";
    var W = 0, H = 0, dpr = 1;
    var M = { l: 74 * S, r: 16, t: 40 * S, b: 48 * S };
    var NB = { 1: 380, 2: 240, 3: 140, 4: 75 }[D.stage] || 240;
    var RW = { 1: 0.72, 2: 0.84, 3: 0.92, 4: 0.98 }[D.stage] || 0.84;
    var LOG = !!D.log, NORM = !!D.norm;
    var sp = D.spectra;
    var xmax = 0;
    sp.forEach(function (s) { if (s.e.length) xmax = Math.max(xmax, s.e[s.e.length - 1]); });
    var X_FULL = [0, xmax * 1.05];
    var xv = X_FULL.slice();
    var panels = [];
    if (D.stacked && sp.length > 1) sp.forEach(function (s, i) { panels.push({ idx: [i] }); });
    else panels.push({ idx: sp.map(function (s, i) { return i; }) });
    var bars = [];          // drawn bars, for hover hit-testing
    var hover = null, raf = 0;

    // ---------------------------------------------------------------- helpers
    function lowerBound(a, v) { var lo = 0, hi = a.length; while (lo < hi) { var m = (lo + hi) >> 1; if (a[m] < v) lo = m + 1; else hi = m; } return lo; }
    function agg(s, binW, xa, xb) {
        var e = s.e, c = s.c, lo = lowerBound(e, xa - binW), hi = lowerBound(e, xb + binW);
        var m = new Map(), k, sc = NORM ? 100 / s.total : 1;
        for (var i = lo; i < hi; i++) { k = Math.floor(e[i] / binW); m.set(k, (m.get(k) || 0) + c[i] * sc); }
        return m;
    }
    function ty(v) { return LOG ? Math.log10(Math.max(v, 1e-12)) : v; }
    function niceStep(range, target) {
        var raw = range / target, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
        return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
    }
    function decimals(step) { return Math.max(0, -Math.floor(Math.log10(step) + 1e-9)); }
    function group(n) { return n.toLocaleString('en-US'); }
    function fmtY(v) {
        var t;
        if (NORM) { if (v > 100.0001) return ''; t = (v >= 1 && Math.abs(v - Math.round(v)) < 1e-6) ? String(Math.round(v)) : String(+v.toPrecision(3)); return t + '%'; }
        if (v >= 1 && Math.abs(v - Math.round(v)) < 1e-6) return group(Math.round(v));
        return String(+v.toPrecision(2));
    }
    function plotW() { return Math.max(50, W - M.l - M.r); }
    function mapX(x) { return M.l + (x - xv[0]) / (xv[1] - xv[0]) * plotW(); }
    function unX(px) { return xv[0] + (px - M.l) / plotW() * (xv[1] - xv[0]); }
    function mapY(p, t) { return p.top + p.h * (1 - (t - p.y[0]) / (p.y[1] - p.y[0])); }
    function unY(p, py) { return p.y[0] + (1 - (py - p.top) / p.h) * (p.y[1] - p.y[0]); }

    // default y-range of a panel (the same rules as the former static plot)
    function defaultY(p) {
        var binW = (X_FULL[1] - X_FULL[0]) / NB, maxC = 0;
        p.idx.forEach(function (i) { agg(sp[i], binW, X_FULL[0], X_FULL[1]).forEach(function (v) { if (v > maxC) maxC = v; }); });
        if (maxC <= 0) maxC = 1;
        if (LOG) {
            var bottom = NORM ? 0.05 : 0.5;
            var top = NORM ? Math.min(100, Math.max(maxC * 1.8, 10)) : Math.max(maxC * 2.5, bottom * 15);
            return [Math.log10(bottom), Math.log10(top)];
        }
        return [0, NORM ? Math.min(100, Math.max(maxC * 1.12, 1)) : Math.max(maxC * 1.15, 1)];
    }
    panels.forEach(function (p) { p.y0 = defaultY(p); p.y = p.y0.slice(); });

    // keep the x-view across the reload that a change of the Streamlit options causes
    try {
        var P = window.parent;
        if (P.__specView && P.__specView.sig === D.sig) {
            xv = P.__specView.x.slice();
            if (P.__specView.opt === (((D.log ? 1 : 0) + '|' + (D.norm ? 1 : 0) + '|' + (D.stacked ? 1 : 0))) && P.__specView.y && P.__specView.y.length === panels.length) {
                panels.forEach(function (p, i) { p.y = P.__specView.y[i].slice(); });
            }
        }
    } catch (err) {}
    var OPT = (D.log ? 1 : 0) + '|' + (D.norm ? 1 : 0) + '|' + (D.stacked ? 1 : 0);
    function saveView() { try { window.parent.__specView = { sig: D.sig, opt: OPT, x: xv.slice(), y: panels.map(function (p) { return p.y.slice(); }) }; } catch (err) {} }

    function layout() {
        var n = panels.length, top = M.t, bottom = H - M.b, gap = n > 1 ? 12 * S : 0;
        var ph = (bottom - top - gap * (n - 1)) / n;
        panels.forEach(function (p, i) { p.top = top + i * (ph + gap); p.h = Math.max(20, ph); });
    }
    function resize() {
        var r = stage.getBoundingClientRect();
        W = Math.max(200, Math.floor(r.width)); H = Math.max(160, Math.floor(r.height));
        dpr = window.devicePixelRatio || 1;
        cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
        layout(); draw();
    }

    // ---------------------------------------------------------------- drawing
    function draw() {
        raf = 0;
        saveView();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
        bars = [];
        var pw = plotW(), binW = (xv[1] - xv[0]) * (pw / NB) / pw;   // = range / NB: fixed pixel width of a bin
        var n = panels.length;

        // title
        ctx.fillStyle = '#111827'; ctx.font = 'bold ' + (15 * S) + 'px ' + FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
        ctx.fillText(D.title, M.l + pw / 2, M.t - 14 * S);

        // vertical grid + x ticks
        var xs = niceStep(xv[1] - xv[0], Math.max(4, pw / 95)), xd = decimals(xs), xt = [];
        for (var x = Math.ceil(xv[0] / xs - 1e-9) * xs; x <= xv[1] + 1e-9; x += xs) xt.push(x);

        panels.forEach(function (p, pi) {
            ctx.save();
            ctx.beginPath(); ctx.rect(M.l, p.top, pw, p.h); ctx.clip();
            // grid
            ctx.strokeStyle = 'rgba(100,116,139,0.28)'; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
            xt.forEach(function (x) { var px = Math.round(mapX(x)) + 0.5; ctx.beginPath(); ctx.moveTo(px, p.top); ctx.lineTo(px, p.top + p.h); ctx.stroke(); });
            var yt = yTicks(p);
            yt.forEach(function (t) { var py = Math.round(mapY(p, t.t)) + 0.5; ctx.beginPath(); ctx.moveTo(M.l, py); ctx.lineTo(M.l + pw, py); ctx.stroke(); });
            ctx.setLineDash([]);
            // bars
            var base = mapY(p, LOG ? p.y[0] : Math.max(0, p.y[0]));
            var ng = p.idx.length;
            p.idx.forEach(function (i, jj) {
                var s = sp[i], m = agg(s, binW, xv[0], xv[1]);
                var col = s.color;
                m.forEach(function (v, k) {
                    if (v <= 0) return;
                    var t = ty(v); if (t <= p.y[0]) return;
                    var ytop = mapY(p, t);
                    var bx0 = mapX(k * binW), bx1 = mapX((k + 1) * binW), bw = bx1 - bx0;
                    var gw = bw * RW, sub = gw / ng, x0 = bx0 + (bw - gw) / 2 + jj * sub;
                    var w = Math.max(1, sub), h = Math.max(1, base - ytop);
                    if (x0 + w < M.l || x0 > M.l + pw) return;
                    ctx.globalAlpha = ng > 1 ? 0.95 : 0.84; ctx.fillStyle = col; ctx.fillRect(x0, base - h, w, h);
                    ctx.globalAlpha = 1;
                    bars.push({ x: x0, y: base - h, w: w, h: h, pi: pi, i: i, k: k, v: v, bx0: bx0, bw: bw, base: base });
                });
            });
            // hovered bar
            if (hover && hover.pi === pi) {
                ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 1.5;
                ctx.strokeRect(hover.x - 0.5, hover.y - 0.5, hover.w + 1, hover.h + 1);
            }
            ctx.restore();

            // frame
            ctx.strokeStyle = '#334155'; ctx.lineWidth = 1; ctx.strokeRect(M.l + 0.5, p.top + 0.5, pw, p.h);
            // y tick labels
            ctx.fillStyle = '#1e293b'; ctx.font = (12.5 * S) + 'px ' + FONT; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
            var lastPy = 1e9;
            yt.slice().sort(function (u, w) { return w.t - u.t; }).forEach(function (t) {
                var py = mapY(p, t.t); if (py < p.top - 1 || py > p.top + p.h + 1) return;
                if (!t.lab || Math.abs(py - lastPy) < 13 * S) return;
                lastPy = py;
                ctx.beginPath(); ctx.strokeStyle = '#334155'; ctx.moveTo(M.l - 4, Math.round(py) + 0.5); ctx.lineTo(M.l, Math.round(py) + 0.5); ctx.stroke();
                ctx.fillText(t.lab, M.l - 8, py);
            });
            // y label
            ctx.save(); ctx.translate(16 * S, p.top + p.h / 2); ctx.rotate(-Math.PI / 2);
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = (13 * S) + 'px ' + FONT;
            ctx.fillText(n > 1 ? (NORM ? 'Rel. [%]' : 'Counts') : (NORM ? 'Relative Intensity' : 'Counts (Intensity)'), 0, 0);
            ctx.restore();
            // legend: only when several spectra are shown (a single one is already described by the title)
            if (sp.length > 1) drawLegend(p);
        });

        // x tick labels + label (bottom panel)
        var last = panels[n - 1], by = last.top + last.h;
        ctx.fillStyle = '#1e293b'; ctx.font = (12.5 * S) + 'px ' + FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        xt.forEach(function (x) {
            var px = mapX(x); if (px < M.l - 1 || px > M.l + pw + 1) return;
            ctx.strokeStyle = '#334155'; ctx.beginPath(); ctx.moveTo(Math.round(px) + 0.5, by); ctx.lineTo(Math.round(px) + 0.5, by + 4); ctx.stroke();
            ctx.fillText(xd ? x.toFixed(xd) : String(Math.round(x)), px, by + 7);
        });
        ctx.font = (13.5 * S) + 'px ' + FONT; ctx.textBaseline = 'alphabetic';
        ctx.fillText('Photon Energy ΔE [keV]', M.l + pw / 2, H - 8 * S);
    }

    function yLabel(v, d) {
        if (d === undefined) return fmtY(v);
        if (NORM && v > 100.0001) return '';
        var t = d === 0 ? group(Math.round(v)) : v.toFixed(d);
        return NORM ? t + '%' : t;
    }
    function linTicks(lo, hi, p) {
        var out = [], st = niceStep(hi - lo, Math.max(3, p.h / 45)), d = decimals(st);
        for (var v = Math.ceil(lo / st - 1e-9) * st; v <= hi + 1e-9; v += st) {
            var vv = +v.toFixed(d + 2);
            out.push({ t: LOG ? Math.log10(Math.max(vv, 1e-12)) : vv, v: vv, lab: yLabel(vv, d) });
        }
        return out;
    }
    function yTicks(p) {
        var out = [], a = p.y[0], b = p.y[1], i, k;
        if (!LOG) return linTicks(a, b, p);
        var span = b - a;
        if (span <= 0.6) return linTicks(Math.pow(10, a), Math.pow(10, b), p);   // zoomed in: fine ticks between the decades
        if (span > 8) { var stp = Math.ceil(span / 6); for (k = Math.ceil(a); k <= b; k += stp) out.push({ t: k, v: Math.pow(10, k), lab: yLabel(Math.pow(10, k)) }); return out; }
        var mult = span > 3.2 ? [1] : span > 1.4 ? [1, 2, 5] : [1, 2, 3, 4, 5, 6, 7, 8, 9];
        for (k = Math.floor(a) - 1; k <= Math.ceil(b); k++) {
            for (i = 0; i < mult.length; i++) {
                var v2 = mult[i] * Math.pow(10, k), t2 = Math.log10(v2);
                if (t2 >= a - 1e-9 && t2 <= b + 1e-9) out.push({ t: t2, v: v2, lab: yLabel(v2) });
            }
        }
        return out;
    }

    function drawLegend(p) {
        ctx.font = (12.5 * S) + 'px ' + FONT; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        var lh = 19 * S, pad = 8 * S, sw = 12 * S, wmax = 0;
        p.idx.forEach(function (i) { wmax = Math.max(wmax, ctx.measureText(sp[i].label).width); });
        var bw = wmax + sw + pad * 3, bh = lh * p.idx.length + pad, x0 = M.l + plotW() - bw - 8, y0 = p.top + 8;
        ctx.fillStyle = 'rgba(255,255,255,0.85)'; ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x0, y0, bw, bh, 5) : ctx.rect(x0, y0, bw, bh); ctx.fill(); ctx.stroke();
        p.idx.forEach(function (i, j) {
            var cy = y0 + pad / 2 + lh * j + lh / 2;
            ctx.fillStyle = sp[i].color; ctx.fillRect(x0 + pad, cy - sw / 2 + 1, sw, sw - 2);
            ctx.fillStyle = '#111827'; ctx.fillText(sp[i].label, x0 + pad * 2 + sw, cy);
        });
    }

    function redraw() { if (!raf) raf = requestAnimationFrame(draw); }

    // ---------------------------------------------------------------- view changes
    function clampX() {
        var full = X_FULL[1] - X_FULL[0], span = xv[1] - xv[0];
        if (span < 1e-4) { var c = (xv[0] + xv[1]) / 2; xv = [c - 5e-5, c + 5e-5]; }
        if (span > full * 3) { xv = [X_FULL[0] - full, X_FULL[1] + full]; }
    }
    function zoomX(cx, f) { xv = [cx + (xv[0] - cx) / f, cx + (xv[1] - cx) / f]; clampX(); saveView(); }
    function zoomY(p, ct, f) {
        var lo = ct + (p.y[0] - ct) / f, hi = ct + (p.y[1] - ct) / f, minSpan = LOG ? 0.02 : 1e-3;
        if (hi - lo < minSpan) return;
        if (hi - lo > (LOG ? 40 : 1e9)) return;
        p.y = [lo, hi];
    }
    function panelAt(py) {
        for (var i = 0; i < panels.length; i++) { if (py >= panels[i].top - 1 && py <= panels[i].top + panels[i].h + 1) return panels[i]; }
        return null;
    }
    var anim = 0, animTgt = null;
    function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
    // the centre moves linearly, the visible span changes geometrically (feels like a steady zoom)
    function mixRange(a, b, e) {
        var ca = (a[0] + a[1]) / 2, sa = Math.max(a[1] - a[0], 1e-9), cb = (b[0] + b[1]) / 2, sb = Math.max(b[1] - b[0], 1e-9);
        var c = ca + (cb - ca) * e, sp2 = sa * Math.pow(sb / sa, e);
        return [c - sp2 / 2, c + sp2 / 2];
    }
    function animateTo(xT, yT, DUR) {
        var x0 = xv.slice(), y0 = panels.map(function (p) { return p.y.slice(); }), t0 = performance.now();
        if (anim) cancelAnimationFrame(anim);
        animTgt = { x: xT, y: yT };
        function step(now) {
            var k = Math.min(1, (now - t0) / DUR), e = ease(k);
            if (k >= 1) {
                anim = 0; animTgt = null; xv = xT.slice(); panels.forEach(function (p, i) { p.y = yT[i].slice(); }); saveView(); draw(); return;
            }
            xv = mixRange(x0, xT, e);
            panels.forEach(function (p, i) { p.y = mixRange(y0[i], yT[i], e); });
            draw(); anim = requestAnimationFrame(step);
        }
        anim = requestAnimationFrame(step);
    }
    function resetView() { animateTo(X_FULL.slice(), panels.map(function (p) { return p.y0.slice(); }), 480); }
    function stopAnim() { if (anim) { cancelAnimationFrame(anim); anim = 0; } animTgt = null; }
    function stepZoom(f) {
        // relative to where a running animation is heading, so quick repeated clicks add up smoothly
        var bx = animTgt ? animTgt.x : xv, by = animTgt ? animTgt.y : panels.map(function (p) { return p.y; });
        var full = X_FULL[1] - X_FULL[0], cx = (bx[0] + bx[1]) / 2, sx = Math.max(1e-4, Math.min(full * 3, (bx[1] - bx[0]) / f));
        var yT = panels.map(function (p, i) {
            var b = by[i], c = (b[0] + b[1]) / 2, s = (b[1] - b[0]) / f, minS = LOG ? 0.02 : 1e-3, maxS = LOG ? 40 : 1e9;
            if (s < minS || s > maxS) s = b[1] - b[0];
            return [c - s / 2, c + s / 2];
        });
        animateTo([cx - sx / 2, cx + sx / 2], yT, 240);
    }
    function exportPng() {
        hover = null; tip.style.display = 'none'; draw();
        cv.toBlob(function (b) {
            if (!b) return;
            var a = document.createElement('a');
            a.href = URL.createObjectURL(b); a.download = 'muonic_spectrum.png';
            document.body.appendChild(a); a.click(); a.remove();
        }, 'image/png');
    }
    // the zoom / reset / save buttons live in the settings row above (their own small frame) and call these
    try { window.parent.__specPlot = { zoom: stepZoom, reset: resetView, save: exportPng, fullscreen: toggleFs }; } catch (err) {}
    syncFs();

    cv.addEventListener('wheel', function (e) {
        e.preventDefault(); stopAnim();
        var r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
        var dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
        var f = Math.exp(-dy * 0.0016);
        var p = panelAt(my);
        var inX = mx >= M.l, onYAxis = mx < M.l, onXAxis = my > H - M.b;
        if (onYAxis && p) { zoomY(p, unY(p, my), f); }
        else if (onXAxis || (!p && inX)) { zoomX(unX(mx), f); }
        else if (p && inX) {
            if (!e.ctrlKey) zoomX(unX(mx), f);
            if (!e.shiftKey) zoomY(p, unY(p, my), f);
        }
        hover = null; tip.style.display = 'none';
        redraw();
    }, { passive: false });

    var drag = null;
    cv.addEventListener('pointerdown', function (e) {
        stopAnim();
        var r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
        var p = panelAt(my);
        if (!p || mx < M.l) return;
        drag = { x: e.clientX, y: e.clientY, x0: xv.slice(), p: p, y0: p.y.slice() };
        cv.setPointerCapture(e.pointerId); cv.classList.add('drag');
        hover = null; tip.style.display = 'none';
    });
    cv.addEventListener('pointermove', function (e) {
        var r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
        if (drag) {
            var dx = e.clientX - drag.x, dy = e.clientY - drag.y, spanX = drag.x0[1] - drag.x0[0], spanY = drag.y0[1] - drag.y0[0];
            xv = [drag.x0[0] - dx / plotW() * spanX, drag.x0[1] - dx / plotW() * spanX];
            drag.p.y = [drag.y0[0] + dy / drag.p.h * spanY, drag.y0[1] + dy / drag.p.h * spanY];
            saveView(); redraw(); return;
        }
        // hover read-out
        var best = null;
        for (var i = bars.length - 1; i >= 0; i--) {
            var b = bars[i];
            if (mx >= b.x - 1.5 && mx <= b.x + b.w + 1.5 && my >= b.y - 1.5 && my <= b.base + 1) { best = b; break; }
        }
        if (best !== hover) { hover = best; redraw(); }
        if (!best) { tip.style.display = 'none'; return; }
        var s = sp[best.i], binW = best.bw / plotW() * (xv[1] - xv[0]);
        var a = best.k * binW, bnd = (best.k + 1) * binW, lo = lowerBound(s.e, a), hi = lowerBound(s.e, bnd), rows = [];
        for (var q = lo; q < hi && rows.length < 6; q++) rows.push('E = ' + s.e[q].toFixed(3) + ' keV &nbsp;→&nbsp; ' + group(s.c[q]));
        if (hi - lo > 6) rows.push('… +' + (hi - lo - 6));
        var tot = 0; for (q = lo; q < hi; q++) tot += s.c[q];
        tip.innerHTML = (NORM ? '<b>' + (+best.v.toPrecision(4)) + '%</b> &nbsp;(' + group(tot) + ')' : '<b>' + group(tot) + '</b> counts') +
            '<br>' + rows.join('<br>');
        tip.style.borderLeft = '4px solid ' + s.color;   // the spectrum is told apart by colour only
        tip.style.display = 'block';
        var tw = tip.offsetWidth, th = tip.offsetHeight;
        var tx = mx + 14, ty2 = my + 14;
        if (tx + tw > W - 4) tx = mx - tw - 14;
        if (ty2 + th > H - 4) ty2 = my - th - 14;
        tip.style.left = Math.max(2, tx) + 'px'; tip.style.top = Math.max(2, ty2) + 'px';
    });
    function endDrag(e) { if (!drag) return; drag = null; cv.classList.remove('drag'); try { cv.releasePointerCapture(e.pointerId); } catch (err) {} }
    cv.addEventListener('pointerup', endDrag);
    cv.addEventListener('pointercancel', endDrag);
    cv.addEventListener('pointerleave', function () { if (!drag) { hover = null; tip.style.display = 'none'; redraw(); } });
    cv.addEventListener('dblclick', resetView);

    if (window.ResizeObserver) new ResizeObserver(resize).observe(stage); else window.addEventListener('resize', resize);
    resize();
})();
</script>
</body>
</html>

'''


PLOT_BUTTONS_TEMPLATE = r'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; height: 100%; background: transparent; overflow: hidden; }
    body { font-family: 'Calibri', 'Segoe UI', Arial, sans-serif; user-select: none; }
    /* the buttons are centred in the first 44px of the frame (= the height of the settings row: the frame has -28px margin below),
       so their centre lies on the common centre line of the row at every text size */
    .rowbox { height: 44px; display: flex; align-items: center; }
    .row { display: inline-flex; align-items: center; gap: 6px; }
    button {
        font-family: 'Calibri', 'Segoe UI', sans-serif;
        background: #ffffff; color: #1e293b; border: 1px solid #64748b;
        border-radius: 6px; padding: 4px 9px; font-size: calc(13px * var(--fs));
        font-weight: 600; cursor: pointer; transition: all 0.15s; position: relative;
        display: inline-flex; align-items: center; justify-content: center; height: calc(28px * var(--fs));
    }
    button.icon { padding: 4px 8px; }
    button:hover { background: #f1f5f9; }
    .zoom-btn-wrap { position: relative; display: inline-flex; align-items: center; }
    .zoom-wheel-tooltip {
        position: absolute; bottom: -34px; left: 50%; transform: translateX(-50%);
        background: #0f172a; color: #ffffff; font-size: 11.5px; font-weight: 600;
        padding: 4px 10px; border-radius: 6px; white-space: nowrap;
        display: flex; align-items: center; gap: 6px;
        opacity: 0; pointer-events: none; transition: opacity 0.15s ease; z-index: 120;
        box-shadow: 0 3px 8px rgba(15, 23, 42, 0.35); border: 1px solid #334155;
    }
    .zoom-btn-wrap:hover .zoom-wheel-tooltip { opacity: 1; }
    /* the tooltips of the two end buttons open inwards, so the frame never clips them */
    #row[dir="ltr"] .first .zoom-wheel-tooltip, #row[dir="rtl"] .last .zoom-wheel-tooltip { left: 0; transform: none; }
    #row[dir="ltr"] .last .zoom-wheel-tooltip, #row[dir="rtl"] .first .zoom-wheel-tooltip { left: auto; right: 0; transform: none; }
</style>
</head>
<body>
<div class="rowbox">
<div class="row" id="row">
    <div class="zoom-btn-wrap first">
        <button id="zo" style="font-weight:800;">&minus;</button>
        <div class="zoom-wheel-tooltip"><svg width="14" height="18" viewBox="0 0 14 20" fill="none"><rect x="1" y="1" width="12" height="18" rx="6" stroke="#38bdf8" stroke-width="1.8"/><rect x="6" y="4" width="2" height="4.5" rx="1" fill="#f59e0b"/></svg><span id="tt1"></span></div>
    </div>
    <button id="zr"></button>
    <div class="zoom-btn-wrap">
        <button id="zi" style="font-weight:800;">+</button>
        <div class="zoom-wheel-tooltip"><svg width="14" height="18" viewBox="0 0 14 20" fill="none"><rect x="1" y="1" width="12" height="18" rx="6" stroke="#38bdf8" stroke-width="1.8"/><rect x="6" y="4" width="2" height="4.5" rx="1" fill="#f59e0b"/></svg><span id="tt2"></span></div>
    </div>
    <div class="zoom-btn-wrap">
        <button id="ex" class="icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 11l5 5 5-5M5 20h14"/></svg></button>
        <div class="zoom-wheel-tooltip"><span id="tt3"></span></div>
    </div>
    <div class="zoom-btn-wrap last">
        <button id="fs" class="icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg></button>
        <div class="zoom-wheel-tooltip"><span id="tt4"></span></div>
    </div>
</div>
</div>
<script>
(function () {
    var UI = __UI__;
    var S = Math.max(0.85, Math.min(1.3, UI.fs || 1));
    document.documentElement.style.setProperty('--fs', S);
    var row = document.getElementById('row');
    row.setAttribute('dir', 'ltr');   // the buttons sit in the same places in Hebrew and English
    document.getElementById('tt1').textContent = UI.wheel;
    document.getElementById('tt2').textContent = UI.wheel;
    document.getElementById('tt3').textContent = UI.exportLabel;
    document.getElementById('tt4').textContent = UI.fullscreenTip;
    document.getElementById('zr').textContent = UI.reset;
    function call(name, arg) { try { var pl = window.parent.__specPlot; if (pl && pl[name]) pl[name](arg); } catch (err) {} }
    document.getElementById('zo').onclick = function () { call('zoom', 1 / 1.3); this.blur(); };
    document.getElementById('zi').onclick = function () { call('zoom', 1.3); this.blur(); };
    document.getElementById('zr').onclick = function () { call('reset'); this.blur(); };
    document.getElementById('ex').onclick = function () { call('save'); this.blur(); };
    document.getElementById('fs').onclick = function () { call('fullscreen'); this.blur(); setTimeout(syncFs, 150); };
    // the button turns into "exit full screen" (corners pointing inwards) while the plot is full screen
    var SVG_ENTER = document.getElementById('fs').innerHTML;
    var SVG_EXIT = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
    var lastFs = null;
    function syncFs() {
        var on = false;
        try {
            var col = window.frameElement.closest('.st-key-plot_controls_row').closest('[data-testid="stColumn"]');
            on = !!col && col.hasAttribute('data-plotfs');
        } catch (err) {}
        if (on === lastFs) return;
        lastFs = on;
        document.getElementById('fs').innerHTML = on ? SVG_EXIT : SVG_ENTER;
        document.getElementById('tt4').textContent = on ? UI.exitTip : UI.fullscreenTip;
    }
    syncFs(); setInterval(syncFs, 200);
    // the frame shrinks to its buttons, so the gaps between the groups of the settings row come out equal
    function fit() {
        try { window.frameElement.style.width = Math.ceil(row.getBoundingClientRect().width) + 'px'; } catch (err) {}
    }
    fit(); setTimeout(fit, 120); setTimeout(fit, 600);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
})();
</script>
</body>
</html>
'''


def render_plot_buttons(height=72):
    """Zoom in / zoom out / 100% / save-as-image buttons (a small frame inside the settings row above the plot)."""
    ui = {
        "reset": tr("reset_zoom"),
        "wheel": tr("wheel_tooltip"),
        "exportLabel": tr("plot_export"),
        "fullscreenTip": tr("fullscreen").split(" ", 1)[-1],
        "exitTip": tr("exit_fullscreen").split(" ", 1)[-1],
        "rtl": st.session_state.lang == "HE",
        "fs": st.session_state.font_scale / 100.0,
    }
    embed_html(PLOT_BUTTONS_TEMPLATE.replace("__UI__", json.dumps(ui)), height)


def spectrum_lines(spec):
    """Exact emission lines of a spectrum: (sorted energies, counts). Cached on the spectrum."""
    n = len(spec["photons"])
    cache = spec.get("_lines")
    if cache and cache[0] == n:
        return cache[1], cache[2]
    energies, counts = np.unique(np.asarray(spec["photons"], dtype=float), return_counts=True)
    spec["_lines"] = (n, [round(float(e), 6) for e in energies], [int(c) for c in counts])
    return spec["_lines"][1], spec["_lines"][2]


def render_interactive_spectrum(data, height=500):
    """Interactive (zoom / pan) spectrum plot drawn on a canvas inside an iframe."""
    ui = {
        "reset": tr("reset_zoom"),
        "wheel": tr("wheel_tooltip"),
        "exportLabel": tr("plot_export"),
        "rtl": st.session_state.lang == "HE",
        "fs": st.session_state.font_scale / 100.0,
    }
    html = (
        PLOT_HTML_TEMPLATE
        .replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
        .replace("__UI__", json.dumps(ui))
    )
    with st.container(key="plot_frame"):
        embed_html(html, height)


def render_inside_card_progress_bar(progress_frac):
    """
    Renders a progress bar COMPLETELY inside the spectrum card that fills from left to right
    according to the percentage, with the spinning Atom icon and percentage centered inside it.
    """
    pct_int = int(round(max(0.0, min(1.0, float(progress_frac))) * 100))
    return f"""
    <div style="position:relative; width:100%; height:20px; margin:0 2px 2px 2px; width:calc(100% - 4px); background:#e2e8f0; border:1px solid #64748b; border-radius:5px; overflow:hidden; box-sizing:border-box;">
        <div style="position:absolute; top:0; left:0; bottom:0; width:{pct_int}%; background:linear-gradient(90deg, #93c5fd 0%, #38bdf8 100%); transition:width 0.25s ease;"></div>
        <div style="position:relative; z-index:2; width:100%; height:100%; display:flex; align-items:center; justify-content:center; gap:6px;">
            <svg width="17" height="17" viewBox="0 0 28 28" style="flex-shrink:0; animation: atomSpin 1.2s linear infinite;">
                <ellipse cx="14" cy="14" rx="10.5" ry="3.8" fill="none" stroke="#0f4c81" stroke-width="1.8"/>
                <ellipse cx="14" cy="14" rx="10.5" ry="3.8" fill="none" stroke="#0f4c81" stroke-width="1.8" transform="rotate(60 14 14)"/>
                <ellipse cx="14" cy="14" rx="10.5" ry="3.8" fill="none" stroke="#0f4c81" stroke-width="1.8" transform="rotate(120 14 14)"/>
                <circle cx="14" cy="14" r="2.6" fill="#c1121f"/>
            </svg>
            <span style="font-size:0.82em; font-weight:800; color:#0f172a;">{pct_int}%</span>
        </div>
    </div>
    """


def _level_lock(element, level_name, isotope=None):
    """One lock per (element, isotope, level): MUDIRAC temp files are named after the element and level,
    so different levels can run in parallel while identical ones are serialised."""
    with shared_res["lock"]:
        return shared_res.setdefault("level_locks", {}).setdefault((element, isotope, level_name), threading.Lock())


def _mc_for(isotope):
    """muonic_cascade123 works in one output folder with file names built from element and level only, so two
    isotopes of the same element would overwrite each other's MUDIRAC files when run in parallel. Every isotope
    therefore gets its own private copy of the module (own OUTPUT_DIR, same code, shared results cache)."""
    if not isotope:
        return mc
    with shared_res["lock"]:
        mods = shared_res.setdefault("mc_modules", {})
        mod = mods.get(isotope)
        if mod is None:
            spec = importlib.util.spec_from_file_location(f"muonic_cascade123_iso{isotope}", mc.__file__)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.OUTPUT_DIR = os.path.join(mc.OUTPUT_DIR, f"iso_{isotope}")
            os.makedirs(mod.OUTPUT_DIR, exist_ok=True)
            mods[isotope] = mod
    mod.live_cache = shared_res["cache"]
    return mod


def verify_isotope_available(element, isotope):
    """Asks MUDIRAC once (2p -> 1s) whether it knows this isotope. Only a real 'Isotope not found' from MUDIRAC is an
    error; a state that merely fails to converge is handled later by the normal fallbacks."""
    known = shared_res.setdefault("isotope_known", {})
    key = (element, isotope)
    if key in known:
        return known[key]
    mcm = _mc_for(isotope)
    with _level_lock(element, "2p_3/2", isotope):
        fn = mcm.create_mudirac_input(
            "2p_3/2", target="1s_1/2", verbose=False, element=element,
            nuclear_model="FERMI2", uehling_correction=False, electronic_config=screening_config(element),
            reduced_mass=True, isotope=isotope
        )
        text = ""
        if fn:
            base = os.path.splitext(fn)[0]
            for ext in (".err", ".log"):
                if os.path.exists(base + ext):
                    with open(base + ext, errors="ignore") as fh:
                        text += fh.read()
            for ext in (".in", ".xr.out", ".out", ".log", ".err"):
                if os.path.exists(base + ext):
                    os.remove(base + ext)
    # MUDIRAC aborts with "Isotope/element does not exist" for an unknown isotope (create_mudirac_input returns None).
    # A crash can have other causes, so it is re-tested once without the electronic background.
    if not fn:
        with _level_lock(element, "2p_3/2", isotope):
            fn2 = mcm.create_mudirac_input(
                "2p_3/2", target="1s_1/2", verbose=False, element=element,
                nuclear_model="POINT", uehling_correction=False, isotope=isotope
            )
            if fn2:
                base2 = os.path.splitext(fn2)[0]
                for ext in (".in", ".xr.out", ".out", ".log", ".err"):
                    if os.path.exists(base2 + ext):
                        os.remove(base2 + ext)
        fn = fn2
    ok = bool(fn) and "isotope not found" not in text.lower()
    known[key] = ok
    return ok


def _parse_level(level_name):
    """'5g_9/2' -> (n=5, l=4, two_j=9)."""
    m = re.match(r"^(\d+)([a-z])_(\d+)/2$", level_name)
    n_val, l_char, two_j = int(m.group(1)), m.group(2), int(m.group(3))
    return n_val, mc.l_symbols.index(l_char), two_j


def enforce_selection_rules(level_name, transitions):
    """Keeps only electric-dipole (E1) radiative transitions to a lower-energy state of the same or a lower shell
    (|Δl| = 1, |Δj| <= 1) and re-normalises the branching ratios. Anything else cannot produce a single-photon X-ray
    line. (Transitions inside one shell exist: in heavy atoms the finite nuclear size lifts the s states above the p
    states, e.g. 3s -> 3p in gold; MUDIRAC returns only the lines with a positive energy.)"""
    n_i, l_i, j_i = _parse_level(level_name)
    kept = []
    for t in transitions:
        n_f, l_f, j_f = _parse_level(t["Target Level"])
        if n_f <= n_i and abs(l_f - l_i) == 1 and abs(j_f - j_i) <= 2 and t["Rate (s^-1)"] > 0:
            kept.append(dict(t))
    total = sum(t["Rate (s^-1)"] for t in kept)
    if total <= 0:
        return []
    for t in kept:
        t["Probability (%)"] = t["Rate (s^-1)"] / total * 100.0
    kept.sort(key=lambda x: x["Probability (%)"], reverse=True)
    return kept


class MudiracError(RuntimeError):
    """MUDIRAC gave no result for a state. Nothing is ever substituted for it: the calculation stops with this message.
    level_txt / name_txt let the page word the message in the language that is shown (see spec_error_text)."""
    def __init__(self, message, level_txt="", name_txt=""):
        super().__init__(message)
        self.level_txt, self.name_txt = level_txt, name_txt


def spec_error_text(spec):
    """The error shown for a spectrum, in the current language (MUDIRAC failures are worded from the translation table)."""
    args = spec.get("mudirac_error")
    if args:
        return tr("mudirac_error").format(level=args[0], name=args[1])
    return spec.get("status_text", "Error")


def safe_calculate_transitions(level_name, element, lock, _cancel=None, **physics_kwargs):
    """Thread-safe wrapper around mc.calculate_branching_ratios. Everything returned is a MUDIRAC result (only
    electric-dipole lines to lower-energy states are kept; a level without any (e.g. 2s in muonic hydrogen) gives []).
    If MUDIRAC cannot compute the level with the requested settings a MudiracError is raised."""
    def _check():
        if _cancel is not None and _cancel():
            raise RuntimeError("cancelled")

    _check()

    iso = physics_kwargs.get("isotope")
    mcm = _mc_for(iso)
    with _level_lock(element, level_name, iso):
        _check()
        transitions = mcm.calculate_branching_ratios(
            level_name, element=element, print_table=False, **physics_kwargs
        )
        if transitions is None:        # None = MUDIRAC gave no complete result; [] = it ran cleanly and the level has no decay line
            _lv, _nm = format_level_unicode(level_name), spec_name_unicode({'element': element, 'isotope': iso})
            raise MudiracError(f"MUDIRAC could not compute the level {_lv} of {_nm} with these settings.", _lv, _nm)
        return enforce_selection_rules(level_name, transitions)

def plan_isotopes(element, isotope):
    """Returns (mode, [(A or None, weight)]). mode: 'specific' | 'natural' | 'default'."""
    if isotope:
        return "specific", [(int(isotope), 1.0)]
    table = NATURAL_ABUNDANCE.get(element)
    if table:
        picked = [(a, w) for a, w in table.items() if w >= NAT_MIN_ABUNDANCE]
        if not picked:
            picked = [max(table.items(), key=lambda kv: kv[1])]
        total = sum(w for _, w in picked)
        return "natural", [(a, w / total) for a, w in picked]
    return "default", [(None, 1.0)]


_SYMBOL_BY_Z = {z_: sym_ for sym_, (z_, _en, _he) in ELEMENT_INFO.items()}


def screening_config(element):
    """Electronic background as in the MUDIRAC paper (Sturniolo & Hillier 2021, sect. 5.2 and Tab. 2): the configuration
    of the neutral atom with Z-1, because the muon itself screens one unit of the nuclear charge (e.g. Mg -> the
    configuration of neutral Na). Hydrogen has no electron left: no background."""
    z = ELEMENT_INFO[element][0]
    return f"[{_SYMBOL_BY_Z[z - 1]}]" if z > 1 else None


def mudirac_can_run(element, isotope, model, uehling=True):
    """True only when the MUDIRAC executable itself can run this element / isotope selection with this nuclear model
    (mudirac_support.py, generated by really running MUDIRAC on the lines K1-L2 and K1-L3):
      POINT  - both lines converge with the point nucleus;
      SPHERE - tabulated nuclear charge radius and SPHERE converges;
      FERMI2 - tabulated radius and FERMI2 converges, or no radius and FERMI2 converges with the empirical radius of
               the MUDIRAC paper (fermi_fallback_kwargs), which this MUDIRAC build accepts only without vacuum polarization.
    isotope None = natural mix (all its isotopes must pass) or MUDIRAC's default isotope."""
    if ELEMENT_INFO.get(element, (999,))[0] > MAX_SELECTABLE_Z:
        return False
    for a, _w in plan_isotopes(element, isotope)[1]:
        if a is None:
            d = DEFAULT_ISOTOPE.get(element, {})
            if not d.get("known") or (model != "POINT" and not d.get("radius")):
                return False
            continue
        if model == "POINT":
            # measured with MUDIRAC (QED + screening on, n up to 5): the p1/2 states of a point nucleus stop converging from
            # Z = 76 (Os 5p1/2), at lower n with growing Z (Ir 4p, Hg 3p, Rn 2p); a point nucleus is also unphysical there
            ok = a in POINT_ISOTOPES.get(element, ()) and ELEMENT_INFO[element][0] <= POINT_MAX_Z
        elif model == "SPHERE":
            ok = a in SPHERE_ISOTOPES.get(element, ())
        else:
            ok = a in RADIUS_ISOTOPES.get(element, ()) or (a in FALLBACK_FERMI.get(element, ()) and not uehling)
        if not ok:
            return False
    return True


def fermi_fallback_kwargs(element, a):
    """MUDIRAC input for FERMI2 when the isotope has no tabulated charge radius (Angeli & Marinova 2013). The MUDIRAC
    paper (Sturniolo & Hillier 2021, sect. 2.2, eq. 9-12) says to fall back on R = 1.2 A^(1/3) fm for such isotopes;
    this MUDIRAC build returns NaN instead of doing so, so the same numbers are given through fermi_c / fermi_t (fm):
    delta_F = 2.3 fm and, for A >= 5, R_F = sqrt(R^2 - 7/3 (pi delta_F / (4 ln 3))^2) (eq. 11); for A < 5 eq. 12."""
    if not a or a in RADIUS_ISOTOPES.get(element, ()):
        return {}
    delta = 2.3
    arg = (1.2 * a ** (1 / 3)) ** 2 - 7.0 / 3.0 * (math.pi * delta / (4.0 * math.log(3.0))) ** 2
    if a >= 5 and arg > 0:
        r_f = math.sqrt(arg)
    else:          # light nuclei, where eq. 11 fails (negative root): eq. 12 of the paper
        r_f = (2.2291e-5 * a ** (1 / 3) - 0.90676e-5) * 52917.721067
    return {"fermi_c": round(r_f, 5), "fermi_t": delta}


def runnable_isotope_options(element, model, uehling=True):
    """The isotope choices (None first) that MUDIRAC can run for this element and nuclear model."""
    first = [None] if len(NATURAL_ABUNDANCE.get(element, ())) > 1 else []   # a natural mix needs several natural isotopes
    return [a for a in first + STABLE_ISOTOPES.get(element, []) if mudirac_can_run(element, a, model, uehling)]


# ==============================================================================
# UNIFIED BACKGROUND WORKER
#   Phase A ("running"):     cascade tree + Monte Carlo over ALL muons -> exact spectrum (spectrum_ready)
#   Phase B ("simulating"):  builds the animation data set -> "completed" (Play becomes available)
# ==============================================================================
def _worker_once(spec_entry, run_token, lock, shared_cache):
    """One attempt. Returns None on success / cancellation, or the exception that stopped it."""
    mc.live_cache = shared_cache
    element = spec_entry["element"]
    start_level = spec_entry["start_level"]
    num_muons = spec_entry["num_muons"]

    def cancel_fn():
        return spec_entry.get("cancel", False) or spec_entry.get("run_token") != run_token

    base_kwargs = {
        "nuclear_model": spec_entry["nuclear_model"],
        "uehling_correction": spec_entry["uehling"],
        "reduced_mass": NUCLEAR_RECOIL,
    }
    # None = "no electronic background": muonic_cascade123 would otherwise always add its own [element] default
    base_kwargs["electronic_config"] = screening_config(element) if spec_entry["screening"] else None

    def kwargs_for(iso_a):
        kw = dict(base_kwargs)
        if iso_a:
            kw["isotope"] = int(iso_a)
            if spec_entry["nuclear_model"] == "FERMI2":
                kw.update(fermi_fallback_kwargs(element, int(iso_a)))
        return kw

    iso_mode, iso_plan = plan_isotopes(element, spec_entry.get("isotope"))
    iso_ref = max(iso_plan, key=lambda x: x[1])[0]

    _t_start = time.time()
    try:
        for _a, _w in iso_plan:
            if _a and not verify_isotope_available(element, _a):
                raise ValueError(f"MUDIRAC does not know the isotope {_a}{element}")
        max_n = mc.get_n(start_level)
        levels_list = []
        level_map = {}
        max_l_seen = 1

        for lvl_name in mc.mudirac_dict.keys():
            n_val = mc.get_n(lvl_name)
            if n_val <= max_n:
                orb_part = lvl_name.split("_")[0]
                l_char = re.sub(r"^\d+", "", orb_part)
                l_idx = mc.l_symbols.index(l_char) if l_char in mc.l_symbols else 0
                max_l_seen = max(max_l_seen, l_idx)

                if l_idx == 0:
                    x_pos = 0.0
                else:
                    j_num = int(lvl_name.split("_")[1].split("/")[0])
                    is_high_j = (j_num == 2 * l_idx + 1)
                    x_pos = l_idx + (0.20 if is_high_j else -0.20)

                orb_str, j_str = lvl_name.split("_", 1)
                entry = {
                    "name": lvl_name,
                    "orb": orb_str,
                    "j_str": j_str,
                    "code": mc.mudirac_dict[lvl_name],
                    "n": n_val,
                    "l": l_idx,
                    "x_pos": x_pos
                }
                levels_list.append(entry)
                level_map[lvl_name] = entry

        _dist = spec_entry.get("distribution", "delta")
        if _dist in ("uniform", "statistical"):
            n_start = mc.get_n(start_level)
            start_levels = [
                lvl for lvl in mc.mudirac_dict.keys()
                if mc.get_n(lvl) == n_start and is_sublevel_allowed_for_element(lvl, element)
            ] or [start_level]
            if _dist == "uniform":
                base_cnt, extra = divmod(num_muons, len(start_levels))
                per_level = {lvl: base_cnt for lvl in start_levels}
                for lvl in random.sample(start_levels, extra):
                    per_level[lvl] += 1
                muon_starts = [lvl for lvl in start_levels for _ in range(per_level[lvl])]
                random.shuffle(muon_starts)
            else:
                # statistical population: every muon draws its own capture sublevel with the weight (2j+1)
                _w = [initial_population_weight(lvl) for lvl in start_levels]
                muon_starts = random.choices(start_levels, weights=_w, k=num_muons)
        else:
            start_levels = [start_level]
            muon_starts = [start_level] * num_muons

        # Every muon draws its own isotope (natural mix: by abundance; otherwise a single isotope).
        if iso_mode == "natural" and len(iso_plan) > 1:
            muon_iso = random.choices([a for a, _ in iso_plan], weights=[w for _, w in iso_plan], k=num_muons)
        else:
            muon_iso = [iso_plan[0][0]] * num_muons

        # ---------------------------------------------------------------- cascade tree (parallel, per isotope)
        queue = [(a, lvl) for a, _ in iso_plan for lvl in start_levels]
        visited_states = set(queue)
        state_transitions_map = {}       # (isotope A, level) -> [{target, prob, energy, rate}]
        raw_tables_display = {}
        all_theoretical_edges = []
        seen_edges = set()
        max_photon_e = 10.0

        processed_count = 0
        n_workers = max(2, min(6, (os.cpu_count() or 4) - 2))  # leave CPU for the UI
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            while queue:
                if cancel_fn():
                    return

                batch = [node for node in queue if node[1] != "1s_1/2"]
                queue = []
                if not batch:
                    break

                est_total = max(len(visited_states), processed_count + len(batch))
                spec_entry["progress"] = min(0.45, 0.45 * (processed_count / max(1, est_total)))

                futures = [
                    pool.submit(safe_calculate_transitions, lv, element, lock, cancel_fn, **kwargs_for(a))
                    for a, lv in batch
                ]
                results = []
                for fut in futures:
                    results.append(fut.result())
                    if cancel_fn():
                        for other in futures:
                            other.cancel()
                        return

                for (iso_a, curr_lvl), trans in zip(batch, results):
                    processed_count += 1
                    cleaned_trans = []
                    formatted_rows = []
                    for idx_t, t in enumerate(trans):
                        t_lvl = t["Target Level"]
                        prob = float(t["Probability (%)"])
                        e_kev = float(t["Energy (keV)"])
                        rate_val = float(t["Rate (s^-1)"])
                        max_photon_e = max(max_photon_e, e_kev)

                        formatted_rows.append({
                            "Target Level": format_level_unicode(t_lvl),
                            "Energy ΔE (keV)": round(e_kev, 4),
                            "Rate (s⁻¹)": f"{rate_val:.3e}",
                            "Branching Ratio (%)": round(prob, 2),
                        })
                        cleaned_trans.append({
                            "target": t_lvl,
                            "prob": prob,
                            "energy": e_kev,
                            "rate": rate_val
                        })

                        if (iso_a == iso_ref and prob >= 1.0 and idx_t < 4 and t_lvl in level_map
                                and (curr_lvl, t_lvl) not in seen_edges):
                            seen_edges.add((curr_lvl, t_lvl))
                            all_theoretical_edges.append({
                                "from": curr_lvl,
                                "to": t_lvl,
                                "prob": prob,
                                "energy": e_kev
                            })

                        if (prob >= 0.2 and t_lvl in level_map and t_lvl != "1s_1/2"
                                and (iso_a, t_lvl) not in visited_states):
                            visited_states.add((iso_a, t_lvl))
                            queue.append((iso_a, t_lvl))
                            # The edge that first reaches a state is always kept, even if it is weak (< 1 %),
                            # so no level ever shows outgoing transitions without a way to get there.
                            if (curr_lvl, t_lvl) not in seen_edges:
                                seen_edges.add((curr_lvl, t_lvl))
                                all_theoretical_edges.append({
                                    "from": curr_lvl,
                                    "to": t_lvl,
                                    "prob": prob,
                                    "energy": e_kev
                                })

                    state_transitions_map[(iso_a, curr_lvl)] = cleaned_trans
                    if iso_a == iso_ref:
                        raw_tables_display[curr_lvl] = formatted_rows

            _t_tree = time.time()

            # ------------------------------------------------------------ Monte Carlo over ALL muons (phase A)
            # A muon that reaches a state without a computed branching table is parked; all parked states are then
            # computed IN PARALLEL and the muons resume.
            emitted_photons = []
            cum_cache = {}
            sim_enabled = num_muons < SIM_DISABLE_FROM
            keep_n = min(num_muons, MAX_ANIM_MUONS) if sim_enabled else 0
            kept_steps = [[] for _ in range(keep_n)]
            first_muon_steps = []
            cur_state = list(muon_starts)
            safety = [0] * num_muons
            finished = 0
            update_step = max(1, num_muons // 100)
            todo = list(range(num_muons))
            tag_iso = (iso_mode == "natural")

            while todo:
                if cancel_fn():
                    return
                blocked = {}
                for i in todo:
                    if (i & 255) == 0 and cancel_fn():
                        return
                    curr = cur_state[i]
                    iso_a = muon_iso[i]
                    while curr != "1s_1/2" and safety[i] < 90:
                        node = (iso_a, curr)
                        trans = state_transitions_map.get(node)
                        if trans is None:
                            blocked.setdefault(node, []).append(i)
                            break
                        if not trans:      # no downward dipole decay from here (e.g. 2s in muonic hydrogen): cascade ends
                            safety[i] = 99
                            break
                        safety[i] += 1
                        cw = cum_cache.get(node)
                        if cw is None or cw[0] is not trans:
                            cw = (trans, list(itertools.accumulate(t["prob"] for t in trans)))
                            cum_cache[node] = cw
                        chosen = random.choices(trans, cum_weights=cw[1], k=1)[0]
                        e_val = chosen["energy"]
                        if e_val > max_photon_e:
                            max_photon_e = e_val
                        emitted_photons.append(e_val)

                        if i == 0:
                            first_muon_steps.append(
                                f"**{format_level_unicode(curr)} → {format_level_unicode(chosen['target'])}** "
                                f"(ΔE = {e_val:.3f} keV, P = {chosen['prob']:.2f}%)"
                            )
                        if (curr, chosen["target"]) not in seen_edges:
                            seen_edges.add((curr, chosen["target"]))
                            all_theoretical_edges.append({
                                "from": curr,
                                "to": chosen["target"],
                                "prob": chosen["prob"],
                                "energy": e_val
                            })
                        if i < keep_n:
                            step = {
                                "from": curr,
                                "to": chosen["target"],
                                "energy": e_val,
                                "prob": chosen["prob"]
                            }
                            if tag_iso:
                                step["a"] = iso_a
                            kept_steps[i].append(step)
                        curr = chosen["target"]
                    cur_state[i] = curr
                    if curr == "1s_1/2" or safety[i] >= 90:
                        finished += 1
                        if finished % update_step == 0:
                            spec_entry["progress"] = 0.45 + 0.55 * (finished / num_muons) * 0.95

                todo = []
                if blocked:
                    miss = list(blocked.keys())
                    futs = [
                        pool.submit(safe_calculate_transitions, lv, element, lock, cancel_fn, **kwargs_for(a))
                        for a, lv in miss
                    ]
                    for node, fut in zip(miss, futs):
                        raw_t = fut.result()
                        state_transitions_map[node] = [{
                            "target": t["Target Level"],
                            "prob": float(t["Probability (%)"]),
                            "energy": float(t["Energy (keV)"]),
                            "rate": float(t["Rate (s^-1)"])
                        } for t in raw_t]
                        todo.extend(blocked[node])

        print(f"[worker] {element} {start_level} N={num_muons} iso={iso_mode}{[a for a, _ in iso_plan]}: "
              f"cascade tree {_t_tree - _t_start:.1f}s, Monte Carlo {time.time() - _t_tree:.1f}s", flush=True)

        if cancel_fn():
            return

        full_line_groups = []
        tol = max(0.4, max_photon_e * 0.004)
        for p_e, p_cnt in Counter(emitted_photons).items():
            matched = False
            for g in full_line_groups:
                if abs(g["energy"] - p_e) < tol:
                    g["count"] += p_cnt
                    matched = True
                    break
            if not matched:
                full_line_groups.append({"energy": p_e, "count": p_cnt})

        # The exact spectrum (all N muons) is now available: it can be shown / ticked / compared.
        spec_entry["photons"] = emitted_photons
        spec_entry["steps"] = first_muon_steps
        spec_entry["tables"] = raw_tables_display
        spec_entry["sim_progress"] = 0.0
        spec_entry["spectrum_ready"] = True
        spec_entry["progress"] = 1.0
        if not sim_enabled:
            spec_entry["payload"] = None
            spec_entry["status"] = "spectrum_only"
            return
        spec_entry["status"] = "simulating"

        # ------------------------------------------------------------------ phase B: animation data set
        trajectories = []
        chunk = max(1, keep_n // 50)
        for idx in range(keep_n):
            if idx % chunk == 0 and cancel_fn():
                return
            traj = []
            for st_ in kept_steps[idx]:
                item = {
                    "from": st_["from"],
                    "to": st_["to"],
                    "energy": round(st_["energy"], 4),
                    "prob": round(st_["prob"], 3),
                }
                if "a" in st_:
                    item["a"] = st_["a"]
                traj.append(item)
            trajectories.append(traj)

        # UI transition only: the data set above is built almost instantly. So that the two loading stages are
        # visible, wait until the page has drawn the finished spectrum, then sweep the ring over 2 s.
        for _ in range(200):
            if spec_entry.get("ready_rendered") or cancel_fn():
                break
            time.sleep(0.05)
        for k in range(1, 21):
            if cancel_fn():
                return
            spec_entry["sim_progress"] = max(spec_entry.get("sim_progress", 0.0), k / 20.0)
            time.sleep(0.1)

        state_transitions_ref = {lvl: tr_ for (a, lvl), tr_ in state_transitions_map.items() if a == iso_ref}
        z_atomic = ELEMENT_INFO.get(element, (26, "", ""))[0]
        # the real MUDIRAC radial wavefunctions of every state that can appear in the wavefunction window
        wf_kw = kwargs_for(iso_ref)
        wf_states = set(state_transitions_ref) | {t_["target"] for tr_ in state_transitions_ref.values() for t_ in tr_}
        wavefunctions = {}
        for lvl_ in wf_states:
            w_ = shared_cache.get(mc.wf_key(element, lvl_, wf_kw))
            if w_:
                wavefunctions[lvl_] = w_
        spec_entry["payload"] = {
            "wavefunctions": wavefunctions,
            "radius_fallback": any(bool(fermi_fallback_kwargs(element, a_)) for a_, _w in iso_plan)
                               and spec_entry["nuclear_model"] == "FERMI2",
            "id": spec_entry["id"],
            "run_nonce": run_token,
            "element": element,
            "element_label": spec_name_unicode(spec_entry),
            "z_atomic": z_atomic,
            "start_level": start_level,
            "start_levels": start_levels,
            "distribution": spec_entry.get("distribution", "delta"),
            "isotope_mode": iso_mode,
            "isotopes": [{"A": a, "w": round(w, 5)} for a, w in iso_plan],
            "isotope_ref": iso_ref,
            "num_muons": num_muons,
            "animated_muons": len(trajectories),
            "total_photons_all": len(emitted_photons),
            "nuclear_model": spec_entry["nuclear_model"],
            "max_n": max_n,
            "max_l": max_l_seen,
            "max_energy": max_photon_e * 1.12,
            "levels": levels_list,
            "level_map": level_map,
            "state_transitions": state_transitions_ref,
            "all_edges": all_theoretical_edges,
            "trajectories": trajectories,
            "full_line_groups": full_line_groups,
            "shell_letters": {str(k): v for k, v in mc.shell_letters.items()},
            "l_symbols": mc.l_symbols,
        }
        spec_entry["sim_progress"] = 1.0
        spec_entry["status"] = "completed"

    except Exception as exc:
        import traceback
        print(f"[worker] {element} {start_level} N={num_muons}: attempt failed with {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return exc
    return None


def unified_background_worker(spec_entry, run_token, lock, shared_cache):
    def cancelled():
        return spec_entry.get("cancel", False) or spec_entry.get("run_token") != run_token

    exc = _worker_once(spec_entry, run_token, lock, shared_cache)
    if exc is not None and not cancelled() and not (isinstance(exc, RuntimeError) and str(exc) == "cancelled"):
        # A one-off failure (e.g. a MUDIRAC run that crashed) is retried once; finished MUDIRAC results are cached.
        time.sleep(1.0)
        spec_entry["status"] = "running"
        spec_entry["progress"] = 0.0
        spec_entry["spectrum_ready"] = False
        exc = _worker_once(spec_entry, run_token, lock, shared_cache)
    if exc is not None and not cancelled():
        spec_entry["status"] = "error"
        # a MudiracError already is a complete sentence for the user; other failures keep their technical prefix
        spec_entry["status_text"] = str(exc) if isinstance(exc, MudiracError) else f"Error: {type(exc).__name__}: {exc}"
        spec_entry["mudirac_error"] = (exc.level_txt, exc.name_txt) if isinstance(exc, MudiracError) else None


def start_simulation_thread(spec_entry):
    """Starts or restarts a background calculation with a fresh run_token."""
    new_token = str(uuid.uuid4())[:8]
    spec_entry["run_token"] = new_token
    spec_entry["status"] = "running"
    spec_entry["progress"] = 0.0
    spec_entry["cancel"] = False
    spec_entry["notified_done"] = False
    spec_entry["spectrum_ready"] = False
    spec_entry["notified_ready"] = False
    spec_entry["ready_rendered"] = False
    spec_entry["sim_progress"] = 0.0

    thread = threading.Thread(
        target=unified_background_worker,
        args=(spec_entry, new_token, shared_res["lock"], shared_res["cache"]),
        daemon=True
    )
    thread.start()


# ==============================================================================
# ZERO-SCROLL FLOATING MODAL DIALOG
# ==============================================================================
def render_dialog_body():
    with st.container(key="dlg_close_x"):
        if st.button("✕", key="dlg_close_btn"):
            st.session_state.dialog_alive = False
            st.rerun(scope="app")

    edit_id = st.session_state.editing_id
    is_new = (edit_id == "NEW")
    ep = st.session_state.editor_params
    is_he = (st.session_state.lang == "HE")

    if not is_sublevel_allowed_for_element(ep["start_level"], ep["element"]):
        n_curr = max(2, mc.get_n(ep["start_level"]))
        valid_in_shell = [
            lvl for lvl in mc.mudirac_dict.keys()
            if mc.get_n(lvl) == n_curr and is_sublevel_allowed_for_element(lvl, ep["element"])
        ]
        ep["start_level"] = valid_in_shell[-1] if valid_in_shell else "2p_3/2"

    # left to right: number of muons | muon distribution | initial level | isotope | nuclear model | 3 corrections
    c_mu, c_dist, c_lvl, c_iso, c_model, c_corr = st.columns(6, gap="large", vertical_alignment="top")

    muon_options = [1, 3, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 100000, 1000000]
    default_muons = ep["num_muons"] if ep["num_muons"] in muon_options else 10
    mu_key = f"dlg_mu_{st.session_state.get('dlg_serial', 0)}"
    if st.session_state.get(mu_key) not in muon_options:
        st.session_state[mu_key] = default_muons
    with c_mu:
        with st.container(key="muon_slider_box"):
            num_muons = st.select_slider(tr("muon_count"), options=muon_options, key=mu_key, format_func=lambda v: f"{v:,}")
            if num_muons >= SIM_DISABLE_FROM:
                # not printed on the page: a small label floating above the slider thumb
                _thumb_left = 100.0 - muon_options.index(num_muons) / (len(muon_options) - 1) * 100.0
                st.markdown(
                    f"<div class='sim-tip' dir='{'rtl' if st.session_state.lang == 'HE' else 'ltr'}' "
                    f"style='left:clamp(30%, {_thumb_left:.1f}%, 70%)'>"
                    f"{tr('sim_disabled_note').format(limit=f'{SIM_DISABLE_FROM:,}')}</div>",
                    unsafe_allow_html=True
                )
    ep["num_muons"] = num_muons

    dist_options = ["statistical", "uniform", "delta"]   # default (first) = statistical, delta last
    _dist_names = {"delta": "dist_delta_short", "uniform": "dist_uniform_short",
                   "statistical": "dist_stat_short"}
    with c_dist:
        with st.container(key="dlg_dist_group"):    # the closed-box hover label comes from the page script (DIST_TIPS)
            ep["distribution"] = st.selectbox(
                tr("distribution_label"),
                dist_options,
                index=dist_options.index(ep.get("distribution", "statistical")) if ep.get("distribution", "statistical") in dist_options else 0,
                format_func=lambda k: tr(_dist_names[k]),
            )
    is_uniform = (ep["distribution"] != "delta")   # every n-wide distribution: no single sublevel is chosen

    # initial level: the title above the n box, and below it (delta distribution only) the sublevel box
    current_n = mc.get_n(ep["start_level"])
    max_allowed_n = MAX_START_N
    allowed_n_options = list(range(2, max_allowed_n + 1))
    if current_n not in allowed_n_options:
        current_n = allowed_n_options[-1]

    n_key = f"dlg_n_{st.session_state.get('dlg_serial', 0)}"
    if st.session_state.get(n_key) not in allowed_n_options:
        st.session_state[n_key] = current_n
    st.session_state["_dlg_n_key"] = n_key
    st.session_state["_dlg_n_opts"] = allowed_n_options
    with c_lvl:
        with st.container(key="dlg_lvl_group"):
            st.markdown(f"<div class='dlg-cap'>{tr('initial_level_row_label')}</div>", unsafe_allow_html=True)
            st.text_input(
                "n_bridge",
                key="_n_bridge",
                on_change=_apply_n_wheel_step,
                label_visibility="collapsed"
            )
            selected_n = st.selectbox(
                "n",
                options=allowed_n_options,
                key=n_key,
                format_func=lambda n_val: f"n = {n_val}",
                label_visibility="collapsed"
            )
            shell_sublevels = [
                lvl for lvl in mc.mudirac_dict.keys()
                if mc.get_n(lvl) == selected_n and is_sublevel_allowed_for_element(lvl, ep["element"])
            ]
            if is_uniform:
                # n-wide distributions: no sublevel choice
                selected_sublevel = shell_sublevels[-1]
            else:
                default_sub_idx = (
                    shell_sublevels.index(ep["start_level"])
                    if ep["start_level"] in shell_sublevels
                    else len(shell_sublevels) - 1
                )
                selected_sublevel = st.selectbox(
                    "sublevel",
                    options=shell_sublevels,
                    index=default_sub_idx,
                    format_func=format_level_unicode,
                    label_visibility="collapsed"
                )
    st.session_state.editor_params["start_level"] = selected_sublevel

    # ---- nuclear model + isotope: the two depend on each other and NOTHING is ever changed behind the user's back ----
    #  * the isotope list is the same for the three nuclear models (every choice MUDIRAC can run in at least one of them);
    #    the entries it cannot run with the chosen model are shown faded and cannot be chosen;
    #  * the nuclear models that cannot run the chosen isotope are shown faded too (with an explanation), so a
    #    combination MUDIRAC cannot run can not be reached from the menus.
    nuc_models = ["FERMI2", "SPHERE", "POINT"]
    el_now = ep["element"]
    has_natural = el_now in NATURAL_ABUNDANCE     # "natural mix" exists only with a natural composition; MUDIRAC's own
    #                                               default isotope of the others (Tc, Pm, ...) is an arbitrary nuclide
    ueh_key = f"dlg_ueh_{st.session_state.get('dlg_serial', 0)}"
    uehling_now = st.session_state.get(ueh_key, ep["uehling"])     # the QED checkbox is drawn later; its state is current
    # option value 0 stands for "natural mix" (None would make Streamlit show its "Choose an option" placeholder)
    def _iso(v):
        return None if not v else v

    # a "natural mix" of a single isotope (Au-197, Be-9 ...) is that isotope itself: it is not offered twice
    has_mix = has_natural and len(NATURAL_ABUNDANCE[el_now]) > 1
    iso_options = [a for a in ([0] if has_mix else []) + STABLE_ISOTOPES.get(el_now, [])
                   if any(mudirac_can_run(el_now, _iso(a), m, u) for m in nuc_models for u in (True, False))]
    nothing_offered = not iso_options
    if nothing_offered:
        iso_options = [0]

    def _default_isotope(model):
        """natural mix; else the most abundant isotope (elements with a natural composition) or the longest-lived one
        (elements without), among the isotopes MUDIRAC can run with this model. Used only when the element changes."""
        ok = [a for a in iso_options if mudirac_can_run(el_now, _iso(a), model, uehling_now)]
        if not ok:
            return iso_options[0]
        if has_natural:
            ab = NATURAL_ABUNDANCE[el_now]
            return sorted(ok, key=lambda a: (a != 0, -ab.get(a, 0.0)))[0]
        ll = LONGEST_LIVED.get(el_now)
        return sorted(ok, key=lambda a: (a != ll, -a))[0]

    iso_key = f"dlg_iso_{el_now}_{st.session_state.get('dlg_serial', 0)}"
    if st.session_state.get(iso_key, "__unset__") not in iso_options:     # first time for this element
        st.session_state[iso_key] = _default_isotope(ep["nuclear_model"])
    iso_state = _iso(st.session_state[iso_key])                            # the isotope as chosen so far (current)

    def _model_text(m):
        return m if mudirac_can_run(el_now, iso_state, m, uehling_now) else m + "​​"   # invisible marker = faded, see fadeUnavailableOptions

    with c_model:
        with st.container(key="dlg_model_group"):   # hover labels of the options come from the page script (NUC_TIPS)
            ep["nuclear_model"] = st.selectbox(tr("nuclear_model"), nuc_models, format_func=_model_text,
                                               index=nuc_models.index(ep["nuclear_model"]))
    model_now = ep["nuclear_model"]
    nat_label = tr("isotope_natural") if has_natural else tr("isotope_default")

    def _iso_text(a_val):
        if nothing_offered:
            return "—"
        if not a_val:
            txt = nat_label
        else:
            txt = f"{str(a_val).translate(SUPERSCRIPT_DIGITS)}{el_now}"
            ab = NATURAL_ABUNDANCE.get(el_now, {}).get(a_val)
            if ab is not None:
                txt = f"{txt}  —  {format(ab, '.4g')}%"
        return txt if mudirac_can_run(el_now, _iso(a_val), model_now, uehling_now) else txt + "​​"

    with c_iso:
        with st.container(key="dlg_iso_group"):
            st.markdown(f"<div class='dlg-cap'>{tr('isotope_label')}</div>", unsafe_allow_html=True)
            _iso_choice = st.selectbox(
                "isotope",
                options=iso_options,
                key=iso_key,
                format_func=_iso_text,
                label_visibility="collapsed",
            )
    ep["isotope"] = _iso(_iso_choice)
    can_run = mudirac_can_run(el_now, ep["isotope"], model_now, uehling_now)   # also when a faded entry was reached by keyboard
    if nothing_offered or (not has_mix and ep["isotope"] is None):
        can_run = False          # no natural mix and no MUDIRAC default any more: a specific isotope is required

    # the three physical corrections, one above the other, at the right end
    with c_corr:
        with st.container(key="dlg_corr_group"):
            ep["uehling"] = st.checkbox(tr("qed_label"), value=ep["uehling"], help=tr("qed_help"), key=ueh_key)
            if ELEMENT_INFO.get(el_now, (0,))[0] <= 1:
                # hydrogen: the muon replaces the only electron, Z-1 = 0 -> no electronic background exists (see
                # screening_config). The box is shown unticked and disabled; the user's choice is kept for other elements.
                # (the saved choice belongs to this editor dict only: editing another spectrum creates a new dict)
                if st.session_state.get("_screening_before_h", (None,))[0] != id(ep):
                    st.session_state["_screening_before_h"] = (id(ep), ep["screening"])
                ep["screening"] = False
                st.checkbox(tr("screening_label"), value=False, disabled=True, help=tr("screening_help_h"))
            else:
                saved = st.session_state.pop("_screening_before_h", None)
                if saved and saved[0] == id(ep):
                    ep["screening"] = saved[1]
                ep["screening"] = st.checkbox(tr("screening_label"), value=ep["screening"], help=tr("screening_help"))

        # (the green button sits in the grey band of the window, see the CSS; it is created last so that it sees every setting)
        with st.container(key="dlg_green_create_btn"):
            btn_label = tr(("create" if is_new else "update") + ("_spec_sim" if num_muons < SIM_DISABLE_FROM else "_spec"))
            if st.button(btn_label, type="primary", use_container_width=True, disabled=not can_run,
                         help=None if can_run else tr("mudirac_cannot_run")):
                updated_params = dict(ep)
                if is_new:
                    new_id = str(uuid.uuid4())[:8]
                    color = pick_next_distinct_color()
                    new_item = {
                        "id": new_id,
                        **updated_params,
                        "visible": True,
                        "color": color,
                        "photons": [],
                        "steps": [],
                        "tables": {},
                        "payload": None,
                        "notified_done": False,
                    }
                    st.session_state[f"chk_{new_id}"] = True
                    st.session_state.spectra_list.insert(0, new_item)
                    start_simulation_thread(new_item)
                else:
                    for item in st.session_state.spectra_list:
                        if item["id"] == edit_id:
                            item["cancel"] = True
                            item.update(updated_params)
                            item["payload"] = None
                            start_simulation_thread(item)
                            break
                st.session_state.dialog_alive = False
                st.rerun(scope="app")

    st.markdown("<hr style='margin: 1px 0 3px 0; border:none; border-top:1px solid #cbd5e1;'>", unsafe_allow_html=True)

    with st.container(height=PERIODIC_TABLE_BOX_HEIGHT, border=True, key="periodic_table_box"):
        grid_lookup = {(r, c): (z, sym, n_en, n_he) for (r, c, z, sym, n_en, n_he) in MAIN_PERIODIC_TABLE}

        for r in range(7):
            cols = st.columns(18)
            for c in range(18):
                if r == 5 and c == 2:
                    cols[c].markdown(
                        "<div style='text-align:center; font-size:9.5px; color:#64748b; padding-top:2px;'>57-71</div>",
                        unsafe_allow_html=True
                    )
                    continue
                if r == 6 and c == 2:
                    cols[c].markdown(
                        "<div style='text-align:center; font-size:9.5px; color:#64748b; padding-top:2px;'>89-103</div>",
                        unsafe_allow_html=True
                    )
                    continue

                cell = grid_lookup.get((r, c))
                if cell is not None:
                    z_val, sym, n_en, n_he = cell
                    is_sel = (ep["element"] == sym)
                    b_type = "primary" if is_sel else "secondary"
                    hover_name = n_he if is_he else n_en
                    if cols[c].button(
                        sym,
                        key=f"pt_{sym}_{z_val}",
                        type=b_type,
                        help=hover_name,
                        use_container_width=True,
                        disabled=not runnable_isotope_options(sym, ep["nuclear_model"], uehling_now)
                    ):
                        st.session_state.editor_params["element"] = sym
                        st.rerun(scope="fragment")

        for block_label, row_data in [("57-71", LANTHANIDES_ROW), ("89-103", ACTINIDES_ROW)]:
            cols = st.columns(18)
            cols[1].markdown(
                f"<div style='text-align:right; font-size:9.5px; color:#475569; padding-top:2px;'>{block_label}</div>",
                unsafe_allow_html=True
            )
            for c_idx, z_val, sym, n_en, n_he in row_data:
                is_sel = (ep["element"] == sym)
                b_type = "primary" if is_sel else "secondary"
                hover_name = n_he if is_he else n_en
                if cols[c_idx].button(
                    sym,
                    key=f"pt_f_{sym}_{z_val}",
                    type=b_type,
                    help=hover_name,
                    use_container_width=True,
                    disabled=not runnable_isotope_options(sym, ep["nuclear_model"], uehling_now)
                ):
                    st.session_state.editor_params["element"] = sym
                    st.rerun(scope="fragment")

    st.session_state["_dlg_seq"] = st.session_state.get("_dlg_seq", 0) + 1
    st.markdown(f"<div class='run-marker dlg-marker' data-seq='{st.session_state['_dlg_seq']}'></div>", unsafe_allow_html=True)


# ==============================================================================
# 60-FPS HTML5 CANVAS ENGINE:
# - Mouse-Wheel support on Speed Slider AND Master Timeline Bar!
# - Smooth continuous Zoom-Out animation on Magnifying Glass click (🔍 100%)
# - Clickable badges both on the diagram AND in the bottom Branching Ratios bar
# ==============================================================================
def render_unified_canvas_animator(payload):
    ui_labels = {
        "play": tr("play"),
        "pause": tr("pause"),
        "replay": tr("replay"),
        "space_tooltip": tr("space_tooltip"),
        "prev_trans": tr("prev_trans"),
        "next_trans": tr("next_trans"),
        "start": tr("start"),
        "end": tr("end"),
        "fullscreen": tr("fullscreen"),
        "exit_fullscreen": tr("exit_fullscreen"),
        "reset_zoom": tr("reset_zoom"),
        "wheel_tooltip": tr("wheel_tooltip"),
        "all_probs": tr("all_probs"),
        "photon_anim": tr("photon_anim"),
        "gaussian": tr("gaussian"),
        "speed": tr("speed"),
        "timeline_hint": tr("timeline_hint"),
        "wf_modal_title": tr("wf_modal_title"),
        "wf_initial": tr("wf_initial"),
        "wf_target": tr("wf_target"),
        "wf_legend": tr("wf_legend"),
        "wf_approx": tr("wf_approx"),
        "wf_unavailable": tr("wf_unavailable"),
        "wf_norm": tr("wf_norm"),
        "wf_radius_fb": tr("wf_radius_fb"),
        "wf_axis": tr("wf_axis"),
        "wf_nuc_model": tr("wf_nuc_model"),
        "wf_table_title": tr("wf_table_title"),
        "wf_th_target": tr("wf_th_target"),
        "wf_th_energy": tr("wf_th_energy"),
        "wf_th_rate": tr("wf_th_rate"),
        "wf_th_prob": tr("wf_th_prob"),
        "wf_prob": tr("wf_prob"),
        "wf_close": tr("wf_close"),
        "branching": tr("branching"),
        "rtl": st.session_state.lang == "HE",
        "ground_reached": tr("ground_reached"),
        "no_transition": tr("no_transition"),
        "font_scale": st.session_state.font_scale / 100.0
    }
    json_data = json.dumps(payload)
    sim_key = hashlib.md5(json_data.encode("utf-8")).hexdigest()
    json_ui = json.dumps(ui_labels)

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0; padding: 0;
            font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
            background: transparent; color: #0f172a;
            user-select: none; overflow: hidden;
        }}
        .player-card {{
            position: relative;
            border: 1.5px solid #64748b;
            border-radius: 10px;
            background: #ffffff;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
        }}
        .player-card:fullscreen {{
            width: 100vw;
            height: 100vh;
            border-radius: 0;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            background: #ffffff;
        }}
        .player-card:fullscreen canvas#cascadeCanvas {{
            max-height: calc(100vh - 230px) !important;   /* 2-row top bar + info box/time ruler + 84px branching bar + margins */
            max-width: 99vw !important;
        }}
        /* Fixed-height branching-ratio bar in fullscreen, so hovering levels with / without follow-up
           transitions can never make the whole simulation jump up or down. */
        .player-card:fullscreen .inspector-bar {{
            height: 84px;
            min-height: 84px;
            max-height: 84px;
            overflow-y: auto;
            flex: 0 0 auto;
            justify-content: flex-start;
        }}
        .top-bar {{
            display: flex; flex-direction: column; align-items: stretch;
            background: #e2e8f0; border-bottom: 1px solid #94a3b8;
            padding: 5px 12px; gap: 6px;
        }}
        /* Row 1: buttons spread over the full width; only the related pairs stay together */
        .btn-group {{
            display: flex; align-items: center; justify-content: space-between;
            width: 100%; gap: 6px; flex-wrap: nowrap;
            direction: ltr;   /* all buttons of the simulator keep the same places in Hebrew and English */
        }}
        .btn-pair {{ display: flex; align-items: center; gap: 4px; }}
        button {{
            font-family: 'Calibri', 'Segoe UI', sans-serif;
            background: #0f4c81; color: #ffffff; border: 1px solid #0c3b66;
            border-radius: 6px; padding: 4px 9px; font-size: calc(13px * {ui_labels['font_scale']});
            font-weight: 600; cursor: pointer; transition: all 0.15s;
            position: relative;
        }}
        button:hover {{ background: #1e3a8a; }}
        button.play-active {{
            background: #15803d; border-color: #166534;
        }}
        button.secondary {{
            background: #ffffff; color: #1e293b; border: 1px solid #64748b;
        }}
        button.secondary:hover {{ background: #f1f5f9; }}

        /* Localized Keyboard Space tooltip badge on Play button hover */
        #btnPlay::after {{
            content: "{ui_labels['space_tooltip']}";
            position: absolute;
            bottom: -27px;
            left: 50%;
            transform: translateX(-50%);
            background: #0f172a;
            color: #ffffff;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 5px;
            white-space: nowrap;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.15s ease;
            z-index: 100;
            box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        }}
        #btnPlay:hover::after {{
            opacity: 1;
        }}

        /* Custom Styled Mouse-Wheel Tooltip for Zoom [+] and [-] Buttons */
        .zoom-btn-wrap {{
            position: relative;
            display: inline-flex;
            align-items: center;
        }}
        .zoom-wheel-tooltip {{
            position: absolute;
            bottom: -34px;
            left: 50%;
            transform: translateX(-50%);
            background: #0f172a;
            color: #ffffff;
            font-size: 11.5px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 6px;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 6px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.15s ease;
            z-index: 120;
            box-shadow: 0 3px 8px rgba(15, 23, 42, 0.35);
            border: 1px solid #334155;
        }}
        .zoom-btn-wrap:hover .zoom-wheel-tooltip {{
            opacity: 1;
        }}
        /* Speed control: its tooltip opens ABOVE so it never covers the simulation below */
        #speedControlBox .zoom-wheel-tooltip {{
            bottom: auto;
            top: -34px;
        }}

        /* the one information box between the simulation and the time ruler: the step of the current muon,
           the muon counter and the photon counter, spread evenly over its width */
        .status-readout {{
            display: flex; justify-content: center; align-items: center; column-gap: 28px; row-gap: 2px; flex-wrap: wrap;
            width: 100%; min-height: calc(13.5px * {ui_labels['font_scale']} * 1.3 + 8px);
            background: #ffffff; border: 1px solid #94a3b8;
            border-radius: 6px; padding: 3px 10px; font-size: calc(13.5px * {ui_labels['font_scale']});
            text-align: center; white-space: nowrap; direction: ltr;
        }}
        /* the step text takes the free room; the two counters have a fixed width, so they never jump while the digits change */
        .status-readout sup, .status-readout sub {{ line-height: 0; }}   /* sub-/superscripts must not make the box taller */
        #statusStepText {{ flex: 1 1 auto; text-align: center; }}
        #timelineRightLabel {{ flex: 0 0 auto; min-width: 11em; text-align: center; }}
        #photonCountLabel {{ flex: 0 0 auto; min-width: 9.5em; text-align: center; }}
        .controls-right {{
            display: flex; align-items: center; justify-content: space-around; gap: 28px;
            flex: 1 1 auto;
            font-size: calc(13px * {ui_labels['font_scale']});
            flex-wrap: wrap;
            direction: ltr;   /* same order / same side in Hebrew and English (each label keeps its own text direction) */
        }}
        .canvas-stage {{
            width: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #ffffff;
        }}
        canvas#cascadeCanvas {{
            display: block;
            width: 100%;
            max-width: 1520px;
            aspect-ratio: 1600 / 505;
            height: auto;
            max-height: 400px;
            object-fit: contain;
            background: #ffffff;
            cursor: grab;
        }}
        canvas#cascadeCanvas.dragging {{
            cursor: grabbing;
        }}
        .timeline-wrapper {{
            background: #f1f5f9; border-top: 1px solid #cbd5e1;
            padding: 4px 14px 6px 14px;
        }}
        .timeline-header {{
            display: flex; justify-content: space-between; align-items: center;
            font-size: calc(12.5px * {ui_labels['font_scale']}); margin-bottom: 3px; color: #1e293b;
        }}
        .timeline-track-box {{
            position: relative; height: 25px; width: 100%;
            background: #e2e8f0; border: 1.5px solid #475569;
            border-radius: 6px; overflow: hidden; cursor: ew-resize;
            touch-action: none;
        }}
        .muon-segments-row {{
            display: flex; width: 100%; height: 100%; position: absolute; top: 0; left: 0;
            pointer-events: none;
        }}
        .muon-seg {{
            height: 100%; border-right: 1.5px solid #64748b;
            display: flex; align-items: center; justify-content: center;
            font-size: 11.5px; font-weight: 600;
            color: #1e293b; position: relative; overflow: hidden;
        }}
        .muon-seg {{ box-sizing: border-box; }}
        .muon-seg:nth-child(even) {{ background: rgba(255, 255, 255, 0.48); }}
        .muon-seg:last-child {{ border-right: none; }}
        .ruler-tick {{
            position: absolute; top: 0; bottom: 0; width: 1.5px; background: #64748b;
        }}
        .ruler-label {{
            position: absolute; top: 50%; transform: translate(4px, -50%);
            font-size: 11.5px; font-weight: 600; color: #1e293b; white-space: nowrap;
        }}
        .step-tick {{
            position: absolute; bottom: 0; height: 7px; width: 1.5px;
            background: #64748b;
        }}
        .timeline-fill {{
            position: absolute; top: 0; left: 0; height: 100%;
            background: rgba(15, 76, 129, 0.22);
            border-right: 3px solid #c1121f;
            pointer-events: none;
        }}
        .timeline-playhead {{
            position: absolute; top: -2px; width: 12px; height: 29px;
            margin-left: -6px; background: #c1121f; border: 2px solid #ffffff;
            border-radius: 4px; box-shadow: 0 1px 5px rgba(0,0,0,0.35);
            pointer-events: none;
        }}
        .inspector-bar {{
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            justify-content: center;
            background: #f8fafc; border-top: 1px solid #e2e8f0;
            padding: 5px 14px; font-size: calc(12.5px * {ui_labels['font_scale']}); gap: 4px;
            /* a fixed, narrow bar: when a level has many decay channels the list scrolls inside it (the window never grows) */
            height: 96px; min-height: 96px; max-height: 96px; overflow-y: auto; flex: 0 0 auto;
            justify-content: flex-start; box-sizing: border-box;
        }}
        .inspector-options-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            width: 100%;
        }}
        .badge-candidate {{
            direction: ltr;
            display: inline-block; background: #ffffff; border: 1px solid #94a3b8;
            border-radius: 5px; padding: 2px 8px; cursor: pointer;
            transition: transform 0.1s ease, box-shadow 0.1s ease, border-color 0.1s ease;
        }}
        .badge-candidate:hover {{
            transform: scale(1.04);
            border-color: #0284c7;
            box-shadow: 0 2px 6px rgba(2, 132, 199, 0.25);
            background: #f0f9ff;
        }}
        .badge-chosen {{
            background: #fef2f2; border: 1.8px solid #c1121f; color: #991b1b; font-weight: 700;
        }}

        /* Modal Overlay for Radial Wavefunctions & Branching Tables */
        .wf-modal-backdrop {{
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 23, 42, 0.62);
            backdrop-filter: blur(2px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 500;
            padding: 18px;
        }}
        .wf-modal-box {{
            background: #ffffff;
            border: 2px solid #334155;
            border-radius: 12px;
            width: 95%;
            max-width: 1280px;
            height: 90%;
            display: flex;
            flex-direction: column;
            box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
            overflow: hidden;
        }}
        .wf-modal-header {{
            direction: ltr;   /* the close button stays top-right whatever the language; the texts keep their own direction */
            display: grid;
            grid-template-columns: 30px 1fr 30px;
            column-gap: 12px;
            align-items: center;
            background: #e2e8f0;
            border-bottom: 1.5px solid #94a3b8;
            padding: 8px 16px;
        }}
        .wf-modal-titles {{ grid-column: 2; grid-row: 1; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 4px; min-width: 0; }}
        .wf-close-circle-btn {{ grid-column: 3; grid-row: 1; }}
        .wf-modal-title {{
            font-size: 16px;
            font-weight: 700;
            color: #0f172a;
        }}
        .wf-modal-sub {{
            direction: ltr;   /* this line is identical in Hebrew and English */
            display: flex;
            justify-content: center;
            align-items: baseline;
            flex-wrap: wrap;
            gap: 6px clamp(36px, 6vw, 84px);
            font-size: 14px;
            font-weight: 600;
            color: #0f4c81;
        }}
        .wf-sub-item {{ white-space: nowrap; }}
        .wf-modal-sub .wf-ltr {{ direction: ltr; unicode-bidi: isolate; display: inline-block; }}
        .wf-close-circle-btn {{
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: #ffffff;
            color: #1e293b;
            border: 1.8px solid #475569;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0;   /* the X is drawn below, not typed */
            cursor: pointer;
            padding: 0;
            position: relative;
            overflow: hidden;
            transition: all 0.15s ease;
        }}
        /* two perpendicular strokes, each a full diameter of the circle (padding 0: the pseudo-elements span the inner circle) */
        .wf-close-circle-btn::before,
        .wf-close-circle-btn::after {{
            content: "";
            position: absolute;
            left: 0;
            top: 50%;
            width: 100%;
            height: 1.3px;
            margin-top: -0.65px;
            background: currentColor;
            transform: rotate(45deg);
        }}
        .wf-close-circle-btn::after {{ transform: rotate(-45deg); }}
        .wf-close-circle-btn:hover {{
            background: #c1121f;
            color: #ffffff;
            border-color: #991b1b;
            transform: scale(1.08);
        }}
        .wf-modal-body {{
            display: grid;
            grid-template-columns: 1.25fr 1fr;
            gap: 16px;
            padding: 14px 18px;
            height: calc(100% - 48px);
            overflow-y: auto;
            direction: ltr;   /* the graphs stay on the left in Hebrew as well; the table text keeps its own direction */
        }}
        .wf-table {{
            direction: ltr;   /* same column order in Hebrew and English */
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-top: 6px;
        }}
        .wf-table th {{
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            padding: 6px 8px;
            text-align: center;
            vertical-align: middle;
            font-weight: 700;
        }}
        .wf-table td {{
            border: 1px solid #cbd5e1;
            padding: 5px 8px;
            height: 30px;
            text-align: center;
            vertical-align: middle;
        }}
        .wf-table sup {{ font-size: 0.72em; line-height: 0; vertical-align: super; }}
        .wf-num {{ direction: ltr; unicode-bidi: isolate; display: inline-block; }}
        .wf-table tr.active-row {{
            background: #fef2f2;
            font-weight: 700;
            color: #991b1b;
        }}
    </style>
    </head>
    <body>
    <div class="player-card" id="playerCard">
        <div class="top-bar">
            <div class="btn-group">
                <button id="btnPlay" onclick="togglePlay(); this.blur();" style="min-width: 86px;"></button>
                <div class="btn-pair">
                    <button class="secondary" onclick="stepJump(-1); this.blur();">{ui_labels['prev_trans']}</button>
                    <button class="secondary" onclick="stepJump(1); this.blur();">{ui_labels['next_trans']}</button>
                </div>
                <div class="btn-pair">
                    <button class="secondary" onclick="jumpToStart(); this.blur();">{ui_labels['start']}</button>
                    <button class="secondary" onclick="jumpToEnd(); this.blur();">{ui_labels['end']}</button>
                </div>

                <!-- Zoom Out (-), Smooth Reset (100%), and Zoom In (+): always "-" on the left and "+" on the right -->
                <div class="btn-pair" style="direction:ltr;">
                <div class="zoom-btn-wrap">
                    <button class="secondary" onclick="stepZoomButton(1/1.22); this.blur();" style="padding: 4px 9px; font-weight:800;">−</button>
                    <div class="zoom-wheel-tooltip">
                        <svg width="14" height="18" viewBox="0 0 14 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="1" y="1" width="12" height="18" rx="6" stroke="#38bdf8" stroke-width="1.8"/>
                            <rect x="6" y="4" width="2" height="4.5" rx="1" fill="#f59e0b"/>
                        </svg>
                        <span>{ui_labels['wheel_tooltip']}</span>
                    </div>
                </div>

                <button class="secondary" id="btnResetZoom" onclick="resetZoom100(); this.blur();">{ui_labels['reset_zoom']}</button>

                <div class="zoom-btn-wrap">
                    <button class="secondary" onclick="stepZoomButton(1.22); this.blur();" style="padding: 4px 9px; font-weight:800;">+</button>
                    <div class="zoom-wheel-tooltip">
                        <svg width="14" height="18" viewBox="0 0 14 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="1" y="1" width="12" height="18" rx="6" stroke="#38bdf8" stroke-width="1.8"/>
                            <rect x="6" y="4" width="2" height="4.5" rx="1" fill="#f59e0b"/>
                        </svg>
                        <span>{ui_labels['wheel_tooltip']}</span>
                    </div>
                </div>
                </div>

                <div class="zoom-btn-wrap">
                    <button class="secondary" id="btnFullscreen" onclick="toggleFullscreen(); this.blur();" style="padding: 4px 8px; display:inline-flex; align-items:center;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg></button>
                    <div class="zoom-wheel-tooltip" style="left:auto; right:0; transform:none;"><span id="fsTip"></span></div>
                </div>
            </div>

            <div class="controls-right">
                <label style="cursor:pointer; direction:{'rtl' if ui_labels['rtl'] else 'ltr'};">
                    <input type="checkbox" id="chkPhotonAnim" checked onchange="this.blur(); drawScene();">
                    {ui_labels['photon_anim']}
                </label>
                <label style="cursor:pointer; direction:{'rtl' if ui_labels['rtl'] else 'ltr'};">
                    <input type="checkbox" id="chkAllProbs" onchange="this.blur(); drawScene();">
                    {ui_labels['all_probs']}
                </label>
                <!-- Gaussian profile option is switched off for now; the hidden, unchecked input keeps the drawing code intact -->
                <input type="checkbox" id="chkGaussian" style="display:none;">

                <div id="speedControlBox" class="zoom-btn-wrap" style="display:flex; align-items:center; gap:4px; cursor:ns-resize;">
                    <span>{ui_labels['speed']}</span>
                    <input type="range" id="speedSlider" min="0" max="6" step="1" value="3" list="speedTicks" style="width:78px; vertical-align:middle; cursor:ew-resize;" oninput="updateDiscreteSpeed(this.value)">
                    <datalist id="speedTicks">
                        <option value="0"></option>
                        <option value="1"></option>
                        <option value="2"></option>
                        <option value="3"></option>
                        <option value="4"></option>
                        <option value="5"></option>
                        <option value="6"></option>
                    </datalist>
                    <span id="speedLabel" style="display:inline-block; width:38px; font-weight:700;">1×</span>
                    <div class="zoom-wheel-tooltip">
                        <svg width="14" height="18" viewBox="0 0 14 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="1" y="1" width="12" height="18" rx="6" stroke="#38bdf8" stroke-width="1.8"/>
                            <rect x="6" y="4" width="2" height="4.5" rx="1" fill="#f59e0b"/>
                        </svg>
                        <span>{ui_labels['wheel_tooltip']}</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="canvas-stage">
            <canvas id="cascadeCanvas" width="1600" height="505"></canvas>
        </div>

        <div class="timeline-wrapper" id="timelineWrapper">
            <div class="timeline-header">
                <div class="status-readout" id="statusReadout">
                    <span id="statusStepText"></span>
                    <span id="timelineRightLabel"></span>
                    <span id="photonCountLabel"></span>
                </div>
            </div>
            <div class="timeline-track-box" id="timelineTrack">
                <div class="muon-segments-row" id="muonSegmentsRow"></div>
                <div class="timeline-fill" id="timelineFill"></div>
                <div class="timeline-playhead" id="timelinePlayhead"></div>
            </div>
        </div>

        <div class="inspector-bar" id="inspectorBar"></div>

        <!-- Radial Wavefunctions & Branching Tables Modal Window -->
        <div class="wf-modal-backdrop" id="wfModalBackdrop" onclick="if(event.target===this) closeWavefunctionModal();">
            <div class="wf-modal-box">
                <div class="wf-modal-header">
                    <div class="wf-modal-titles" style="direction:{'rtl' if ui_labels['rtl'] else 'ltr'};">
                        <span class="wf-modal-title" id="wfModalTitle">{ui_labels['wf_modal_title']}</span>
                        <span class="wf-modal-sub" id="wfModalSub"></span>
                    </div>
                    <button class="wf-close-circle-btn" onclick="closeWavefunctionModal()" title="{ui_labels['wf_close']}" aria-label="{ui_labels['wf_close']}"></button>
                </div>
                <div class="wf-modal-body">
                    <div>
                        <canvas id="wfPlotCanvas" width="660" height="438" style="width:100%; height:auto; border:1px solid #cbd5e1; border-radius:8px; background:#ffffff;"></canvas>
                    </div>
                    <div id="wfTableContainer" style="overflow-y:auto;"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
    const sim = {json_data};
    const ui = {json_ui};
    const canvas = document.getElementById('cascadeCanvas');
    const ctx = canvas.getContext('2d');
    const btnPlay = document.getElementById('btnPlay');
    const btnResetZoom = document.getElementById('btnResetZoom');
    const btnFullscreen = document.getElementById('btnFullscreen');
    const inspectorBarEl = document.getElementById('inspectorBar');
    if (ui.rtl) {{ inspectorBarEl.style.direction = 'rtl'; inspectorBarEl.style.textAlign = 'right'; }}
    const speedSliderEl = document.getElementById('speedSlider');
    const speedControlBoxEl = document.getElementById('speedControlBox');

    window.addEventListener('pointerdown', () => {{
        try {{
            if (window.parent && window.parent._closeOpenColorPopovers) {{
                window.parent._closeOpenColorPopovers(null);
            }}
        }} catch (err) {{}}
    }}, {{ capture: true }});

    inspectorBarEl.addEventListener('pointerdown', (e) => {{
        const badge = e.target.closest('.badge-candidate[data-from][data-to]');
        if (badge) {{
            e.preventDefault();
            e.stopPropagation();
            openWavefunctionModal(badge.getAttribute('data-from'), badge.getAttribute('data-to'));
        }}
    }});

    const SPEED_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10];
    if (sim.num_muons >= 500) SPEED_STEPS.push(30);   // extra fast speed only for large simulations
    speedSliderEl.max = String(SPEED_STEPS.length - 1);
    const speedTicksEl = document.getElementById('speedTicks');
    if (speedTicksEl) {{
        speedTicksEl.innerHTML = '';
        SPEED_STEPS.forEach((_, i) => {{ const o = document.createElement('option'); o.value = String(i); speedTicksEl.appendChild(o); }});
    }}
    const totalMuons = Math.max(1, sim.trajectories.length);
    let tau = 0.0;
    let prefixCache = null;
    let doneCache = null;
    let isPlaying = true;
    let speed = 1.0;
    let lastTime = performance.now();
    let isDraggingTimeline = false;
    let hoveredLevel = null;
    let hoveredBadge = null;
    let lastBottomBarSignature = '';

    let zoomL = 1.0, panXL = 0.0, panYL = 0.0;
    let zoomR = 1.0, panXR = 0.0, panYR = 0.0;
    let isResettingZoomSmooth = false;
    let isPanningCanvas = false;
    let panMovedDist = 0.0;
    let panSide = 'L';
    let panStartMouseX = 0.0, panStartMouseY = 0.0;

    function updateDiscreteSpeed(idxStr) {{
        const idx = Math.max(0, Math.min(SPEED_STEPS.length - 1, parseInt(idxStr, 10)));
        speedSliderEl.value = idx;
        speed = SPEED_STEPS[idx];
        document.getElementById('speedLabel').innerText = speed + '×';
    }}

    // Mouse-Wheel control over Speed Slider!
    speedControlBoxEl.addEventListener('wheel', (e) => {{
        e.preventDefault();
        e.stopPropagation();
        const dir = e.deltaY < 0 ? 1 : -1;
        const parsedIdx = parseInt(speedSliderEl.value, 10);
        const currIdx = Number.isNaN(parsedIdx) ? 3 : parsedIdx;
        updateDiscreteSpeed(currIdx + dir);
    }}, {{ passive: false }});

    // Exclusive Global Spacebar Handler
    function onGlobalSpaceKeyDown(e) {{
        if (e.code === 'Space' || e.key === ' ') {{
            const tag = (e.target && e.target.tagName) ? e.target.tagName.toUpperCase() : '';
            if (tag === 'INPUT' && (e.target.type === 'text' || e.target.type === 'number')) return;
            if (tag === 'TEXTAREA') return;
            e.preventDefault();
            e.stopPropagation();
            if (e.target && typeof e.target.blur === 'function') {{
                e.target.blur();
            }}
            togglePlay();
        }} else if (e.key === 'Escape') {{
            closeWavefunctionModal();
        }}
    }}
    window.addEventListener('keydown', onGlobalSpaceKeyDown, {{ capture: true }});
    try {{
        if (window.parent && window.parent !== window) {{
            if (window.parent._muonSpaceHandler) {{
                window.parent.removeEventListener('keydown', window.parent._muonSpaceHandler, {{ capture: true }});
            }}
            window.parent._muonSpaceHandler = onGlobalSpaceKeyDown;
            window.parent.addEventListener('keydown', onGlobalSpaceKeyDown, {{ capture: true }});
        }}
    }} catch (err) {{}}

    // the button always reads "100%" (it is the "back to 100%" button, not a zoom read-out)
    function updateZoomButtonLabel() {{
        if (btnResetZoom.innerText !== ui.reset_zoom) btnResetZoom.innerText = ui.reset_zoom;
    }}

    function resetZoom100() {{
        zoomTgtL = null; zoomTgtR = null;
        isResettingZoomSmooth = true;
        lastTime = performance.now();
    }}

    // + / - : the zoom glides to its target (repeated clicks add up), see easeZoomSteps() in the render loop
    let zoomTgtL = null, zoomTgtR = null;
    function stepZoomButton(factor) {{
        isResettingZoomSmooth = false;
        zoomTgtL = Math.min(7.0, Math.max(1.0, (zoomTgtL === null ? zoomL : zoomTgtL) * factor));
        zoomTgtR = Math.min(7.0, Math.max(1.0, (zoomTgtR === null ? zoomR : zoomTgtR) * factor));
    }}
    function easeZoomSteps(dt) {{
        if (zoomTgtL === null && zoomTgtR === null) return;
        const k = 1.0 - Math.exp(-16.0 * dt);
        const cy = canvas.height * 0.5;
        const glide = (z, px, py, tgt, cx) => {{
            let nz = z * Math.pow(tgt / z, k);
            if (Math.abs(nz - tgt) < 0.002) nz = tgt;
            if (nz === 1.0) return [1.0, 0.0, 0.0, true];
            return [nz, cx - (cx - px) * (nz / z), cy - (cy - py) * (nz / z), nz === tgt];
        }};
        if (zoomTgtL !== null) {{
            const r = glide(zoomL, panXL, panYL, zoomTgtL, 475);
            zoomL = r[0]; panXL = r[1]; panYL = r[2];
            if (r[3]) zoomTgtL = null;
        }}
        if (zoomTgtR !== null) {{
            const r = glide(zoomR, panXR, panYR, zoomTgtR, 1280);
            zoomR = r[0]; panXR = r[1]; panYR = r[2];
            if (r[3]) zoomTgtR = null;
        }}
        updateZoomButtonLabel();
    }}

    function toggleFullscreen() {{
        const card = document.getElementById('playerCard');
        if (!document.fullscreenElement) {{
            if (card.requestFullscreen) card.requestFullscreen();
        }} else {{
            if (document.exitFullscreen) document.exitFullscreen();
        }}
    }}

    // icon only: corners pointing outwards = enter full screen, inwards = exit; the words are in the tooltip
    const FS_ENTER_SVG = btnFullscreen.innerHTML;
    const FS_EXIT_SVG = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
    const fsWords = (t) => String(t).split(' ').slice(1).join(' ') || String(t);
    function syncFullscreenUI() {{
        const on = !!document.fullscreenElement;
        btnFullscreen.innerHTML = on ? FS_EXIT_SVG : FS_ENTER_SVG;
        document.getElementById('fsTip').textContent = on ? fsWords(ui.exit_fullscreen) : fsWords(ui.fullscreen);
    }}
    document.addEventListener('fullscreenchange', syncFullscreenUI);
    syncFullscreenUI();

    canvas.addEventListener('wheel', (e) => {{
        e.preventDefault();
        zoomTgtL = null; zoomTgtR = null;
        isResettingZoomSmooth = false;
        const rect = canvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
        const my = (e.clientY - rect.top) * (canvas.height / rect.height);
        const factor = e.deltaY < 0 ? 1.18 : (1.0 / 1.18);

        if (mx < 956) {{
            const newZ = Math.min(7.0, Math.max(1.0, zoomL * factor));
            if (newZ === 1.0) {{
                zoomL = 1.0; panXL = 0.0; panYL = 0.0;
            }} else {{
                panXL = mx - (mx - panXL) * (newZ / zoomL);
                panYL = my - (my - panYL) * (newZ / zoomL);
                zoomL = newZ;
            }}
        }} else {{
            const newZ = Math.min(7.0, Math.max(1.0, zoomR * factor));
            if (newZ === 1.0) {{
                zoomR = 1.0; panXR = 0.0; panYR = 0.0;
            }} else {{
                panXR = mx - (mx - panXR) * (newZ / zoomR);
                panYR = my - (my - panYR) * (newZ / zoomR);
                zoomR = newZ;
            }}
        }}
        updateZoomButtonLabel();
        drawScene();
    }}, {{ passive: false }});

    function isBadgeVisibleNow(b, st) {{
        const showAllProbs = document.getElementById('chkAllProbs').checked;
        const activeKey = st.activeStep ? `${{st.activeStep.from}}->${{st.activeStep.to}}` : '';
        const focusFrom = hoveredLevel || (st.activeStep ? st.activeStep.from : '');
        const isCurrentActive = (b.key === activeKey);
        const isOutgoingFromCurr = (b.from === focusFrom);
        return showAllProbs || isOutgoingFromCurr || isCurrentActive;
    }}

    canvas.addEventListener('pointerdown', (e) => {{
        isResettingZoomSmooth = false;
        const rect = canvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
        const my = (e.clientY - rect.top) * (canvas.height / rect.height);
        isPanningCanvas = true;
        panMovedDist = 0.0;
        panSide = (mx < 956) ? 'L' : 'R';
        panStartMouseX = mx;
        panStartMouseY = my;
        canvas.classList.add('dragging');
        canvas.setPointerCapture(e.pointerId);
    }});

    canvas.addEventListener('pointermove', (e) => {{
        const rect = canvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
        const my = (e.clientY - rect.top) * (canvas.height / rect.height);

        if (isPanningCanvas) {{
            const dx = mx - panStartMouseX;
            const dy = my - panStartMouseY;
            panMovedDist += Math.hypot(dx, dy);
            panStartMouseX = mx;
            panStartMouseY = my;
            if (panSide === 'L') {{
                panXL += dx;
                panYL += dy;
            }} else {{
                panXR += dx;
                panYR += dy;
            }}
            drawScene();
            return;
        }}

        const worldX = (mx - panXL) / zoomL;
        const worldY = (my - panYL) / zoomL;
        const st = decodeTimelineState(tau);

        let foundBadge = null;
        if (mx < 956) {{
            for (const b of permanentEdges) {{
                if (!isBadgeVisibleNow(b, st)) continue;
                if (Math.abs(worldX - b.x) <= b.w * 0.5 && Math.abs(worldY - b.y) <= b.h * 0.5) {{
                    foundBadge = b;
                    break;
                }}
            }}
        }}
        hoveredBadge = foundBadge;
        canvas.style.cursor = foundBadge ? 'pointer' : 'grab';

        let found = null;
        for (const lvl of sim.levels) {{
            const pt = levelToScreen(lvl.x_pos, lvl.n);
            if (Math.abs(worldX - pt.x) <= 26 && Math.abs(worldY - pt.y) <= 16) {{
                found = lvl.name;
                break;
            }}
        }}
        if (found !== hoveredLevel) {{
            hoveredLevel = found;
            if (!isPlaying) drawScene();
        }}
    }});

    window.addEventListener('pointerup', (e) => {{
        if (isPanningCanvas) {{
            isPanningCanvas = false;
            canvas.classList.remove('dragging');
            try {{ canvas.releasePointerCapture(e.pointerId); }} catch (err) {{}}

            if (panMovedDist < 6.0 && hoveredBadge) {{
                openWavefunctionModal(hoveredBadge.from, hoveredBadge.to);
            }}
        }}
    }});

    // =========================================================================
    // RADIAL WAVEFUNCTIONS & BRANCHING TABLES MODAL RENDERER
    // =========================================================================
    // The radial wavefunctions come from MUDIRAC itself (output: 2 state files, resampled on a uniform r grid by the
    // server): P(r) and Q(r) are the large / small Dirac components. Nothing is computed or approximated here.
    // Hebrew texts on the canvas: a right-to-left paragraph with the English / numeric parts kept as left-to-right islands
    function wfText(s) {{ return ui.rtl ? '⁧' + s + '⁩' : s; }}
    function wfLtr(s) {{ return ui.rtl ? '⁦' + s + '⁩' : s; }}
    function mudiracProfile(lvlName) {{
        const w = (sim.wavefunctions || {{}})[lvlName];
        if (!w || !w.r_fm || w.r_fm.length < 2) return null;
        let maxP = 1e-30, maxD = 1e-30;
        const dens = [];
        for (let i = 0; i < w.P.length; i++) {{
            const d = w.P[i] * w.P[i] + w.Q[i] * w.Q[i];
            dens.push(d);
            if (Math.abs(w.P[i]) > maxP) maxP = Math.abs(w.P[i]);
            if (d > maxD) maxD = d;
        }}
        return {{
            r: w.r_fm,
            rMax: w.r_fm[w.r_fm.length - 1],
            P: w.P.map(v => v / maxP),
            Q: w.Q.map(v => v / maxP),
            dens: dens.map(v => v / maxD)
        }};
    }}
    // a number written out as  m · 10^n  (exponent as a superscript) instead of the "e" notation
    function fmtSci(v) {{
        if (!v) return '—';
        const parts = v.toExponential(3).split('e');
        const ex = parseInt(parts[1], 10);
        if (ex === 0) return parts[0];
        return `${{parts[0]}} · 10<sup>${{ex < 0 ? '−' : ''}}${{Math.abs(ex)}}</sup>`;
    }}
    let wfCurrent = null;   // the transition shown in the analysis window (null = window closed)
    function openWavefunctionModal(fromState, toState) {{
        isPlaying = false;
        syncPlayButtonUI();

        const modal = document.getElementById('wfModalBackdrop');
        modal.style.display = 'flex';

        wfCurrent = {{ from: fromState, to: toState }};
        simSave();
        document.querySelector('.wf-modal-box').style.direction = ui.rtl ? 'rtl' : 'ltr';
        document.getElementById('wfTableContainer').style.direction = ui.rtl ? 'rtl' : 'ltr';
        document.getElementById('wfModalTitle').textContent = ui.wf_modal_title;
        const _trList = sim.state_transitions[fromState] || [];
        const _trItem = _trList.find(t => t.target === toState);
        // three items spread over the width of the window: no separator character is needed between them
        let _subHtml = `<span class="wf-sub-item"><span class="wf-ltr">${{sim.element_label || sim.element}}: ${{fmtStateHTML(fromState)}} → ${{fmtStateHTML(toState)}}</span></span>`;
        if (_trItem) {{
            _subHtml += `<span class="wf-sub-item">ΔE = <span class="wf-ltr">${{_trItem.energy.toFixed(3)}} keV</span></span>`;
            _subHtml += `<span class="wf-sub-item">Probability: <span class="wf-ltr">${{_trItem.prob.toFixed(2)}}%</span></span>`;
        }}
        document.getElementById('wfModalSub').innerHTML = _subHtml;

        const wfCanvas = document.getElementById('wfPlotCanvas');
        const wctx = wfCanvas.getContext('2d');
        wctx.clearRect(0, 0, wfCanvas.width, wfCanvas.height);

        const profFrom = mudiracProfile(fromState);
        const profTo = mudiracProfile(toState);

        function drawWaveSubPlot(yTop, yBottom, titleTxt, prof, colorMain, colorSub, colorFill) {{
            const xLeft = 58, xRight = wfCanvas.width - 24;
            const plotW = xRight - xLeft;
            const plotH = yBottom - yTop;
            const yZero = yTop + plotH * 0.55;

            wctx.fillStyle = '#0f172a';
            wctx.font = 'bold 13.5px Calibri, sans-serif';
            wctx.direction = ui.rtl ? 'rtl' : 'ltr';          // Hebrew: the text runs from the right edge
            wctx.textAlign = ui.rtl ? 'right' : 'left';
            wctx.fillText(titleTxt + (prof ? `   ${{wfLtr('[r: 0 → ' + prof.rMax.toFixed(prof.rMax < 100 ? 1 : 0) + ' fm]')}}` : ''), ui.rtl ? xRight : xLeft, yTop - 6);

            wctx.strokeStyle = '#cbd5e1';
            wctx.lineWidth = 1;
            wctx.strokeRect(xLeft, yTop, plotW, plotH);

            if (!prof) {{
                wctx.fillStyle = '#64748b';
                wctx.font = '13px Calibri, sans-serif';
                wctx.textAlign = 'center';
                wctx.fillText(ui.wf_unavailable, xLeft + plotW / 2, yTop + plotH / 2);
                return;
            }}
            const numPts = prof.r.length - 1;

            // the r axis (zero line): solid dark grey, so it is not mistaken for the dashed Q(r) curve
            wctx.beginPath();
            wctx.moveTo(xLeft, yZero);
            wctx.lineTo(xRight, yZero);
            wctx.strokeStyle = '#475569';
            wctx.lineWidth = 1.4;
            wctx.stroke();

            wctx.beginPath();
            wctx.moveTo(xLeft, yBottom);
            for (let i = 0; i <= numPts; i++) {{
                const px = xLeft + (prof.r[i] / prof.rMax) * plotW;
                const py = yBottom - prof.dens[i] * (plotH * 0.85);
                wctx.lineTo(px, py);
            }}
            wctx.lineTo(xRight, yBottom);
            wctx.closePath();
            wctx.fillStyle = colorFill;
            wctx.fill();

            wctx.beginPath();
            for (let i = 0; i <= numPts; i++) {{
                const px = xLeft + (prof.r[i] / prof.rMax) * plotW;
                const py = yZero - prof.P[i] * (plotH * 0.40);
                if (i === 0) wctx.moveTo(px, py);
                else wctx.lineTo(px, py);
            }}
            wctx.strokeStyle = colorMain;
            wctx.lineWidth = 2.4;
            wctx.stroke();

            wctx.beginPath();
            for (let i = 0; i <= numPts; i++) {{
                const px = xLeft + (prof.r[i] / prof.rMax) * plotW;
                const py = yZero - prof.Q[i] * (plotH * 0.40);
                if (i === 0) wctx.moveTo(px, py);
                else wctx.lineTo(px, py);
            }}
            wctx.setLineDash([5, 3]);
            wctx.strokeStyle = colorSub;
            wctx.lineWidth = 1.8;
            wctx.stroke();
            wctx.setLineDash([]);
        }}

        drawWaveSubPlot(28, 192, wfText(`${{ui.wf_initial}}: ${{wfLtr(fromState.replace('_', ' '))}}   (${{ui.wf_legend}})`), profFrom, '#0f4c81', '#0284c7', 'rgba(2, 132, 199, 0.14)');
        drawWaveSubPlot(226, 388, wfText(`${{ui.wf_target}}: ${{wfLtr(toState.replace('_', ' '))}}   (${{ui.wf_legend}})`), profTo, '#c1121f', '#d97706', 'rgba(193, 18, 31, 0.13)');   // the target state is red, like its row in the table

        wctx.fillStyle = '#334155';
        wctx.font = 'bold 12.5px Calibri, sans-serif';
        wctx.textAlign = 'center';
        wctx.direction = ui.rtl ? 'rtl' : 'ltr';
        wctx.fillText(wfText(`${{ui.wf_axis}} ${{wfLtr('[fm]')}}  (${{ui.wf_nuc_model}}: ${{wfLtr(sim.nuclear_model)}};  ${{ui.wf_approx}})` + (sim.radius_fallback ? `  ${{ui.wf_radius_fb}}` : '')), wfCanvas.width * 0.52, 410);
        wctx.font = '11.5px Calibri, sans-serif';
        wctx.fillStyle = '#64748b';
        wctx.fillText(wfText(ui.wf_norm), wfCanvas.width * 0.52, 427);

        const list = sim.state_transitions[fromState] || [];
        let tblHTML = `<div style="font-size:14.5px; font-weight:700; color:#0f4c81; margin-bottom:6px;">${{ui.wf_table_title}} <span class="wf-ltr" style="direction:ltr; unicode-bidi:isolate; display:inline-block;">${{fmtStateHTML(fromState)}}</span>:</div>`;
        tblHTML += `<table class="wf-table"><thead><tr><th>${{ui.wf_th_target}}</th><th>${{ui.wf_th_energy}}</th><th>${{ui.wf_th_rate}}</th><th>${{ui.wf_th_prob}}</th></tr></thead><tbody>`;
        for (const item of list) {{
            const isClicked = (item.target === toState);
            const rowCls = isClicked ? ' class="active-row"' : '';
            tblHTML += `<tr${{rowCls}}><td><span class="wf-num">${{fmtStateHTML(item.target)}}</span></td><td><span class="wf-num">${{item.energy.toFixed(3)}}</span></td><td><span class="wf-num">${{fmtSci(item.rate)}}</span></td><td><span class="wf-num">${{item.prob.toFixed(2)}}%</span></td></tr>`;
        }}
        tblHTML += `</tbody></table>`;
        document.getElementById('wfTableContainer').innerHTML = tblHTML;
    }}

    function closeWavefunctionModal() {{
        wfCurrent = null;
        simSave();
        document.getElementById('wfModalBackdrop').style.display = 'none';
    }}

    function syncPlayButtonUI() {{
        if (isPlaying) {{
            btnPlay.innerText = ui.pause;
            btnPlay.classList.remove('play-active');
        }} else {{
            btnPlay.innerText = (tau >= totalMuons - 1e-4) ? ui.replay : ui.play;
            btnPlay.classList.add('play-active');
        }}
    }}

    function fmtStateHTML(name) {{
        if (!name) return '';
        const parts = name.split('_');
        if (parts.length === 2) {{
            return `${{parts[0]}}<sub>${{parts[1]}}</sub>`;
        }}
        return name;
    }}

    function drawSubscriptState(ctx, levelName, x, y, fontSize, color, bold=false) {{
        ctx.save();
        ctx.fillStyle = color;
        const parts = levelName.split('_');
        const orb = parts[0];
        const sub = parts[1] || '';
        const weight = bold ? 'bold ' : '600 ';

        ctx.font = `${{weight}}${{fontSize}}px Calibri, "Segoe UI", sans-serif`;
        const wOrb = ctx.measureText(orb).width;
        const subSize = Math.round(fontSize * 0.78);
        ctx.font = `${{weight}}${{subSize}}px Calibri, "Segoe UI", sans-serif`;
        const wSub = ctx.measureText(sub).width;

        const totalW = wOrb + wSub;
        const startX = x - totalW / 2;

        ctx.textAlign = 'left';
        ctx.font = `${{weight}}${{fontSize}}px Calibri, "Segoe UI", sans-serif`;
        ctx.fillText(orb, startX, y);

        if (sub) {{
            ctx.font = `${{weight}}${{subSize}}px Calibri, "Segoe UI", sans-serif`;
            ctx.fillText(sub, startX + wOrb + 0.5, y + fontSize * 0.28);
        }}
        ctx.restore();
    }}

    const segRow = document.getElementById('muonSegmentsRow');
    // Adaptive ruler: per-muon cells (with step ticks) only while they stay readable;
    // for large N a few "nice" labelled marks are drawn, so no clipped/garbled cells appear.
    (function buildTimelineRuler() {{
        if (totalMuons <= 60) {{
            for (let m = 0; m < totalMuons; m++) {{
                const seg = document.createElement('div');
                seg.className = 'muon-seg';
                seg.style.flex = '1 1 0';
                seg.style.minWidth = '0';
                if (totalMuons <= 30 || (m + 1) % 5 === 0) {{
                    seg.innerHTML = 'μ<sub>' + (m + 1).toLocaleString('en-US') + '</sub>';
                }}
                const numSteps = sim.trajectories[m].length;
                for (let step = 1; step < numSteps; step++) {{
                    const tick = document.createElement('div');
                    tick.className = 'step-tick';
                    tick.style.left = ((step / numSteps) * 100) + '%';
                    seg.appendChild(tick);
                }}
                segRow.appendChild(seg);
            }}
        }} else {{
            const rough = totalMuons / 10;
            const pow = Math.pow(10, Math.floor(Math.log10(rough)));
            let stepM = pow;
            for (const k of [1, 2, 5, 10]) {{
                stepM = k * pow;
                if (stepM >= rough) break;
            }}
            for (let m = stepM; m < totalMuons; m += stepM) {{
                const pos = (m / totalMuons) * 100;
                const line = document.createElement('div');
                line.className = 'ruler-tick';
                line.style.left = pos + '%';
                segRow.appendChild(line);
                const lab = document.createElement('div');
                lab.className = 'ruler-label';
                lab.style.left = pos + '%';
                lab.innerHTML = 'μ<sub>' + m.toLocaleString('en-US') + '</sub>';
                segRow.appendChild(lab);
            }}
        }}
    }})();

    const trackEl = document.getElementById('timelineTrack');
    const timelineWrapperEl = document.getElementById('timelineWrapper');

    function scrubToClientX(clientX) {{
        const rect = trackEl.getBoundingClientRect();
        const frac = Math.max(0.0, Math.min(1.0, (clientX - rect.left) / rect.width));
        tau = frac * totalMuons;
        drawScene();
    }}

    trackEl.addEventListener('pointerdown', (e) => {{
        isDraggingTimeline = true;
        isPlaying = false;
        syncPlayButtonUI();
        trackEl.setPointerCapture(e.pointerId);
        scrubToClientX(e.clientX);
    }});
    trackEl.addEventListener('pointermove', (e) => {{
        if (isDraggingTimeline) {{
            scrubToClientX(e.clientX);
        }}
    }});
    window.addEventListener('pointerup', (e) => {{
        if (isDraggingTimeline) {{
            isDraggingTimeline = false;
            try {{ trackEl.releasePointerCapture(e.pointerId); }} catch (err) {{}}
        }}
    }});

    // Mouse-Wheel scrubbing directly over the Master Timeline Bar!
    timelineWrapperEl.addEventListener('wheel', (e) => {{
        e.preventDefault();
        e.stopPropagation();
        isPlaying = false;
        syncPlayButtonUI();
        const m = Math.min(totalMuons - 1, Math.max(0, Math.floor(tau)));
        const K = Math.max(1, sim.trajectories[m].length);
        const dir = e.deltaY < 0 ? 1 : -1;
        tau = Math.max(0.0, Math.min(totalMuons, tau + (dir * 0.14) / K));
        drawScene();
    }}, {{ passive: false }});

    function levelToScreen(x_pos, n_val) {{
        const padLeft = 102, padRight = 38, padTop = 56, padBottom = 46;
        const plotW = 940 - padLeft - padRight;
        const plotH = canvas.height - padTop - padBottom;

        const x = padLeft + ((x_pos + 0.42) / (sim.max_l + 0.9)) * plotW;
        const y = padTop + ((sim.max_n - n_val) / Math.max(1, sim.max_n - 1)) * plotH;
        return {{ x, y }};
    }}

    function energyToScreenX(energy) {{
        const specLeft = 1005, specRight = canvas.width - 35;
        const frac = Math.min(1.0, Math.max(0.0, energy / sim.max_energy));
        return specLeft + frac * (specRight - specLeft);
    }}

    function getCurveControlPoint(p1, p2, edgeIdx=0) {{
        const mx = (p1.x + p2.x) * 0.5;
        const my = (p1.y + p2.y) * 0.5;
        const dx = p2.x - p1.x;
        const dy = p2.y - p1.y;
        const sign = (dx >= 0 ? 1 : -1) * (edgeIdx % 2 === 0 ? 1 : -0.7);
        const bend = sign * Math.min(34, Math.abs(dy) * 0.13 + 8);
        return {{ cx: mx + bend, cy: my }};
    }}

    function pointOnQuadBezier(p1, cp, p2, t) {{
        const u = 1 - t;
        return {{
            x: u * u * p1.x + 2 * u * t * cp.cx + t * t * p2.x,
            y: u * u * p1.y + 2 * u * t * cp.cy + t * t * p2.y
        }};
    }}

    const permanentEdges = [];
    function precomputePermanentDiagramBadges() {{
        sim.all_edges.forEach((edge, idx) => {{
            const c1 = sim.level_map[edge.from];
            const c2 = sim.level_map[edge.to];
            if (!c1 || !c2) return;
            const p1 = levelToScreen(c1.x_pos, c1.n);
            const p2 = levelToScreen(c2.x_pos, c2.n);
            const cp = getCurveControlPoint(p1, p2, idx);

            const tAnchor = 0.30 + ((idx * 37) % 45) / 100.0;
            const anchor = pointOnQuadBezier(p1, cp, p2, tAnchor);

            const probTxt = `${{edge.prob.toFixed(1)}}%`;
            const energyTxt = `${{edge.energy.toFixed(1)}} keV`;

            ctx.font = 'bold 13px Calibri, "Segoe UI", sans-serif';
            const w1 = ctx.measureText(probTxt).width;
            ctx.font = 'normal 12px Calibri, "Segoe UI", sans-serif';
            const w2 = ctx.measureText(energyTxt).width;

            const bw = Math.max(w1, w2) + 16;
            const bh = 36;

            permanentEdges.push({{
                key: `${{edge.from}}->${{edge.to}}`,
                from: edge.from,
                to: edge.to,
                prob: edge.prob,
                energy: edge.energy,
                probTxt: probTxt,
                energyTxt: energyTxt,
                p1: p1,
                p2: p2,
                cp: cp,
                anchorX: anchor.x,
                anchorY: anchor.y,
                x: anchor.x,
                y: anchor.y,
                w: bw,
                h: bh
            }});
        }});

        const obstacles = sim.levels.map(lvl => {{
            const pt = levelToScreen(lvl.x_pos, lvl.n);
            return {{ x: pt.x, y: pt.y - 6, w: 66, h: 32 }};
        }});

        const padX = 7, padY = 6;
        for (let iter = 0; iter < 95; iter++) {{
            for (let i = 0; i < permanentEdges.length; i++) {{
                for (let j = i + 1; j < permanentEdges.length; j++) {{
                    const a = permanentEdges[i];
                    const b = permanentEdges[j];
                    const dx = b.x - a.x;
                    const dy = b.y - a.y;
                    const minW = (a.w + b.w) * 0.5 + padX;
                    const minH = (a.h + b.h) * 0.5 + padY;

                    if (Math.abs(dx) < minW && Math.abs(dy) < minH) {{
                        const overlapX = minW - Math.abs(dx);
                        const overlapY = minH - Math.abs(dy);
                        if (overlapY < overlapX * 1.3) {{
                            const pushY = (overlapY * 0.52) * (dy >= 0 ? 1 : -1);
                            a.y -= pushY;
                            b.y += pushY;
                        }} else {{
                            const pushX = (overlapX * 0.52) * (dx >= 0 ? 1 : -1);
                            a.x -= pushX;
                            b.x += pushX;
                        }}
                    }}
                }}
            }}

            for (let i = 0; i < permanentEdges.length; i++) {{
                const a = permanentEdges[i];
                for (const ob of obstacles) {{
                    const dx = a.x - ob.x;
                    const dy = a.y - ob.y;
                    const minW = (a.w + ob.w) * 0.5 + 4;
                    const minH = (a.h + ob.h) * 0.5 + 4;
                    if (Math.abs(dx) < minW && Math.abs(dy) < minH) {{
                        const pushY = (minH - Math.abs(dy)) * 0.6 * (dy >= 0 ? 1 : -1);
                        a.y += pushY;
                    }}
                }}
                a.x += (a.anchorX - a.x) * 0.04;
                a.y += (a.anchorY - a.y) * 0.04;
                a.x = Math.max(104 + a.w * 0.5, Math.min(925 - a.w * 0.5, a.x));
                a.y = Math.max(54 + a.h * 0.5, Math.min(canvas.height - 52 - a.h * 0.5, a.y));
            }}
        }}
    }}
    precomputePermanentDiagramBadges();

    function togglePlay() {{
        if (!isPlaying) {{
            if (tau >= totalMuons - 1e-4) {{
                tau = 0.0;
            }}
            isPlaying = true;
            lastTime = performance.now();
        }} else {{
            isPlaying = false;
        }}
        syncPlayButtonUI();
        drawScene();
    }}

    function jumpToStart() {{
        tau = 0.0;
        isPlaying = false;
        syncPlayButtonUI();
        drawScene();
    }}

    function jumpToEnd() {{
        tau = totalMuons;
        isPlaying = false;
        syncPlayButtonUI();
        drawScene();
    }}

    function stepJump(dir) {{
        isPlaying = false;
        syncPlayButtonUI();
        let m = Math.min(totalMuons - 1, Math.floor(tau));
        const K = Math.max(1, sim.trajectories[m].length);
        let s = Math.floor((tau - m) * K + 1e-4);
        s += dir;
        if (s >= K) {{
            m += 1;
            if (m >= totalMuons) {{ tau = totalMuons; drawScene(); return; }}
            tau = m + (0.45 / Math.max(1, sim.trajectories[m].length));
        }} else if (s < 0) {{
            m -= 1;
            if (m < 0) {{ tau = 0.0; drawScene(); return; }}
            const Kprev = Math.max(1, sim.trajectories[m].length);
            tau = m + ((Kprev - 0.55) / Kprev);
        }} else {{
            tau = m + ((s + 0.45) / K);
        }}
        drawScene();
    }}

    function easeInOutCubic(t) {{
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    }}

    function decodeTimelineState(tauVal) {{
        if (tauVal >= totalMuons) {{
            if (!doneCache) {{
                const cachedPhotons = [];
                const cachedKeys = new Set();
                for (let m = 0; m < totalMuons; m++) {{
                    for (const st of sim.trajectories[m]) {{
                        cachedPhotons.push({{ energy: st.energy }});
                        cachedKeys.add(`${{st.from}}->${{st.to}}`);
                    }}
                }}
                // where every muon really ended: 1s_1/2, or a state without a single-photon decay (2s_1/2)
                const cachedEnds = {{}};
                for (let m = 0; m < totalMuons; m++) {{
                    const tj = sim.trajectories[m];
                    const endState = tj.length ? tj[tj.length - 1].to : sim.start_level;
                    cachedEnds[endState] = (cachedEnds[endState] || 0) + 1;
                }}
                doneCache = {{ photons: cachedPhotons, keys: cachedKeys, ends: cachedEnds }};
            }}
            const allPhotons = doneCache.photons;
            const allTraversedKeys = doneCache.keys;
            const lastTraj = sim.trajectories[totalMuons - 1];
            return {{
                done: true,
                muonIdx: totalMuons - 1,
                stepIdx: Math.max(0, lastTraj.length - 1),
                activeStep: null,
                currentState: '1s_1/2',
                finalCounts: doneCache.ends,
                flightProg: 1.0,
                photonInFlight: false,
                photonFadeInProg: 1.0,
                highlightTargetCol: false,
                traversedKeys: allTraversedKeys,
                currentMuonKeys: new Set(lastTraj.map(x => `${{x.from}}->${{x.to}}`)),
                baseGroups: [],
                baseCount: 0,
                photons: allPhotons
            }};
        }}

        const m = Math.min(totalMuons - 1, Math.max(0, Math.floor(tauVal)));
        const traj = sim.trajectories[m];
        const K = Math.max(1, traj.length);
        const u = Math.max(0.0, Math.min(0.999999, tauVal - m));
        const sFloat = u * K;
        const s = Math.min(K - 1, Math.floor(sFloat));
        const localP = sFloat - s;

        let flightProg = 0.0;
        let photonInFlight = false;
        let photonFadeInProg = 0.0;
        let highlightTargetCol = false;
        let includeNewInBase = false;

        if (localP < 0.72) {{
            flightProg = localP / 0.72;
            photonInFlight = true;
            photonFadeInProg = 0.0;
            highlightTargetCol = true;
        }} else if (localP < 0.88) {{
            flightProg = 1.0;
            photonInFlight = false;
            photonFadeInProg = (localP - 0.72) / 0.16;
            highlightTargetCol = true;
        }} else {{
            flightProg = 1.0;
            photonInFlight = false;
            photonFadeInProg = 1.0;
            highlightTargetCol = false;
            includeNewInBase = true;
        }}

        const currentMuonKeys = new Set();
        // Incremental prefix cache: photons/keys of all fully finished muons (keeps large N smooth).
        if (!prefixCache || prefixCache.upTo > m) {{
            prefixCache = {{ upTo: 0, count: 0, groups: [], keys: new Set() }};
        }}
        const groupTol = Math.max(0.4, sim.max_energy * 0.004);
        while (prefixCache.upTo < m) {{
            for (const stp of sim.trajectories[prefixCache.upTo]) {{
                prefixCache.count++;
                let grp = null;
                for (const g of prefixCache.groups) {{
                    if (Math.abs(g.energy - stp.energy) < groupTol) {{ grp = g; break; }}
                }}
                if (grp) grp.count++; else prefixCache.groups.push({{ energy: stp.energy, count: 1 }});
                prefixCache.keys.add(`${{stp.from}}->${{stp.to}}`);
            }}
            prefixCache.upTo++;
        }}
        const traversedKeys = new Set(prefixCache.keys);
        const photons = [];
        for (let sPrev = 0; sPrev < s; sPrev++) {{
            photons.push({{ energy: traj[sPrev].energy }});
            traversedKeys.add(`${{traj[sPrev].from}}->${{traj[sPrev].to}}`);
            currentMuonKeys.add(`${{traj[sPrev].from}}->${{traj[sPrev].to}}`);
        }}
        if (includeNewInBase && traj[s]) {{
            photons.push({{ energy: traj[s].energy }});
            currentMuonKeys.add(`${{traj[s].from}}->${{traj[s].to}}`);
        }}

        return {{
            done: false,
            muonIdx: m,
            stepIdx: s,
            activeStep: traj[s] || null,
            currentState: traj[s]?.from || sim.start_level,
            localP: localP,
            flightProg: flightProg,
            photonInFlight: photonInFlight,
            photonFadeInProg: photonFadeInProg,
            includeNewInBase: includeNewInBase,
            highlightTargetCol: highlightTargetCol,
            traversedKeys: traversedKeys,
            currentMuonKeys: currentMuonKeys,
            baseGroups: prefixCache.groups,
            baseCount: prefixCache.count,
            photons: photons
        }};
    }}

    function computeSpectrumLayout(st) {{
        const specLeft = 1005, specRight = canvas.width - 35;
        const specTop = 54, specBottom = canvas.height - 46;
        const specW = specRight - specLeft;
        const specH = specBottom - specTop;
        const tol = Math.max(0.4, sim.max_energy * 0.004);

        let lineGroups = [];
        let displayedPhotonCount = st.baseCount + st.photons.length + (st.activeStep && !st.includeNewInBase && st.photonFadeInProg > 0 ? 1 : 0);

        if (st.done && sim.full_line_groups && sim.full_line_groups.length > 0) {{
            lineGroups = sim.full_line_groups.map(g => ({{ energy: g.energy, count: g.count, isTarget: false }}));
            displayedPhotonCount = sim.total_photons_all;
        }} else {{
            lineGroups = st.baseGroups.map(g => ({{ energy: g.energy, count: g.count, isTarget: false }}));
            for (const p of st.photons) {{
                let found = null;
                for (const g of lineGroups) {{
                    if (Math.abs(g.energy - p.energy) < tol) {{
                        found = g;
                        break;
                    }}
                }}
                if (found) {{
                    found.count += 1;
                }} else {{
                    lineGroups.push({{ energy: p.energy, count: 1, isTarget: false }});
                }}
            }}
        }}

        let targetColCount = 0;
        let targetColEnergy = st.activeStep ? st.activeStep.energy : 0;
        if (st.activeStep) {{
            let foundGroup = null;
            for (const g of lineGroups) {{
                if (Math.abs(g.energy - st.activeStep.energy) < tol) {{
                    foundGroup = g;
                    targetColCount = g.count;
                    targetColEnergy = g.energy;
                    break;
                }}
            }}
            if (!foundGroup && st.highlightTargetCol) {{
                foundGroup = {{ energy: targetColEnergy, count: 0, isTarget: true }};
                lineGroups.push(foundGroup);
            }} else if (foundGroup && st.highlightTargetCol) {{
                foundGroup.isTarget = true;
            }}
        }}

        const projectedMax = (st.activeStep && !st.includeNewInBase) ? targetColCount + 1 : targetColCount;
        const maxCount = Math.max(4, projectedMax, ...lineGroups.map(g => g.count));

        const destX = energyToScreenX(targetColEnergy);
        const yOld = specBottom - (targetColCount / maxCount) * (specH - 22);
        const yNew = specBottom - ((targetColCount + 1) / maxCount) * (specH - 22);
        const destY = 0.5 * (yOld + yNew);

        return {{
            specLeft, specRight, specTop, specBottom, specW, specH,
            lineGroups, displayedPhotonCount, maxCount, destX, destY, yOld, yNew
        }};
    }}

    function drawScene() {{
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const st = decodeTimelineState(tau);
        const specLayout = computeSpectrumLayout(st);

        const pct = (tau / totalMuons) * 100.0;
        document.getElementById('timelineFill').style.width = pct + '%';
        document.getElementById('timelinePlayhead').style.left = pct + '%';
        document.getElementById('timelineRightLabel').innerHTML =
            `Muon <b>#${{(st.muonIdx + 1).toLocaleString('en-US')}} / ${{totalMuons.toLocaleString('en-US')}}</b>`;
        document.getElementById('photonCountLabel').innerHTML =
            `Photons (𝛾): <b>${{specLayout.displayedPhotonCount.toLocaleString()}}</b>`;

        drawLeftEnergyDiagram(st, specLayout);
        drawRightSpectrum(st, specLayout);
        updateBottomBar(st);
    }}

    function drawLeftEnergyDiagram(st, specLayout) {{
        ctx.fillStyle = '#0f172a';
        ctx.font = 'bold 16.5px Calibri, "Segoe UI", sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`Relativistic Atomic Energy Level Diagram (${{sim.element_label || sim.element}}) — Muon #${{(st.muonIdx + 1).toLocaleString('en-US')}} of ${{totalMuons.toLocaleString('en-US')}}`, 26, 28);

        ctx.save();
        ctx.beginPath();
        ctx.rect(4, 36, 948, canvas.height - 40);
        ctx.clip();
        ctx.translate(panXL, panYL);
        ctx.scale(zoomL, zoomL);

        const padLeft = 102;
        for (let n = 1; n <= sim.max_n; n++) {{
            const y = levelToScreen(0, n).y;
            ctx.strokeStyle = '#e2e8f0';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(padLeft - 12, y);
            ctx.lineTo(932, y);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.fillStyle = '#334155';
            ctx.font = 'bold 14px Calibri, "Segoe UI", sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(`n = ${{n}}`, padLeft - 16, y + 4);
        }}

        for (let l = 0; l <= sim.max_l; l++) {{
            const x = levelToScreen(l, 1).x;
            ctx.fillStyle = '#334155';
            ctx.font = 'bold 14px Calibri, "Segoe UI", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(`ℓ = ${{l}} (${{sim.l_symbols[l]}})`, x, canvas.height - 14);
        }}

        const showAllProbs = document.getElementById('chkAllProbs').checked;
        const showPhotonAnim = document.getElementById('chkPhotonAnim').checked;
        const activeKey = st.activeStep ? `${{st.activeStep.from}}->${{st.activeStep.to}}` : '';
        const focusFrom = hoveredLevel || (st.activeStep ? st.activeStep.from : '');

        for (const edge of permanentEdges) {{
            const isCurrentActive = (edge.key === activeKey);
            const isCurrentMuonPath = st.currentMuonKeys.has(edge.key);
            const isPastMuonPath = st.traversedKeys.has(edge.key);
            const isFromCurrentState = (edge.from === focusFrom);

            if (!showAllProbs && !isFromCurrentState && !isCurrentActive && !isCurrentMuonPath) {{
                continue;
            }}

            ctx.save();
            ctx.beginPath();
            ctx.moveTo(edge.p1.x, edge.p1.y);
            ctx.quadraticCurveTo(edge.cp.cx, edge.cp.cy, edge.p2.x, edge.p2.y);

            if (isCurrentActive) {{
                ctx.strokeStyle = '#c1121f';
                ctx.lineWidth = 4.2;
                ctx.shadowColor = 'rgba(193, 18, 31, 0.35)';
                ctx.shadowBlur = 8;
            }} else if (isCurrentMuonPath) {{
                ctx.strokeStyle = '#0f4c81';
                ctx.lineWidth = 3.2;
            }} else if (isFromCurrentState) {{
                ctx.setLineDash([6, 4]);
                ctx.strokeStyle = '#0284c7';
                ctx.lineWidth = 2.0;
            }} else if (isPastMuonPath) {{
                ctx.strokeStyle = 'rgba(15, 76, 129, 0.45)';
                ctx.lineWidth = 2.0;
            }} else {{
                ctx.setLineDash([5, 4]);
                ctx.strokeStyle = 'rgba(71, 85, 105, 0.40)';
                ctx.lineWidth = 1.4;
            }}
            ctx.stroke();
            ctx.restore();
        }}

        const baseLvlFont = sim.max_n <= 7 ? 15.0 : 13.5;
        for (const lvl of sim.levels) {{
            const pos = levelToScreen(lvl.x_pos, lvl.n);
            const isCurr = (st.activeStep && st.activeStep.from === lvl.name);
            const isTarg = (st.activeStep && st.activeStep.to === lvl.name);
            const isHov = (hoveredLevel === lvl.name);

            ctx.strokeStyle = isCurr ? '#c1121f' : (isTarg ? '#0284c7' : (isHov ? '#d97706' : '#1e293b'));
            ctx.lineWidth = (isCurr || isTarg || isHov) ? 4.2 : 2.5;
            ctx.beginPath();
            ctx.moveTo(pos.x - 18, pos.y);
            ctx.lineTo(pos.x + 18, pos.y);
            ctx.stroke();

            const col = isCurr ? '#c1121f' : (isTarg ? '#0284c7' : '#0f172a');
            drawSubscriptState(ctx, lvl.name, pos.x, pos.y - 8, baseLvlFont, col, (isCurr || isTarg || isHov));
        }}

        for (const b of permanentEdges) {{
            const isCurrentActive = (b.key === activeKey);
            const isCurrentMuonPath = st.currentMuonKeys.has(b.key);
            const isOutgoingFromCurr = (b.from === focusFrom);

            if (!showAllProbs && !isOutgoingFromCurr && !isCurrentActive) {{
                continue;
            }}

            const dist = Math.hypot(b.x - b.anchorX, b.y - b.anchorY);
            if (dist > 5) {{
                ctx.save();
                ctx.beginPath();
                ctx.moveTo(b.anchorX, b.anchorY);
                ctx.lineTo(b.x, b.y);
                ctx.strokeStyle = isCurrentActive ? '#c1121f' : '#94a3b8';
                ctx.lineWidth = isCurrentActive ? 1.5 : 1.0;
                ctx.stroke();
                ctx.restore();
            }}

            ctx.save();
            if (isCurrentActive) {{
                ctx.fillStyle = '#fef2f2';
                ctx.strokeStyle = '#c1121f';
                ctx.lineWidth = 2.3;
            }} else if (isOutgoingFromCurr) {{
                ctx.fillStyle = '#ffffff';
                ctx.strokeStyle = '#0284c7';
                ctx.lineWidth = 1.7;
            }} else if (isCurrentMuonPath) {{
                ctx.fillStyle = '#eff6ff';
                ctx.strokeStyle = '#0f4c81';
                ctx.lineWidth = 1.5;
            }} else {{
                ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
                ctx.strokeStyle = '#94a3b8';
                ctx.lineWidth = 1.1;
            }}

            ctx.beginPath();
            ctx.roundRect(b.x - b.w / 2, b.y - b.h / 2, b.w, b.h, 6);
            ctx.fill();
            ctx.stroke();

            ctx.beginPath();
            ctx.moveTo(b.x - b.w / 2 + 4, b.y);
            ctx.lineTo(b.x + b.w / 2 - 4, b.y);
            ctx.strokeStyle = isCurrentActive ? 'rgba(193, 18, 31, 0.45)' : '#cbd5e1';
            ctx.lineWidth = 1.0;
            ctx.stroke();

            const txtColor = isCurrentActive ? '#991b1b' : (isOutgoingFromCurr ? '#0f4c81' : '#1e293b');
            ctx.fillStyle = txtColor;
            ctx.textAlign = 'center';

            ctx.font = 'bold 13px Calibri, "Segoe UI", sans-serif';
            ctx.fillText(b.probTxt, b.x, b.y - 5);

            ctx.font = 'normal 12px Calibri, "Segoe UI", sans-serif';
            ctx.fillText(b.energyTxt, b.x, b.y + 13);
            ctx.restore();
        }}

        let photonOriginScreen = null;
        if (st.activeStep) {{
            const activeEdge = permanentEdges.find(e => e.key === activeKey);
            const c1 = sim.level_map[st.activeStep.from];
            const c2 = sim.level_map[st.activeStep.to];
            const p1 = levelToScreen(c1.x_pos, c1.n);
            const p2 = levelToScreen(c2.x_pos, c2.n);
            const cp = activeEdge ? activeEdge.cp : getCurveControlPoint(p1, p2, 0);

            const tEase = easeInOutCubic(st.flightProg);
            const muonPt = pointOnQuadBezier(p1, cp, p2, tEase);
            const midCurve = pointOnQuadBezier(p1, cp, p2, 0.5);
            photonOriginScreen = {{
                x: midCurve.x * zoomL + panXL,
                y: midCurve.y * zoomL + panYL
            }};

            ctx.save();
            ctx.beginPath();
            ctx.arc(muonPt.x, muonPt.y, 15, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(193, 18, 31, 0.24)';
            ctx.fill();

            ctx.beginPath();
            ctx.arc(muonPt.x, muonPt.y, 10.5, 0, Math.PI * 2);
            ctx.fillStyle = '#c1121f';
            ctx.fill();
            ctx.lineWidth = 2.0;
            ctx.strokeStyle = '#ffffff';
            ctx.stroke();

            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 11.5px Calibri, "Segoe UI", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('μ⁻', muonPt.x, muonPt.y + 4);
            ctx.restore();

            const htmlFrom = fmtStateHTML(st.activeStep.from);
            const htmlTo = fmtStateHTML(st.activeStep.to);
            const isoTxt = st.activeStep.a ? ` (<sup>${{st.activeStep.a}}</sup>${{sim.element}})` : '';
            document.getElementById('statusStepText').innerHTML =
                `Muon <b>#${{(st.muonIdx + 1).toLocaleString('en-US')}}</b>${{isoTxt}}: &nbsp;<b>${{htmlFrom}} → ${{htmlTo}}</b> &nbsp;` +
                `(<i>P</i> = ${{st.activeStep.prob.toFixed(1)}}%, &nbsp;Δ<i>E</i> = <b>${{st.activeStep.energy.toFixed(2)}} keV</b>)`;
        }} else if (st.done) {{
            // the muons end where the simulation really left them: 1s_1/2, or a level without any downward dipole transition
            const fc = st.finalCounts || {{}};
            const nTot = sim.num_muons;
            const nGround = fc['1s_1/2'] || 0;
            const stuck = Object.keys(fc).filter(k => k !== '1s_1/2');
            const markMuon = (px, py, colour) => {{
                ctx.beginPath();
                ctx.arc(px, py, 10.5, 0, Math.PI * 2);
                ctx.fillStyle = colour;
                ctx.fill();
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 11.5px Calibri, "Segoe UI", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('μ⁻', px, py + 4);
            }};
            const pGround = levelToScreen(0, 1);
            if (nGround > 0 || !stuck.length) markMuon(pGround.x, pGround.y, '#0f4c81');
            stuck.forEach(k => {{
                const c = sim.level_map[k];
                if (c) {{ const p = levelToScreen(c.x_pos, c.n); markMuon(p.x, p.y, '#b45309'); }}
            }});
            const stuckTxt = stuck.map(k => `${{fc[k].toLocaleString('en-US')}} stayed in ${{fmtStateHTML(k)}}`).join('; ');
            document.getElementById('statusStepText').innerHTML = stuck.length
                ? `<b>Cascade Complete</b> — ${{nGround.toLocaleString('en-US')}} of ${{nTot.toLocaleString('en-US')}} μ⁻ reached the ground state 1s<sub>1/2</sub>; ${{stuckTxt}} (no downward E1 transition from there) ` +
                  `(${{sim.total_photons_all.toLocaleString('en-US')}} 𝛾 photons).`
                : `<b>Cascade Complete</b> — Ground state 1s<sub>1/2</sub> (${{nTot.toLocaleString('en-US')}} μ⁻, ${{sim.total_photons_all.toLocaleString('en-US')}} 𝛾 photons)` +
                  `.`;
        }}

        ctx.restore();

        if (showPhotonAnim && st.activeStep && st.photonInFlight && photonOriginScreen) {{
            const tEase = easeInOutCubic(st.flightProg);
            const destX = specLayout.destX * zoomR + panXR;
            const destY = specLayout.destY * zoomR + panYR;

            const gx = photonOriginScreen.x + (destX - photonOriginScreen.x) * tEase;
            const gy = photonOriginScreen.y + (destY - photonOriginScreen.y) * tEase;
            const ang = Math.atan2(destY - photonOriginScreen.y, destX - photonOriginScreen.x);

            ctx.save();
            ctx.translate(gx, gy);
            ctx.rotate(ang);
            ctx.beginPath();
            ctx.strokeStyle = '#0284c7';
            ctx.lineWidth = 2.8;
            for (let xw = -46; xw <= 0; xw += 2) {{
                const yw = 6.0 * Math.sin(xw * 0.42 - st.flightProg * 28);
                if (xw === -46) ctx.moveTo(xw, yw);
                else ctx.lineTo(xw, yw);
            }}
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(0, 0, 5.0, 0, Math.PI * 2);
            ctx.fillStyle = '#0f4c81';
            ctx.fill();
            ctx.restore();

            ctx.save();
            const gTxt = `𝛾 : ΔE = ${{st.activeStep.energy.toFixed(2)}} keV`;
            ctx.font = 'bold italic 13.5px "Cambria Math", "Times New Roman", Calibri, serif';
            const gw = ctx.measureText(gTxt).width + 16;
            ctx.fillStyle = '#eff6ff';
            ctx.strokeStyle = '#0284c7';
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            ctx.roundRect(gx - gw / 2, gy - 28, gw, 22, 4);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#0f4c81';
            ctx.textAlign = 'center';
            ctx.fillText(gTxt, gx, gy - 13);
            ctx.restore();
        }}
    }}

    function drawRightSpectrum(st, layout) {{
        const {{ specLeft, specRight, specTop, specBottom, specW, specH, lineGroups, displayedPhotonCount, maxCount, yOld, yNew }} = layout;

        ctx.strokeStyle = '#cbd5e1';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(956, 14);
        ctx.lineTo(956, canvas.height - 14);
        ctx.stroke();

        ctx.fillStyle = '#0f172a';
        ctx.font = 'bold 16.5px Calibri, "Segoe UI", sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`Muonic X-Ray Emission Spectrum (Photons 𝛾: ${{displayedPhotonCount.toLocaleString()}})`, specLeft, 28);

        ctx.save();
        ctx.beginPath();
        ctx.rect(960, 36, canvas.width - 964, canvas.height - 40);
        ctx.clip();
        ctx.translate(panXR, panYR);
        ctx.scale(zoomR, zoomR);

        ctx.strokeStyle = '#e2e8f0';
        ctx.lineWidth = 1;
        ctx.fillStyle = '#475569';
        ctx.font = '12.5px Calibri, "Segoe UI", sans-serif';
        ctx.textAlign = 'right';
        const yTicks = 4;
        for (let i = 0; i <= yTicks; i++) {{
            const val = Math.round((maxCount / yTicks) * i);
            const y = specBottom - (val / maxCount) * (specH - 22);
            ctx.beginPath();
            ctx.moveTo(specLeft, y);
            ctx.lineTo(specRight, y);
            ctx.stroke();
            ctx.fillText(val.toLocaleString(), specLeft - 8, y + 4);
        }}

        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(specLeft, specTop);
        ctx.lineTo(specLeft, specBottom);
        ctx.lineTo(specRight, specBottom);
        ctx.stroke();

        ctx.textAlign = 'center';
        const xTicks = 6;
        for (let i = 0; i <= xTicks; i++) {{
            const eVal = (sim.max_energy / xTicks) * i;
            const x = energyToScreenX(eVal);
            ctx.beginPath();
            ctx.moveTo(x, specBottom);
            ctx.lineTo(x, specBottom + 5);
            ctx.stroke();
            ctx.fillText(`${{eVal.toFixed(0)}}`, x, specBottom + 18);
        }}
        ctx.font = 'bold 13.5px Calibri, "Segoe UI", sans-serif';
        ctx.fillText('Transition Energy ΔE [keV]', specLeft + specW * 0.5, canvas.height - 12);

        const useGaussian = document.getElementById('chkGaussian').checked;
        if (useGaussian && lineGroups.length > 0) {{
            const sigma = sim.max_energy * 0.012;
            ctx.save();
            ctx.beginPath();
            for (let px = 0; px <= specW; px += 2) {{
                const eVal = (px / specW) * sim.max_energy;
                let sumH = 0;
                for (const g of lineGroups) {{
                    const effCount = g.count + (g.isTarget ? st.photonFadeInProg : 0);
                    const z = (eVal - g.energy) / sigma;
                    if (Math.abs(z) < 4.5) sumH += effCount * Math.exp(-0.5 * z * z);
                }}
                const sx = specLeft + px;
                const sy = specBottom - (sumH / maxCount) * (specH - 22);
                if (px === 0) ctx.moveTo(sx, sy);
                else ctx.lineTo(sx, sy);
            }}
            ctx.strokeStyle = '#0f4c81';
            ctx.lineWidth = 2.2;
            ctx.stroke();
            ctx.lineTo(specRight, specBottom);
            ctx.lineTo(specLeft, specBottom);
            ctx.closePath();
            ctx.fillStyle = 'rgba(15, 76, 129, 0.18)';
            ctx.fill();
            ctx.restore();
        }}

        for (const g of lineGroups) {{
            const x = energyToScreenX(g.energy);
            const hBase = (g.count / maxCount) * (specH - 22);
            const yBaseTop = specBottom - hBase;

            if (g.isTarget) {{
                if (g.count > 0) {{
                    ctx.save();
                    ctx.strokeStyle = '#0284c7';
                    ctx.lineWidth = 7.2;
                    ctx.beginPath();
                    ctx.moveTo(x, specBottom);
                    ctx.lineTo(x, yBaseTop);
                    ctx.stroke();
                    ctx.restore();
                }}

                ctx.save();
                ctx.strokeStyle = '#0284c7';
                ctx.lineWidth = 7.2;

                if (st.photonFadeInProg <= 0.01) {{
                    ctx.globalAlpha = 0.34;
                    ctx.setLineDash([4, 3]);
                    ctx.beginPath();
                    ctx.moveTo(x, yOld);
                    ctx.lineTo(x, yNew);
                    ctx.stroke();
                }} else {{
                    if (st.photonFadeInProg < 0.99) {{
                        ctx.save();
                        ctx.globalAlpha = 0.34 * (1.0 - st.photonFadeInProg);
                        ctx.setLineDash([4, 3]);
                        ctx.beginPath();
                        ctx.moveTo(x, yOld);
                        ctx.lineTo(x, yNew);
                        ctx.stroke();
                        ctx.restore();
                    }}
                    ctx.globalAlpha = 0.34 + 0.66 * st.photonFadeInProg;
                    ctx.setLineDash([]);
                    ctx.beginPath();
                    ctx.moveTo(x, yOld);
                    ctx.lineTo(x, yNew);
                    ctx.stroke();
                }}
                ctx.restore();

                ctx.fillStyle = '#0284c7';
                ctx.font = 'bold 12.5px Calibri, "Segoe UI", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(`${{g.energy.toFixed(1)}}`, x, yNew - 6);
            }} else if (g.count > 0) {{
                ctx.save();
                ctx.strokeStyle = '#0f4c81';
                ctx.lineWidth = 3.6;
                ctx.beginPath();
                ctx.moveTo(x, specBottom);
                ctx.lineTo(x, yBaseTop);
                ctx.stroke();
                ctx.restore();

                ctx.fillStyle = '#1e293b';
                ctx.font = '11.5px Calibri, "Segoe UI", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(`${{g.energy.toFixed(1)}}`, x, yBaseTop - 6);
            }}
        }}

        ctx.restore();
    }}

    function updateBottomBar(st) {{
        const focusState = hoveredLevel || st.currentState;
        const activeTo = (!hoveredLevel && st.activeStep) ? st.activeStep.to : '';
        const sig = `${{focusState}}|${{activeTo}}|${{st.done}}`;
        if (sig === lastBottomBarSignature) return;
        lastBottomBarSignature = sig;

        const list = (sim.state_transitions[focusState] || []);       // every decay channel (the narrow bar scrolls)
        if (!list.length) {{
            const emptyMsg = (focusState === '1s_1/2')
                ? ui.ground_reached
                : ui.no_transition;
            inspectorBarEl.innerHTML = `<div><b>${{ui.branching}} (${{fmtStateHTML(focusState)}}):</b></div><div class="inspector-options-row"><span>${{emptyMsg}}</span></div>`;
            return;
        }}
        let html = `<div><b>${{ui.branching}} (${{fmtStateHTML(focusState)}}):</b></div><div class="inspector-options-row">`;
        for (const item of list) {{
            const isChosen = (activeTo === item.target);
            const cls = isChosen ? 'badge-candidate badge-chosen' : 'badge-candidate';
            html += `<span class="${{cls}}" data-from="${{focusState}}" data-to="${{item.target}}" onclick="openWavefunctionModal('${{focusState}}', '${{item.target}}')" title="Click for Radial Wavefunctions & Analysis">→ ${{fmtStateHTML(item.target)}} : <b>${{item.prob.toFixed(1)}}%</b> (ΔE = ${{item.energy.toFixed(2)}} keV)</span>`;
        }}
        html += `</div>`;
        inspectorBarEl.innerHTML = html;
    }}

    function loop(now) {{
        const dt = Math.min(0.08, Math.max(0.0, (now - lastTime) / 1000.0));
        lastTime = now;

        easeZoomSteps(dt);
        if (isResettingZoomSmooth) {{
            const decay = 1.0 - Math.exp(-10.5 * dt);
            zoomL += (1.0 - zoomL) * decay;
            panXL += (0.0 - panXL) * decay;
            panYL += (0.0 - panYL) * decay;
            zoomR += (1.0 - zoomR) * decay;
            panXR += (0.0 - panXR) * decay;
            panYR += (0.0 - panYR) * decay;

            if (
                Math.abs(zoomL - 1.0) < 0.003 &&
                Math.abs(zoomR - 1.0) < 0.003 &&
                Math.abs(panXL) < 0.5 &&
                Math.abs(panYL) < 0.5 &&
                Math.abs(panXR) < 0.5 &&
                Math.abs(panYR) < 0.5
            ) {{
                zoomL = 1.0; panXL = 0.0; panYL = 0.0;
                zoomR = 1.0; panXR = 0.0; panYR = 0.0;
                isResettingZoomSmooth = false;
            }}
            updateZoomButtonLabel();
        }}

        if (isPlaying && !isDraggingTimeline && tau < totalMuons) {{
            const m = Math.min(totalMuons - 1, Math.floor(tau));
            const K = Math.max(1, sim.trajectories[m].length);
            const stepRate = 0.52 * speed;
            tau = Math.min(totalMuons, tau + (dt * stepRate) / K);
            if (tau >= totalMuons) {{
                isPlaying = false;
                syncPlayButtonUI();
            }}
        }}

        drawScene();
        requestAnimationFrame(loop);
    }}

    // display settings (checkboxes, speed, zoom) are remembered while the language / text size is switched
    const SIM_KEY = "{sim_key}";
    function simSave() {{
        try {{
            window.parent.__simSet = {{
                key: SIM_KEY,
                photon: document.getElementById('chkPhotonAnim').checked,
                all: document.getElementById('chkAllProbs').checked,
                speedIdx: speedSliderEl.value,
                zL: zoomL, pxL: panXL, pyL: panYL, zR: zoomR, pxR: panXR, pyR: panYR,
                tau: tau, playing: isPlaying, wf: wfCurrent
            }};
        }} catch (err) {{}}
    }}
    let restoredPlaying = true, restoredWf = null;
    try {{
        const saved = window.parent.__simSet;
        if (saved && saved.key === SIM_KEY) {{
            document.getElementById('chkPhotonAnim').checked = !!saved.photon;
            document.getElementById('chkAllProbs').checked = !!saved.all;
            updateDiscreteSpeed(saved.speedIdx);
            zoomL = saved.zL; panXL = saved.pxL; panYL = saved.pyL;
            zoomR = saved.zR; panXR = saved.pxR; panYR = saved.pyR;
            updateZoomButtonLabel();
            if (typeof saved.tau === 'number') tau = Math.max(0.0, Math.min(totalMuons, saved.tau));
            restoredPlaying = saved.playing !== false;
            restoredWf = saved.wf || null;
        }}
    }} catch (err) {{}}
    setInterval(simSave, 300);

    isPlaying = restoredPlaying;
    lastTime = performance.now();
    // an analysis window that was open stays open through the switch of language / text size
    if (restoredWf) {{ openWavefunctionModal(restoredWf.from, restoredWf.to); }}
    syncPlayButtonUI();
    requestAnimationFrame(loop);
    </script>
    </body>
    </html>
    """
    embed_html(html_code, 555)


# ==============================================================================
# TOP-LEVEL DIALOG TRIGGER WITH SINGLE LOCALIZED HEADER
# ==============================================================================
def _on_dialog_dismiss():
    st.session_state.dialog_alive = False


if st.session_state.open_dialog_flag or st.session_state.get("dialog_alive"):
    if st.session_state.open_dialog_flag:
        st.session_state.open_dialog_flag = False
        st.session_state.dlg_serial = st.session_state.get("dlg_serial", 0) + 1
        st.session_state.dialog_alive = True
    dlg_title = "\u200b"   # the dialog has no title text (only the grey header band with the buttons)

    try:
        # not dismissible: clicking the fixed header (language / text size) must not close the window;
        # the window has its own close button (see render_dialog_body)
        _dialog_decorator = st.dialog(dlg_title, width="large", dismissible=False)
    except TypeError:                      # older Streamlit without "dismissible"
        try:
            _dialog_decorator = st.dialog(dlg_title, width="large", on_dismiss=_on_dialog_dismiss)
        except TypeError:
            _dialog_decorator = st.dialog(dlg_title, width="large")

    @_dialog_decorator
    def _launch_localized_dialog():
        render_dialog_body()

    _launch_localized_dialog()


# ==============================================================================
# ANCHORED TOP HEADER: TITLE | FONT SCALE | LANGUAGE
# ==============================================================================
with st.container(key="app_header"):
    # left: text size + language | the title, centred on the whole row | right: the i / ? buttons (both languages)
    hdr_font, hdr_lang, hdr_title, hdr_help = st.columns([0.9, 0.9, 7.2, 0.62], vertical_alignment="center")

hdr_title.markdown(
    f"<h3 class='app-title' style='margin:0; padding:0; font-size:1.75rem; font-weight:600; line-height:1.2;'>"
    # the Hebrew title reads right to left as one unit, so its last word (X) ends at the LEFT end of the sentence
    + (f"<span style='direction:rtl; unicode-bidi:isolate; display:inline-block;'>{tr('app_title')}</span>"
       if st.session_state.lang == "HE" else tr('app_title'))
    + "</h3>",
    unsafe_allow_html=True
)

font_options = [130, 115, 100, 90]   # first option sits at the right end (RTL slider): right = larger text
_MAGNIFIER = (
    "<svg width='13' height='13' viewBox='0 0 24 24' fill='none' stroke='#64748b' stroke-width='2.4' "
    "stroke-linecap='round' stroke-linejoin='round'><circle cx='10' cy='10' r='6.5'/><path d='M15 15l6 6'/>{sign}</svg>"
)
if st.session_state.get("font_slider") not in font_options:
    st.session_state["font_slider"] = st.session_state.font_scale
with hdr_font:
    with st.container(key="font_size_slider"):
        fs_minus, fs_slider, fs_plus = st.columns([1, 3.2, 1], vertical_alignment="center")
        fs_minus.markdown(
            "<div class='fs-icon fs-minus' title=''>" + _MAGNIFIER.format(sign="<path d='M7 10h6'/>") + "</div>", unsafe_allow_html=True)
        fs_plus.markdown(
            "<div class='fs-icon fs-plus' title=''>" + _MAGNIFIER.format(sign="<path d='M7 10h6M10 7v6'/>") + "</div>", unsafe_allow_html=True)
        with fs_slider:
            chosen_font = st.select_slider(
                "Text Size",
                options=font_options,
                key="font_slider",
                format_func=lambda x: {130: "XL", 115: "L", 100: "M", 90: "S"}[x],
                label_visibility="collapsed"
            )
if chosen_font != st.session_state.font_scale:
    st.session_state.font_scale = chosen_font
    st.rerun()

with hdr_lang:
    with st.container(key="lang_toggle"):
        lang_choice = st.radio(
            "Language",
            options=["HE", "EN"],
            index=0 if st.session_state.lang == "HE" else 1,
            format_func=lambda k: "עברית" if k == "HE" else "English",
            horizontal=True,
            label_visibility="collapsed"
        )
if lang_choice != st.session_state.lang:
    st.session_state.lang = lang_choice
    st.rerun()

SHOW_REPORT_PAGES = False   # True: the information tab shows the pages of the report (report_pages.py) instead of the short text


@st.cache_resource
def report_pages_json():
    """The pages of the project report (report_pages.py, made from report.pdf) for the "information" tab of the help
    window, as JSON [[width, height, base64 webp], ...]. Images, not an embedded PDF: some browsers block embedded PDFs."""
    try:
        import report_pages
    except ImportError:
        return None
    return json.dumps([list(p) for p in report_pages.PAGES])


# the "?" to the right of the language switch: opens the help guide (a layer drawn by the page script, see PARENT_UI_JS)
with hdr_help:
    _hg = help_guide.TEXT["HE" if st.session_state.lang == "HE" else "EN"]
    # (the spinning atom of a language / text-size switch stands beside the "i", see .hdr-atom)
    st.markdown("<div class='help-btns'><svg class='hdr-atom' viewBox='0 0 28 28'>"
                "<ellipse cx='14' cy='14' rx='10.5' ry='3.8' fill='none' stroke='#0f4c81' stroke-width='1.8'/>"
                "<ellipse cx='14' cy='14' rx='10.5' ry='3.8' fill='none' stroke='#0f4c81' stroke-width='1.8' transform='rotate(60 14 14)'/>"
                "<ellipse cx='14' cy='14' rx='10.5' ry='3.8' fill='none' stroke='#0f4c81' stroke-width='1.8' transform='rotate(120 14 14)'/>"
                "<circle cx='14' cy='14' r='2.6' fill='#c1121f'/></svg>"
                f"<div class='help-q help-i' data-tab='info' tabindex='0' role='button' title='{_hg['tab_info']}' aria-label='{_hg['tab_info']}'>i</div>"
                f"<div class='help-q' data-tab='guide' tabindex='0' role='button' title='{_hg['tab_guide']}' aria-label='{_hg['tab_guide']}'>?</div></div>",
                unsafe_allow_html=True)


# ==============================================================================
# MAIN WORKSPACE:
# - Left Column: "+ Create New Spectrum" | "Select All / Deselect All" | Scrollable Cards List
# ==============================================================================
col_left, col_right = st.columns([1.28, 2.72], gap="medium")

any_running_now = any(
    s.get("status") in ("running", "simulating") or not s.get("notified_done", True)
    for s in st.session_state.spectra_list
)
poll_interval = 0.5 if any_running_now else None
if any_running_now:
    st.markdown("<div class='sim-loading-marker'></div>", unsafe_allow_html=True)

with col_left:
    # Hidden bridge input for instant live Drag-and-Drop card reordering
    st.text_input(
        "card_order_bridge",
        key="_card_order_bridge",
        on_change=_apply_custom_card_order,
        label_visibility="collapsed"
    )
    st.text_input(
        "color_bridge",
        key="_color_bridge",
        on_change=_apply_color_choice,
        label_visibility="collapsed"
    )

    @st.fragment(run_every=poll_interval)
    def render_left_cards_panel():
        # no spectrum: the button spans the whole page; one spectrum: the button alone; two or more: it is joined by
        # the select-all / deselect-all button
        n_specs = len(st.session_state.spectra_list)
        if n_specs >= 2:
            top_btn_c1, top_btn_c2 = st.columns([1.0, 1.0], vertical_alignment="center")
        else:
            top_btn_c1 = st.container(key="top_add_full") if n_specs == 0 else st.container()
            top_btn_c2 = None

        if top_btn_c1.button(
            tr("add_spectrum_top"),
            icon=":material/add:",
            key="top_add_spec_btn",
            type="primary",
            use_container_width=True
        ):
            st.session_state.editing_id = "NEW"
            st.session_state.open_dialog_flag = True
            st.rerun(scope="app")

        if n_specs == 0:
            # start page (no spectrum yet, or all deleted): the site guide of the "?" window, under the create button
            _labels = {k: tr(k) for k in ("create_spec_sim", "add_spectrum_top", "return_all_btn", "view_current_btn")}
            with st.container(key="empty_site_guide"):
                # (in an iframe: st.html / st.markdown would strip the inline SVG of the map)
                embed_html("<!DOCTYPE html><html><body>"
                           + help_guide.start_page_html("HE" if st.session_state.lang == "HE" else "EN", _labels,
                                                        tr("reset_zoom"), tr("wheel_tooltip"),
                                                        st.session_state.font_scale / 100.0)
                           + "</body></html>", 760)

        if top_btn_c2 is not None:
            all_selected = all(s.get("visible", False) for s in st.session_state.spectra_list)
            sel_btn_label = tr("deselect_all") if all_selected else tr("select_all")
            if top_btn_c2.button(sel_btn_label, key="toggle_select_all_btn", use_container_width=True):
                target_state = not all_selected
                for s in st.session_state.spectra_list:
                    s["visible"] = target_state
                    st.session_state[f"chk_{s['id']}"] = target_state
                st.rerun(scope="app")

        needs_full_app_rerun = False

        # Per-card colours: card background is a tint of the spectrum colour, play button uses the colour itself.
        card_style_rules = []
        for _s in st.session_state.spectra_list:
            _cid, _col = _s["id"], _s["color"]
            card_style_rules.append(
                f"div.st-key-spectrum_card_{_cid}{{border-left-color:{_col} !important;}}"
                f".st-key-card_anim_{_cid} button{{background-color:{_col} !important;}}"
                f"div.st-key-card_anim_{_cid} div[data-testid=\"stButton\"] > button:hover,"
                f"div.st-key-card_anim_{_cid} div[data-testid=\"stButton\"] > button:focus,"
                f"div.st-key-card_anim_{_cid} div[data-testid=\"stButton\"] > button:active"
                f"{{background-color:{_col} !important;border-color:#ffffff !important;}}"
                f"div.st-key-spectrum_card_{_cid} .play-ring{{--ringc:{_col};}}"
            )
            if st.session_state.active_anim_id == _s["id"]:
                card_style_rules.append(
                    f".st-key-card_anim_{_cid} button{{box-shadow:0 0 0 3px {_col} !important;}}"
                    f"div.st-key-card_anim_{_cid} [data-testid=\"stButton\"] button{{background-image:url(\"{PAUSE_ICON}\") !important;"
                    f"background-position:50% 50% !important;background-size:24px 24px !important;}}"
                    # the running tab gets the side stripe (4px, its own colour) on all four sides: 1px border + 3px inset
                    f"div.st-key-spectrum_card_{_cid}.st-key-spectrum_card_{_cid},"
                    f"div.st-key-spectrum_card_{_cid}.st-key-spectrum_card_{_cid}:hover{{border-color:{_col} !important;"
                    f"box-shadow:inset 0 3px 0 0 {_col},inset -3px 0 0 0 {_col},inset 0 -3px 0 0 {_col} !important;}}"
                )
        if card_style_rules:
            st.markdown(f"<style>{''.join(card_style_rules)}</style>", unsafe_allow_html=True)

        # Scrollable list of Spectrum Cards
        with st.container(height=515, border=False, key="spectra_cards_scroll"):
            for idx, spec in enumerate(st.session_state.spectra_list):
                is_anim_selected = (st.session_state.active_anim_id == spec["id"])
                with st.container(border=True, key=f"spectrum_card_{spec['id']}"):
                    c_actions, c_summary, c_side = st.columns(
                        [0.62, 5.4, 0.85], vertical_alignment="center"
                    )

                    with c_actions:
                        with st.container(key=f"spectrum_actions_{spec['id']}"):
                            if st.button("", icon=":material/edit:", key=f"edit_{spec['id']}"):
                                st.session_state.editor_params = {
                                    "element": spec["element"],
                                    "start_level": spec["start_level"],
                                    "num_muons": min(1000000, spec["num_muons"]),
                                    "nuclear_model": spec["nuclear_model"],
                                    "distribution": spec.get("distribution", "delta"),
                                    "isotope": spec.get("isotope"),
                                    "uehling": spec["uehling"],
                                    "screening": spec["screening"],
                                }
                                st.session_state.editing_id = spec["id"]
                                st.session_state.open_dialog_flag = True
                                st.rerun(scope="app")

                            if st.button("", icon=":material/content_copy:", key=f"copy_{spec['id']}"):
                                new_id = str(uuid.uuid4())[:8]
                                new_color = pick_next_distinct_color(exclude_color=spec["color"])
                                cloned_spec = {
                                    "id": new_id,
                                    "element": spec["element"],
                                    "start_level": spec["start_level"],
                                    "num_muons": spec["num_muons"],
                                    "nuclear_model": spec["nuclear_model"],
                                    "distribution": spec.get("distribution", "delta"),
                                    "isotope": spec.get("isotope"),
                                    "uehling": spec["uehling"],
                                    "screening": spec["screening"],
                                    "visible": spec["visible"],
                                    "color": new_color,
                                    "photons": list(spec.get("photons", [])),
                                    "steps": list(spec.get("steps", [])),
                                    "tables": dict(spec.get("tables", {})),
                                    "payload": dict(spec["payload"], id=new_id, run_nonce=new_id) if spec.get("payload") else None,
                                    "status": spec.get("status", "completed"),
                                    "progress": spec.get("progress", 1.0),
                                    "spectrum_ready": spec_ready(spec),
                                    "notified_ready": True,
                                    "notified_done": True,
                                }
                                st.session_state[f"chk_{new_id}"] = cloned_spec["visible"]
                                if cloned_spec["status"] in ("running", "simulating"):
                                    start_simulation_thread(cloned_spec)
                                st.session_state.spectra_list.insert(0, cloned_spec)
                                st.rerun(scope="app")

                            if st.button("", icon=":material/delete:", key=f"del_{spec['id']}"):
                                spec["cancel"] = True
                                spec["run_token"] = "CANCELLED"
                                if st.session_state.active_anim_id == spec["id"]:
                                    st.session_state.active_anim_id = None
                                st.session_state.spectra_list.pop(idx)
                                st.rerun(scope="app")

                    with c_summary:
                        with st.container(key=f"spectrum_summary_{spec['id']}"):
                            correction_lines = (
                                ("uehling", "qed_card_label"),
                                ("screening", "screening_label"),
                            )
                            correction_html = "".join(
                                f"<span class='{'on' if spec.get(field) else 'off'}'>{tr(label)}</span>"
                                for field, label in correction_lines
                            )
                            _status = spec.get("status", "completed")
                            if _status == "completed" or _status == "error":
                                ring_html = ""
                            elif _status == "spectrum_only":
                                ring_html = ""      # no simulation from SIM_DISABLE_FROM muons on: no Play button, so no ring either
                            elif _status == "simulating":
                                _pct = int(round(max(0.0, min(1.0, float(spec.get("sim_progress", 0.0)))) * 100))
                                ring_html = f"<div class='play-ring' style='--p:{_pct}'><span>{_pct}%</span></div>"
                            else:
                                ring_html = "<div class='play-ring idle'></div>"
                            st.markdown(
                                "<div class='spec-sum'>"
                                f"{ring_html}"
                                "<div class='spec-left'>"
                                f"<div class='spec-el'>{spec_name_html(spec)}</div>"
                                f"<div class='spec-n'>N={spec['num_muons']:,}</div>"
                                f"<div class='spec-dist'>{spec_level_parts_html(spec)[0]}</div>"
                                f"<div class='spec-lvl'>{spec_level_parts_html(spec)[1]}</div>"
                                "</div>"
                                "<div class='spec-right'>"
                                f"<div class='spec-model'>{spec['nuclear_model']}</div>"
                                f"<div class='spec-corr'>{correction_html}</div>"
                                "</div>"
                                "</div>",
                                unsafe_allow_html=True
                            )
                            if _status == "completed":
                                if st.button("", key=f"card_anim_{spec['id']}"):
                                    st.session_state.active_anim_id = (
                                        None if is_anim_selected else spec["id"]
                                    )
                                    st.rerun(scope="app")

                    with c_side:
                        with st.container(key=f"spectrum_side_{spec['id']}"):
                            st.markdown(
                                f"<div class='color-swatch' role='button' tabindex='0' "
                                f"style='background:{spec['color']}'></div>",
                                unsafe_allow_html=True
                            )

                            st.markdown(
                                f"<div class='drag-handle-box' role='button' tabindex='0' "
                                f"aria-label='Move spectrum' data-spec-id='{spec['id']}'>"
                                "<svg width='14' height='30' viewBox='0 0 14 30' fill='none' stroke='currentColor' "
                                "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
                                "<path d='M2 10l5-6 5 6M2 20l5 6 5-6'/></svg></div>",
                                unsafe_allow_html=True
                            )

                            chk_key = f"chk_{spec['id']}"
                            if chk_key not in st.session_state:
                                st.session_state[chk_key] = spec["visible"]
                            is_vis = st.checkbox(
                                "Show", key=chk_key, label_visibility="collapsed",
                                disabled=not spec_ready(spec)
                            )
                            if is_vis != spec["visible"]:
                                spec["visible"] = is_vis
                                st.rerun(scope="app")

                    if spec.get("spectrum_ready") and not spec.get("notified_ready", False):
                        spec["notified_ready"] = True
                        needs_full_app_rerun = True

                    if spec.get("status") == "running":
                        st.markdown(
                            render_inside_card_progress_bar(spec.get("progress", 0.0)),
                            unsafe_allow_html=True
                        )
                    elif spec.get("status") in ("completed", "spectrum_only") and not spec.get("notified_done", False):
                        spec["notified_done"] = True
                        needs_full_app_rerun = True
                    elif spec.get("status") == "error":
                        if not spec.get("notified_done", False):
                            spec["notified_done"] = True
                            needs_full_app_rerun = True
                        st.error(spec_error_text(spec))


        if needs_full_app_rerun:
            st.rerun(scope="app")

    render_left_cards_panel()


    # Installs (once per code version) the drag & drop, mouse-wheel and colour-popover
    # engine directly into the parent page, so it survives fragment reruns.
    _ui_src = PARENT_UI_JS.replace("__PALETTE__", json.dumps(PALETTE_40)).replace("__DIST_TIPS__", json.dumps({tr("dist_delta_short"): tr("dist_delta_tip"), tr("dist_uniform_short"): "P(nℓj) ∝ 1",
                                                                     tr("dist_stat_short"): "P(ℓ) ∝ 2ℓ+1"}, ensure_ascii=False)).replace("__NEED_OTHER_ISOTOPE__", json.dumps(tr("need_other_isotope"))).replace("__MODEL_OFF_POINT__", json.dumps(tr("model_off_point"))).replace("__NEED_POINT__", json.dumps(tr("need_point"))).replace("__MODEL_OFF_SPHERE__", json.dumps(tr("model_off_sphere"))).replace("__MODEL_OFF_FERMI__", json.dumps(tr("model_off_fermi"))).replace("__NEED_SPHERE__", json.dumps(tr("need_sphere"))).replace("__NEED_FERMI__", json.dumps(tr("need_fermi")))
    _ui_version = hashlib.md5(_ui_src.encode("utf-8")).hexdigest()[:12]
    _ui_code = json.dumps(_ui_src).replace("</", "<\\/")
    embed_html_zero(
        "<script>(function(){"
        "var P=window.parent,d=P.document,v=" + json.dumps(_ui_version) + ",code=" + _ui_code + ";"
        "var old=d.getElementById('muon-ui-bridge');"
        "if(old&&old.getAttribute('data-v')===v&&P.__muonUI)return;"
        "if(old)old.remove();"
        "var s=d.createElement('script');s.id='muon-ui-bridge';s.setAttribute('data-v',v);"
        "s.text=code;d.head.appendChild(s);"
        "})();</script>",
        height=0,
    )

    # the help guide in the chosen language: sent to the page on every run (the "?" button reads it when it is pressed)
    _help_labels = {k: tr(k) for k in ("create_spec_sim", "add_spectrum_top", "return_all_btn", "view_current_btn")}
    _help_lang = "HE" if st.session_state.lang == "HE" else "EN"
    _help_json = json.dumps({
        "lang": _help_lang, "dir": "rtl" if _help_lang == "HE" else "ltr",
        "close": help_guide.TEXT[_help_lang]["close"],
        "tab_info": help_guide.TEXT[_help_lang]["tab_info"],
        "tab_guide": help_guide.TEXT[_help_lang]["tab_guide"],
        "no_report": help_guide.TEXT[_help_lang]["no_report"],
        "info_html": help_guide.TEXT[_help_lang]["info_html"],
        "html": help_guide.help_html(_help_lang, _help_labels),
    }).replace("</", "<\\/")
    # (sent once per session and language: the map holds full-resolution screenshots, ~0.9 MB; the page keeps it)
    if st.session_state.get("_help_sent_lang") != _help_lang:
        embed_html_zero("<script>(function(){try{window.parent.__muonHelp=" + _help_json + ";}catch(e){}})();</script>", height=0)
        st.session_state["_help_sent_lang"] = _help_lang
    # the project report (PDF, ~0.8 MB) for the "information" tab: sent once per session (the page keeps it)
    # (for now the information tab shows a short text instead: SHOW_REPORT_PAGES = False)
    if SHOW_REPORT_PAGES and not st.session_state.get("_report_sent"):
        _rep = report_pages_json()
        if _rep:
            embed_html_zero("<script>(function(){try{if(!window.parent.__muonReportPages)window.parent.__muonReportPages="
                            + _rep + ";}catch(e){}})();</script>", height=0)
        st.session_state["_report_sent"] = True


with col_right:
    active_anim_spec = next(
        (s for s in st.session_state.spectra_list if s["id"] == st.session_state.active_anim_id),
        None
    )

    # ==========================================================================
    # VIEW A: LIVE CASCADE ANIMATION
    # ==========================================================================
    if active_anim_spec is not None:
        # The running spectrum tab (with its Pause symbol) already shows element, level and N: no title here.
        bar_c0, bar_c2, bar_c3, bar_c4 = st.columns([0.65, 1.4, 1.4, 0.65], vertical_alignment="center")   # the two buttons side by side, as a pair centred over the simulator
        # on_click callbacks run at the very start of the next run, before the tabs' checkboxes are created,
        # so their state can still be set here
        def _view_all_spectra():
            for _s in st.session_state.spectra_list:
                _s["visible"] = True
                st.session_state[f"chk_{_s['id']}"] = True
            st.session_state.active_anim_id = None

        def _view_only_spectrum(spec_id):
            for _s in st.session_state.spectra_list:
                _vis = (_s["id"] == spec_id)
                _s["visible"] = _vis
                st.session_state[f"chk_{_s['id']}"] = _vis
            st.session_state.active_anim_id = None

        bar_c2.button(
            tr("return_all_btn"),
            icon=":material/bar_chart:",
            type="primary",
            use_container_width=True,
            key="return_all_spectra_btn",
            on_click=_view_all_spectra
        )
        bar_c3.button(
            tr("view_current_btn"),
            icon=":material/show_chart:",
            type="primary",
            use_container_width=True,
            key="view_current_spectrum_btn",
            on_click=_view_only_spectrum,
            args=(active_anim_spec["id"],)
        )
        if active_anim_spec.get("status") in ("running", "simulating"):
            with st.container(key="anim_wait_box"):
                st.info(tr("anim_computing"))
        elif active_anim_spec.get("status") == "completed" and active_anim_spec.get("payload"):
            render_unified_canvas_animator(active_anim_spec["payload"])
        else:
            st.error(spec_error_text(active_anim_spec))

    # ==========================================================================
    # VIEW B (DEFAULT): COMBINED STATIC SPECTRA VIEW
    # ==========================================================================
    else:
        completed_active = [
            s for s in st.session_state.spectra_list
            if s["visible"] and spec_ready(s) and s["photons"]
        ]

        if not completed_active:
            if st.session_state.spectra_list:      # no message at all while there is no spectrum on the page
                with st.container(key="select_hint"):
                    st.info(tr("select_one_or_more"))
        else:
            has_multiple_spectra = (len(st.session_state.spectra_list) >= 2 and len(completed_active) >= 2)

            with st.container(key="plot_controls_row"):
                opt1, opt2, opt3, opt4, opt5 = st.columns([1.65, 1.05, 0.95, 0.95, 1.6], vertical_alignment="center")
                with opt5:
                    with st.container(key="plot_btns"):
                        render_plot_buttons()
                if not has_multiple_spectra:
                    with opt1:   # empty placeholder: the other controls must not move when the selector disappears
                        with st.container(key="display_mode_box"):
                            st.markdown("&nbsp;", unsafe_allow_html=True)

            if has_multiple_spectra:
                mode_options = ["GROUPED", "STACKED"]
                with opt1:
                    with st.container(key="display_mode_box"):
                        if st.session_state.get("plot_mode_saved") not in mode_options:
                            st.session_state["plot_mode_saved"] = "GROUPED"
                        plot_style = st.radio(
                            tr("display_mode"),
                            options=mode_options,
                            format_func=lambda m: tr("mode_grouped") if m == "GROUPED" else tr("mode_stacked"),
                            index=mode_options.index(st.session_state["plot_mode_saved"]),
                            label_visibility="collapsed"
                        )
                        st.session_state["plot_mode_saved"] = plot_style
            else:
                plot_style = "GROUPED"

            with opt2:
                with st.container(key="col_width_wedge"):
                  cw_slider_col, cw_label_col = st.columns([1.5, 1.0], vertical_alignment="center")
                  cw_label_col.markdown(
                      "<div class='cw-label'>" + "<br>".join(tr("col_width_label").split(" ", 1)) + "</div>",
                      unsafe_allow_html=True
                  )
                  with cw_slider_col:
                    width_levels = {"full": 4, "wide": 3, "medium": 2, "thin": 1}   # first option = right end (RTL slider)
                    if st.session_state.get("col_width_sel") not in width_levels:
                        st.session_state["col_width_sel"] = "medium"
                    width_choice = st.select_slider(
                        tr("col_width_label"),
                        options=list(width_levels),
                        key="col_width_sel",
                        format_func=lambda k: k,   # language-independent (the labels are hidden): switching HE/EN must not reset the slider
                        label_visibility="collapsed",
                    )
                    width_stage = width_levels[width_choice]

            # the labels change with the language (the widget is rebuilt), so the choice is remembered separately
            log_scale = opt3.checkbox(tr("log_y"), value=st.session_state.get("plot_log_saved", True))
            norm_counts = opt4.checkbox(tr("rel_intensity"), value=st.session_state.get("plot_rel_saved", False))
            st.session_state["plot_log_saved"] = log_scale
            st.session_state["plot_rel_saved"] = norm_counts

            stacked_view = (plot_style == "STACKED" and len(completed_active) > 1)
            plot_spectra = []
            for s_ in completed_active:
                e_list, c_list = spectrum_lines(s_)
                plot_spectra.append({
                    "id": s_["id"],
                    "color": s_["color"],
                    "label": f"{spec_name_unicode(s_)}   {spec_level_unicode(s_)}   (N={s_['num_muons']:,}, {s_['nuclear_model']})",
                    "e": e_list,
                    "c": c_list,
                    "total": len(s_["photons"]),
                })
            if stacked_view:
                plot_title = "Synchronized Multi-Spectrum Comparison"
            elif len(completed_active) == 1:
                s0 = completed_active[0]
                plot_title = (f"Simulated Muonic X-Ray Spectrum: {spec_name_unicode(s0)} "
                              f"(Start: {spec_level_unicode(s0)}, N={s0['num_muons']:,})")
            else:
                plot_title = "Comparative Muonic X-Ray Emission Spectrum"

            render_interactive_spectrum({
                "spectra": plot_spectra,
                "log": bool(log_scale),
                "norm": bool(norm_counts),
                "stacked": stacked_view,
                "stage": width_stage,
                "title": plot_title,
                "sig": "|".join(f"{x['id']}:{x['total']}" for x in plot_spectra),
            })


# The finished spectra have now been drawn: lets the background workers continue with stage two (animation).
for _s in st.session_state.spectra_list:
    if spec_ready(_s):
        _s["ready_rendered"] = True

# the last thing of every full run: tells the page (spinning atom) that this run has finished
st.markdown(
    f"<div class='run-marker full-marker' data-seq='{st.session_state['_run_seq']}'></div>",
    unsafe_allow_html=True
)
