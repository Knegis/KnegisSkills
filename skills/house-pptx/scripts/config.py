"""Resolve house settings and machine-specific paths for the house-pptx skill.

Brand settings (font, palette, wordmark, template) live in house.json at the skill root.
Machine paths resolve in this order:
  1. an environment variable            (override anything, e.g. in CI or a one-off run)
  2. house-pptx.json next to the skill, or ~/.house-pptx.json   (per-machine config)
  3. the value in house.json, relative to the skill root
  4. a search over the usual locations

Run `python scripts/doctor.py` to see what resolved and what is missing.

Environment variables:
  HOUSE_PPTX_TEMPLATE   full path to the .pptx template to build on
  HOUSE_PPTX_FONTDIR    directory containing the brand font files (only for a non-system font)
"""
import json
import os
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()

_DEFAULT_HOUSE = {
    "brand": "House",
    "wordmark_text": "",
    "template_supplies_chrome": False,
    "font": {"name": "Arial", "faces": {}},
    "template": "template/house_template.pptx",
    "palette": {},
    "acronyms_extra": [],
}


def _load_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_house = dict(_DEFAULT_HOUSE)
_house.update(_load_json(SKILL_ROOT / "house.json"))

_cfg = {}
for _p in (SKILL_ROOT / "house-pptx.json", HOME / ".house-pptx.json"):
    if _p.exists():
        _cfg.update(_load_json(_p))

# --- brand ------------------------------------------------------------------
BRAND = _house.get("brand") or "House"
WORDMARK_TEXT = _house.get("wordmark_text") or ""
TEMPLATE_SUPPLIES_CHROME = bool(_house.get("template_supplies_chrome", False))
PALETTE = {k: v for k, v in (_house.get("palette") or {}).items() if not k.startswith("_")}
ACRONYMS_EXTRA = [str(a).upper() for a in (_house.get("acronyms_extra") or [])]

# --- font -------------------------------------------------------------------
_font = _house.get("font") or {}
FONT_NAME = _font.get("name") or "Arial"
FONT_FACES = dict(_font.get("faces") or {})          # empty => system font, no @font-face needed
IS_SYSTEM_FONT = not FONT_FACES


def _resolve_path(env, key, house_value, candidates=(), valid=None):
    for v in (os.environ.get(env), _cfg.get(key)):
        if v and Path(v).exists() and (valid is None or valid(Path(v))):
            return Path(v)
    if house_value:
        hv = Path(house_value)
        if not hv.is_absolute():
            hv = SKILL_ROOT / hv
        if hv.exists() and (valid is None or valid(hv)):
            return hv
    for c in candidates:
        c = Path(c)
        if c.exists() and (valid is None or valid(c)):
            return c
    return None


# --- template ---------------------------------------------------------------
def _is_pptx(p):
    return p.is_file() and p.suffix.lower() == ".pptx"


_tpl_dir = SKILL_ROOT / "template"
_tpl_candidates = sorted(_tpl_dir.glob("*.pptx")) if _tpl_dir.exists() else []
TEMPLATE = _resolve_path("HOUSE_PPTX_TEMPLATE", "template", _house.get("template"),
                         _tpl_candidates, valid=_is_pptx)

# --- font directory (brand fonts only) --------------------------------------
_font_roots = [
    HOME / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
    Path("C:/Windows/Fonts"),
    HOME / "Library" / "Fonts",
    Path("/usr/share/fonts"),
    SKILL_ROOT / "fonts",
]


def _has_faces(d):
    return all((d / f).exists() for f in FONT_FACES.values())


FONT_DIR = None
if not IS_SYSTEM_FONT:
    FONT_DIR = _resolve_path("HOUSE_PPTX_FONTDIR", "font_dir", None, _font_roots, valid=_has_faces)

RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# canvas identity: 1280x720 px == 13.33in x 7.5in == 960x540 pt
CANVAS_W, CANVAS_H = 1280, 720
SHRINK = 0.94          # translator text shrink; see house_style.md section 3


def font_face_css(font_dir=None):
    """The @font-face block to embed in slide HTML. Empty for a system font."""
    if IS_SYSTEM_FONT:
        return f"/* {FONT_NAME} is a system font - no @font-face needed */"
    fd = str(font_dir or FONT_DIR or "").replace("\\", "/")
    if not fd:
        return f"/* {FONT_NAME} files not found - run scripts/doctor.py */"
    out = []
    for key, weight, italic in (("regular", 400, False), ("bold", 700, False),
                                ("italic", 400, True), ("bolditalic", 700, True)):
        f = FONT_FACES.get(key)
        if not f:
            continue
        out.append(f"@font-face{{font-family:'{FONT_NAME}';font-weight:{weight};"
                   f"{'font-style:italic;' if italic else ''}src:url('file:///{fd}/{f}');}}")
    return "\n".join(out)


def font_stack_css():
    """The font-family value for body text."""
    return f"'{FONT_NAME}',Arial,sans-serif"


def require(name, value):
    if value is None:
        raise SystemExit(
            f"house-pptx: could not locate {name}. Set the matching environment variable, edit "
            f"{SKILL_ROOT / 'house.json'}, or create {SKILL_ROOT / 'house-pptx.json'}; "
            f"then run: python scripts/doctor.py")
    return value
