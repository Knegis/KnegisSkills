"""Choose the PowerPoint template a deck is built on: the user's own, or the plain built-in one.

    python scripts/use_template.py <template.pptx|.potx> [--name "Company"] [--deck <deck folder>]
    python scripts/use_template.py --plain [--deck <deck folder>]
    python scripts/use_template.py --resume <deck folder>
    python scripts/use_template.py --show

The agent asks the user which template to use at the start of every new deck (SKILL.md) and runs this
script with the answer before designing, because the palette the slides are designed against comes from it.

What it does with the user's template:
  1. Copies it into template/ (never overwrites an existing file; adds a numeric suffix).
  2. Reads the template's theme (ppt/theme/theme1.xml): the dark/light text colours, the six accent colours
     and the major/minor fonts.
  3. Maps them onto the skill's palette ROLES (canvas, panel, text_*, dark_fill, mid_fill, secondary, marker,
     spotlight) so typecheck.py and the docs' role names now mean the template's colours.
  4. Decides whether the template's master already draws chrome (a picture or text in the top-right corner
     of the first slide master), and sets template_supplies_chrome accordingly.
  5. Picks a default layout: the layout with the fewest placeholders whose name suggests a blank/white
     content page.
  6. Writes all of that into deck-studio.json next to house.json (the MACHINE file, which overrides house.json)
     and prints the effective palette so the agent can design against it.

--plain     removes the template settings from deck-studio.json: back to the plain built-in template, Arial and
            the neutral palette in house.json.
--deck DIR  also records the choice in DIR/deck_template.json, so the deck is rebuilt on the same template later.
--resume DIR  re-applies the template recorded in DIR/deck_template.json (run it before revising a deck).
--show      prints the effective settings without changing anything.

house.json (the built-in defaults) is never modified by this script.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MACHINE = ROOT / "deck-studio.json"
KEYS_WE_WRITE = {"template", "palette", "font", "template_supplies_chrome", "default_layout", "wordmark_text",
                 "_client_template"}

_SCHEME_TAGS = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]
_SYSCLR = {"windowText": "000000", "window": "FFFFFF"}


def _hex_of(xml: str, tag: str) -> str | None:
    m = re.search(r"<a:%s>(.*?)</a:%s>" % (tag, tag), xml, re.S)
    if not m:
        return None
    body = m.group(1)
    s = re.search(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', body)
    if s:
        return s.group(1).upper()
    s = re.search(r'<a:sysClr val="(\w+)"(?: lastClr="([0-9A-Fa-f]{6})")?', body)
    if s:
        return (s.group(2) or _SYSCLR.get(s.group(1), "000000")).upper()
    return None


def _luma(h: str) -> float:
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _mix(h: str, white: float) -> str:
    """Lighten hex `h` towards white by fraction `white` (0..1)."""
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    f = lambda c: int(round(c + (255 - c) * white))
    return "%02X%02X%02X" % (f(r), f(g), f(b))


def read_theme(pptx: Path) -> dict:
    z = zipfile.ZipFile(pptx)
    names = z.namelist()
    theme = next((n for n in names if re.match(r"ppt/theme/theme\d*\.xml$", n)), None)
    if not theme:
        raise SystemExit("no theme found in %s" % pptx)
    xml = z.read(theme).decode("utf-8", "ignore")
    scheme = {t: _hex_of(xml, t) for t in _SCHEME_TAGS}
    fonts = {}
    for which in ("major", "minor"):
        m = re.search(r"<a:%sFont>.*?<a:latin typeface=\"([^\"]*)\"" % which, xml, re.S)
        fonts[which] = m.group(1) if m else ""
    return {"scheme": scheme, "fonts": fonts, "theme_part": theme}


def derive_palette(scheme: dict) -> dict:
    dk1 = scheme.get("dk1") or "000000"
    lt1 = scheme.get("lt1") or "FFFFFF"
    dk2 = scheme.get("dk2") or "373737"
    lt2 = scheme.get("lt2") or "EEEEEE"
    accents = [scheme.get("accent%d" % i) for i in range(1, 7)]
    accents = [a for a in accents if a]
    a1 = accents[0] if accents else dk2
    a2 = accents[1] if len(accents) > 1 else a1
    a3 = accents[2] if len(accents) > 2 else a2
    # Text colours stay in the dark/grey family: role rule "text is black, white or grey" holds for any brand.
    return {
        "canvas": "#" + lt1,
        "panel": "#" + (lt2 if _luma(lt2) > 200 else _mix(lt2, 0.6)),
        "panel_alt": "#" + _mix(a1, 0.85),
        "text_primary": "#" + dk1,
        "text_primary_alt": "#" + _mix(dk1, 0.12),
        "text_secondary": "#" + _mix(dk1, 0.35),
        "text_secondary_alt": "#" + _mix(dk1, 0.5),
        "text_caption": "#" + _mix(dk1, 0.62),
        "dark_fill": "#" + (dk2 if _luma(dk2) < 110 else dk1),
        "mid_fill": "#" + a1,
        "mid_fill_alt": "#" + _mix(a1, 0.3),
        "light_fill": "#" + _mix(a1, 0.65),
        "light_fill_alt": "#" + _mix(a1, 0.75),
        "secondary": "#" + a2,
        "marker": "#" + a3,
        "spotlight": "#" + (accents[3] if len(accents) > 3 else a3),
        "alt_canvas": "#" + _mix(lt2, 0.5),
    }


def master_draws_chrome(pptx: Path) -> bool:
    """True if the first slide master (or its layouts) places a picture or text box in the top-right corner."""
    z = zipfile.ZipFile(pptx)
    parts = [n for n in z.namelist() if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", n)]
    sldsz = re.search(r'<p:sldSz cx="(\d+)" cy="(\d+)"', z.read("ppt/presentation.xml").decode("utf-8", "ignore"))
    cx, cy = (int(sldsz.group(1)), int(sldsz.group(2))) if sldsz else (12192000, 6858000)
    for p in parts:
        xml = z.read(p).decode("utf-8", "ignore")
        for m in re.finditer(r'<a:off x="(\d+)" y="(\d+)"/><a:ext cx="(\d+)" cy="(\d+)"', xml):
            x, y, w, h = map(int, m.groups())
            if x + w > cx * 0.85 and y < cy * 0.12 and w < cx * 0.3 and h < cy * 0.2:
                return True
    return False


def pick_default_layout(pptx: Path) -> str:
    z = zipfile.ZipFile(pptx)
    best = None
    for n in z.namelist():
        if not re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n):
            continue
        xml = z.read(n).decode("utf-8", "ignore")
        name = re.search(r'<p:cSld name="([^"]*)"', xml)
        name = name.group(1) if name else n
        ph = len(re.findall(r"<p:ph\b", xml))
        low = name.lower()
        score = ph - (3 if any(k in low for k in ("blank", "no content", "empty")) else 0) \
                   - (1 if any(k in low for k in ("white", "light")) else 0)
        if best is None or score < best[0]:
            best = (score, name)
    return best[1] if best else ""


def load_machine() -> dict:
    if MACHINE.exists():
        try:
            return json.loads(MACHINE.read_text(encoding="utf-8"))
        except ValueError as e:
            raise SystemExit("deck-studio.json is not valid JSON: %s" % e)
    return {}


def show():
    sys.path.insert(0, str(HERE))
    import config as C  # noqa: E402
    print("template:", C.TEMPLATE)
    print("font:", C.FONT_NAME)
    print("template_supplies_chrome:", getattr(C, "TEMPLATE_SUPPLIES_CHROME", None))
    print("default_layout:", getattr(C, "DEFAULT_LAYOUT", ""))
    print("palette:")
    for k, v in C.PALETTE.items():
        print("  %-18s %s" % (k, v))
    print("machine file:", MACHINE if MACHINE.exists() else "(none - plain defaults from house.json)")


def active_label() -> str:
    """One line naming the active template, for the agent to quote when it asks the user."""
    m = load_machine()
    ct = m.get("_client_template")
    if ct and m.get("template"):
        return "%s (%s)" % (ct.get("client") or Path(m["template"]).stem, m["template"])
    return "plain built-in template (template/plain_template.pptx)"


DECK_FILE = "deck_template.json"


def record_for_deck(deck: Path, kind: str):
    """Write <deck>/deck_template.json so a later revision can --resume the same template."""
    deck.mkdir(parents=True, exist_ok=True)
    m = load_machine()
    rec = {"kind": kind}
    if kind == "custom":
        rec.update({"template": m.get("template"), "name": (m.get("_client_template") or {}).get("client"),
                    "source": (m.get("_client_template") or {}).get("source")})
    (deck / DECK_FILE).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print("Recorded for this deck: %s" % (deck / DECK_FILE))


def resume(deck: Path):
    f = deck / DECK_FILE
    if not f.exists():
        raise SystemExit("%s not found: this deck has no recorded template. Ask the user which template to use, "
                         "then run  use_template.py <file> --deck %s  or  use_template.py --plain --deck %s"
                         % (f, deck, deck))
    rec = json.loads(f.read_text(encoding="utf-8"))
    if rec.get("kind") == "plain":
        return back_to_plain()
    tpl = ROOT / (rec.get("template") or "")
    src = tpl if rec.get("template") and tpl.exists() else Path(rec.get("source") or "")
    if not src.is_file():
        raise SystemExit("the template recorded for this deck is gone (%s, source %s). Ask the user for it again."
                         % (rec.get("template"), rec.get("source")))
    switch(src, rec.get("name"))


def back_to_plain():
    m = load_machine()
    if not m:
        print("Already on the plain built-in template (no deck-studio.json).")
        return
    rest = {k: v for k, v in m.items() if k not in KEYS_WE_WRITE}
    if rest:
        MACHINE.write_text(json.dumps(rest, indent=2), encoding="utf-8")
        print("Removed template settings from deck-studio.json; kept machine keys: %s" % ", ".join(rest))
    else:
        MACHINE.unlink()
        print("Deleted deck-studio.json.")
    print("Back on the plain built-in template, Arial and the neutral palette from house.json.")


def switch(src: Path, client_name: str | None):
    if not src.exists():
        raise SystemExit("not found: %s" % src)
    if src.suffix.lower() not in (".pptx", ".potx"):
        raise SystemExit("expected a .pptx or .potx template: %s" % src)
    tdir = ROOT / "template"
    tdir.mkdir(exist_ok=True)
    dest = tdir / (re.sub(r"[^A-Za-z0-9_.-]+", "_", src.stem) + ".pptx")
    i = 2
    while dest.exists() and dest.resolve() != src.resolve():
        dest = tdir / ("%s_%d.pptx" % (re.sub(r"[^A-Za-z0-9_.-]+", "_", src.stem), i))
        i += 1
    if dest.resolve() != src.resolve():
        shutil.copyfile(src, dest)
    theme = read_theme(dest)
    palette = derive_palette(theme["scheme"])
    chrome = master_draws_chrome(dest)
    layout = pick_default_layout(dest)
    font = theme["fonts"]["minor"] or theme["fonts"]["major"] or "Arial"
    if font.startswith("+"):
        font = "Arial"
    m = load_machine()
    m.update({
        "_client_template": {"source": str(src), "client": client_name or src.stem},
        "template": str(dest.relative_to(ROOT)).replace("\\", "/"),
        "palette": palette,
        "font": {"name": font, "faces": {}},
        "template_supplies_chrome": chrome,
        "default_layout": layout,
        "wordmark_text": "",
    })
    MACHINE.write_text(json.dumps(m, indent=2), encoding="utf-8")
    print("Switched to template: %s" % dest.name)
    print("  theme fonts : major=%s minor=%s -> house font %s" % (theme["fonts"]["major"], theme["fonts"]["minor"], font))
    print("  chrome      : master draws top-right chrome = %s -> template_supplies_chrome=%s" % (chrome, chrome))
    print("  layout      : default '%s'" % layout)
    print("  palette (roles -> template theme):")
    for k, v in palette.items():
        print("    %-18s %s" % (k, v))
    print("Design against these role colours; typecheck.py now enforces them. Back to the plain template: python scripts/use_template.py --plain")
    print("NOTE: if the template font is not installed on this machine, PowerPoint will substitute it; install it or set font.name in deck-studio.json.")


def _take(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        v = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
        return v
    return None


def main(argv):
    argv = list(argv)
    if "--help" in argv or "-h" in argv or not argv:
        print(__doc__)
        sys.exit(2)
    if argv[0] == "--show":
        print("active template:", active_label())
        return show()
    if argv[0] == "--resume":
        if len(argv) < 2:
            raise SystemExit("usage: use_template.py --resume <deck folder>")
        return resume(Path(argv[1]))
    deck = _take(argv, "--deck")
    if argv and argv[0] == "--plain":
        back_to_plain()
        if deck:
            record_for_deck(Path(deck), "plain")
        return
    name = _take(argv, "--name")
    if not argv:
        raise SystemExit("usage: use_template.py <template.pptx> [--name N] [--deck DIR]")
    switch(Path(argv[0]), name)
    if deck:
        record_for_deck(Path(deck), "custom")


if __name__ == "__main__":
    main(sys.argv[1:])
