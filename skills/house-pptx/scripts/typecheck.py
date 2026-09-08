"""Mechanically check a constrained-HTML slide against the house style.

Usage:  python typecheck.py <slide.html>          (extracts geometry, then checks)
        python typecheck.py <geom.json>           (checks an already-extracted geom)
        python typecheck.py <slide.html> --quiet   (only FAIL/WARN lines)

Checks what agents have repeatedly got wrong from memory: delivered font sizes (px authoring vs
pt spec, incl. the 0.94 translator shrink), whole/.5pt snapping, type variety, non-grey text
colour, ALL CAPS, letter-spacing, em dashes, emojis, canvas usage, and stray full-bleed rects.

Exit code 1 if any FAIL. Rules and rationale: ../house_style.md
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as _cfg  # noqa: E402

SHRINK = 0.94                    # must match html_to_pptx.SHRINK
CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 24

# delivered pt values the house scale lands on (house_style.md section 3)
SCALE = {7.5, 8, 9, 9.5, 10, 10.5, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32, 40, 54}
GREY_TOL = 16                    # max-min channel spread still counted as black/white/grey/taupe
# true pictographic emoji only. Arrows (U+2190-21FF) and typographic marks like the tick are
# legitimate slide furniture and must NOT be flagged.
EMOJI = re.compile("[🀀-🫿☀-➿️]")
EMOJI_OK = set("✓✔✗✘✚✱※")
ACRONYMS = {"AI", "KPI", "NPS", "CMS", "OPCO", "EBITDA", "CDD", "FDD", "IM", "M&A", "SME",
            "TAM", "SAM", "SOM", "ROI", "CAGR", "B2B", "B2C", "UK", "US", "EU", "IT", "HR", "DACH",
            "CEO", "CFO", "CTO", "COO", "MNOK", "MSEK", "PMI", "SaaS", "AND", "THE", "FOR", "OR",
            "ESG", "IPO", "LTM", "YTD", "FTE", "GDP", "R&D", "UX", "API", "ERP", "CRM",
            # currency codes - house style mandates the "4.6 MEUR" form, so these are correct
            "MEUR", "KEUR", "EUR", "SEK", "NOK", "DKK", "USD", "GBP", "CHF", "TEUR", "MUSD",
            # brand names genuinely styled in capitals come from house.json -> acronyms_extra
            *_cfg.ACRONYMS_EXTRA}

# fills whose use as a coloured LEFT border is flagged (house.json palette roles)
_ACCENT_HEX = [v.lstrip("#") for k, v in _cfg.PALETTE.items()
               if k in ("secondary", "marker", "spotlight") and isinstance(v, str)]

fails, warns, notes = [], [], []


def _shout(txt):
    """Letters left in an upper-case run once recognised acronyms are removed, token by token.

    The whole-run comparison against ACRONYMS above never fires on real text: "198 MSEK" and
    "42 MSEK of 1,112" are house style, not shouting, but neither equals "MSEK". Counting only
    the residue means a genuine caps sentence still fails while a figure with its unit passes.
    """
    rest = [w for w in re.split(r"[^A-Za-z&]+", txt) if w and w.upper() not in ACRONYMS]
    return sum(len(w) for w in rest)


def delivered_pt(px_size):
    """px in the HTML -> pt actually written into the .pptx (mirrors html_to_pptx.pt100)."""
    return round(px_size * 0.75 * SHRINK * 2) * 50 / 100.0


def author_px(target_pt):
    return round(target_pt / (0.75 * SHRINK) * 2) / 2


def is_greyscale(css_color):
    m = re.match(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", css_color or "")
    if not m:
        return True                                   # can't parse -> don't cry wolf
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    return (max(r, g, b) - min(r, g, b)) <= GREY_TOL


def iter_runs(texts):
    """Yield every run from both grouped (.pgroup) and plain text boxes."""
    for t in texts:
        if t.get("grouped"):
            for p in t.get("gparas", []):
                for r in p.get("runs", []):
                    yield t, r
        else:
            for p in t.get("paras", []):
                for r in p:
                    yield t, r


def load(path):
    p = Path(path)
    if p.suffix.lower() == ".json":
        return json.loads(p.read_text(encoding="utf-8"))
    out = Path(tempfile.gettempdir()) / (p.stem + "._typecheck.json")
    r = subprocess.run([sys.executable, str(HERE / "extract_geometry.py"), str(p), str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print("FAIL  geometry extraction failed:\n" + (r.stderr or r.stdout)[-1500:])
        sys.exit(1)
    return json.loads(out.read_text(encoding="utf-8"))


def check(data, src_text=""):
    texts, rects = data.get("texts", []), data.get("rects", [])
    runs = list(iter_runs(texts))
    if not runs:
        fails.append("no text found - is this a real slide?")
        return

    # ---- 1. type scale -------------------------------------------------------
    sizes = {}
    for t, r in runs:
        sizes.setdefault(round(r["size"], 2), []).append(r["t"][:40])
    notes.append("font sizes in use (author px -> delivered pt):")
    for pxs in sorted(sizes, reverse=True):
        pt = delivered_pt(pxs)
        tag = ""
        if pt * 2 != int(pt * 2):
            tag = "  <-- FAIL not a whole/.5 pt value"
            fails.append(f"{pxs}px delivers {pt}pt - PowerPoint sizes must be whole or .5pt "
                         f"(nearest clean: {author_px(round(pt * 2) / 2)}px)")
        elif pt not in SCALE:
            tag = "  <-- off the house scale"
            warns.append(f"{pxs}px delivers {pt}pt, which is off the house scale - "
                         f"intended? nearest: {min(SCALE, key=lambda s: abs(s - pt))}pt "
                         f"({author_px(min(SCALE, key=lambda s: abs(s - pt)))}px)")
        notes.append(f"    {pxs:>6}px -> {pt:>5}pt  x{len(sizes[pxs]):<3} e.g. {sizes[pxs][0]!r}{tag}")

    biggest = max(sizes)
    if delivered_pt(biggest) < 20:
        warns.append(f"largest text is only {delivered_pt(biggest)}pt ({biggest}px). Titles default to "
                     f"24pt = 34px. Small type is for genuinely tight slides, not a default.")
    smallest = min(sizes)
    if delivered_pt(smallest) < 7.5:
        warns.append(f"smallest text is {delivered_pt(smallest)}pt ({smallest}px) - below the 7.5pt floor.")

    # ---- 2. type variety -----------------------------------------------------
    styles = {(round(r["size"], 1), r["weight"] >= 600, bool(r.get("italic"))) for _, r in runs}
    if len(styles) < 5:
        warns.append(f"only {len(styles)} distinct type styles (size/weight/italic). "
                     f"A content slide should carry 5+ - see depth_rubric.md section 2.")
    else:
        notes.append(f"type styles: {len(styles)} distinct (>=5 OK)")

    # ---- 3. colour, caps, tracking, dashes, emoji ----------------------------
    bad_col, caps, caps_soft, ls_hits, dashes, emoji = {}, [], [], [], [], []
    for _, r in runs:
        txt = r["t"]
        if not is_greyscale(r.get("color", "")):
            bad_col.setdefault(r.get("color"), []).append(txt[:40])
        letters = [c for c in txt if c.isalpha()]
        if (r.get("upper") or (letters and "".join(letters).isupper())) and len(letters) > 3 \
                and txt.strip().upper() not in ACRONYMS and _shout(txt) > 3:
            caps.append(txt[:50])
        if r.get("ls"):
            ls_hits.append((txt[:30], r["ls"]))
        if "—" in txt or "–" in txt:
            dashes.append(txt[:50])
        hit = [c for c in EMOJI.findall(txt) if c not in EMOJI_OK]
        if hit:
            emoji.append(txt[:50])

    for col, ex in bad_col.items():
        fails.append(f"non-grey text colour {col} on {len(ex)} run(s), e.g. {ex[0]!r}. "
                     f"Text is black/white/grey only; accents are fills, emphasis is bold.")
    for c in caps:
        fails.append(f"ALL CAPS text: {c!r} - use sentence case.")
    for c in caps_soft:
        warns.append(f"all-caps token {c!r} - fine if it is a brand or acronym, otherwise "
                     f"use sentence case. Add it to ACRONYMS in typecheck.py to silence this.")
    for txt, v in ls_hits:
        fails.append(f"letter-spacing {v} on {txt!r} - tracking stays normal.")
    for d in dashes:
        fails.append(f"em/en dash in {d!r} - hyphens only.")
    for e in emoji:
        fails.append(f"emoji in {e!r} - never in house output.")

    # ---- 4. canvas usage -----------------------------------------------------
    # zero-area boxes (display:none wrappers, empty divs) must not skew the bounding box
    boxes = [(b["x"], b["y"], b["w"], b["h"]) for b in rects + texts
             if b["w"] > 1 and b["h"] > 1]
    full = [b for b in boxes if b[0] <= 0.5 and b[1] <= 0.5
            and b[2] >= CANVAS_W - 1 and b[3] >= CANVAS_H - 1]
    inner = [b for b in boxes if b not in full]
    if inner:
        left = min(b[0] for b in inner)
        right = max(b[0] + b[2] for b in inner)
        bottom = max(b[1] + b[3] for b in inner)
        notes.append(f"content box: left {left:.0f}px, right {right:.0f}px, bottom {bottom:.0f}px")
        if left > MARGIN + 2:
            warns.append(f"leftmost content at {left:.0f}px - the margin is {MARGIN}px "
                         f"(you are losing {left - MARGIN:.0f}px of canvas).")
        if right < CANVAS_W - MARGIN - 8:
            warns.append(f"content stops at {right:.0f}px, short of the {CANVAS_W - MARGIN}px right margin - "
                         f"{CANVAS_W - MARGIN - right:.0f}px of dead width. Grow the objects, not the whitespace.")
        if bottom < 660:
            warns.append(f"content ends at {bottom:.0f}px, leaving a {CANVAS_H - bottom:.0f}px dead band. "
                         f"Fill to ~690px: grow objects, then type, then add a register (house_style.md section 2).")
    if len(full) > 1:
        warns.append(f"{len(full)} full-bleed rects - the bottom one becomes the slide background; "
                     f"any others are real objects. Intentional scrim, or a leftover?")

    # ---- 4b. collisions and overflow ----------------------------------------
    # These recurred on every slide of a real deck (Sept 2026): title over wordmark,
    # legend swatches over their labels, text spilling out of its band. All are visible
    # in the browser but easy to miss, and all are cheap to detect here.
    def area(b):
        return max(0.0, b[2]) * max(0.0, b[3])

    def overlap(a, b):
        w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        return max(0.0, w) * max(0.0, h)

    def label(t):
        for p in (t.get("gparas") or []):
            for r in p.get("runs", []):
                if r["t"].strip():
                    return r["t"].strip()[:34]
        for p in (t.get("paras") or []):
            for r in p:
                if r["t"].strip():
                    return r["t"].strip()[:34]
        return "(empty)"

    tboxes = [(t, (t["x"], t["y"], t["w"], t["h"])) for t in texts
              if t["w"] > 1 and t["h"] > 1]

    # text on text
    seen_pairs = 0
    for i in range(len(tboxes)):
        for j in range(i + 1, len(tboxes)):
            ta, ba = tboxes[i]
            tb, bb = tboxes[j]
            ov = overlap(ba, bb)
            if ov < 120:                                   # ignore hairline touches
                continue
            if ov < 0.12 * min(area(ba), area(bb)):
                continue
            seen_pairs += 1
            if seen_pairs <= 6:
                warns.append(f"text overlaps text: {label(ta)!r} and {label(tb)!r} "
                             f"share {ov:.0f}px2 - they will collide in PowerPoint.")
    if seen_pairs > 6:
        warns.append(f"...and {seen_pairs - 6} further text-on-text overlaps.")

    # the top-right chrome zone. When the template master supplies a logo there, .wordmark /
    # .pg are dropped in translation, so a title running under the logo never shows up as a
    # text-on-text overlap - it only appears in the final PowerPoint render. Only checked when
    # house.json says template_supplies_chrome; otherwise the wordmark is a normal text box and
    # the text-on-text check above already covers it.
    # zone starts at 1190: the house title width (left 24, width ~1160 -> right 1184) must
    # stay clean, while a full-width 1232px title (right 1256) is the case worth flagging.
    CHROME = (1190, 16, 90, 56)
    if _cfg.TEMPLATE_SUPPLIES_CHROME:
        for t, b in tboxes:
            if t.get("cls") and any(c in ("wordmark", "pg") for c in str(t["cls"]).split()):
                continue
            if overlap(b, CHROME) > 150:
                warns.append(f"text runs into the top-right chrome zone: {label(t)!r}. The master "
                             f"supplies the logo there, so this collides only in PowerPoint, "
                             f"not in the browser. Keep titles to ~1160px wide (right edge 1184).")

    # text outside the canvas
    for t, b in tboxes:
        if b[0] < -1 or b[1] < -1 or b[0] + b[2] > CANVAS_W + 1 or b[1] + b[3] > CANVAS_H + 1:
            warns.append(f"text runs off the canvas: {label(t)!r} at "
                         f"({b[0]:.0f},{b[1]:.0f}) {b[2]:.0f}x{b[3]:.0f}px.")

    # text overflowing the filled box it sits in (bands, panels, cards)
    panels = [(r["x"], r["y"], r["w"], r["h"]) for r in rects
              if r.get("fill") and r["w"] > 40 and r["h"] > 20
              and not (r["x"] <= 0.5 and r["y"] <= 0.5
                       and r["w"] >= CANVAS_W - 1 and r["h"] >= CANVAS_H - 1)]
    for t, b in tboxes:
        inside = [p for p in panels
                  if p[0] - 2 <= b[0] and p[1] - 2 <= b[1]
                  and b[0] < p[0] + p[2] and b[1] < p[1] + p[3]]
        if not inside:
            continue
        host = min(inside, key=area)
        spill_r = (b[0] + b[2]) - (host[0] + host[2])
        spill_b = (b[1] + b[3]) - (host[1] + host[3])
        if spill_b > 2 or spill_r > 2:
            warns.append(f"text spills out of its panel: {label(t)!r} overflows by "
                         f"{max(0, spill_r):.0f}px right / {max(0, spill_b):.0f}px bottom - "
                         f"grow the panel or shorten the text.")

    # ---- 5. source text greps ------------------------------------------------
    if src_text:
        if re.search(r"::?before\s*\{[^}]*content\s*:", src_text):
            fails.append("CSS ::before with content - pseudo-elements are dropped in translation. "
                         "Use a real sibling <div> (see html_pipeline.md).")
        if re.search(r"<svg", src_text, re.I):
            fails.append("inline <svg> - dropped entirely in translation. Rebuild with divs, "
                         "or rasterise to <img> (see html_pipeline.md).")
        if re.search(r"text-transform\s*:\s*uppercase", src_text, re.I):
            fails.append("text-transform:uppercase - sentence case only.")
        # only genuinely COLOURED left rules. Neutral hairline left-rules on cards are a legitimate
        # house construction, so flagging those would be a false positive.
        if _ACCENT_HEX and re.search(r"border-left\s*:\s*[^;]*(" + "|".join(_ACCENT_HEX) + ")", src_text, re.I):
            warns.append("coloured border-left accent on a text block or card - house style highlights "
                         "with a tinted background wash instead. (A neutral grey/black hairline rule is fine.)")


def main():
    # Windows consoles default to cp1252 and blow up on arrows / curly quotes in slide copy.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    path = Path(sys.argv[1])
    quiet = "--quiet" in sys.argv
    src = path.read_text(encoding="utf-8", errors="ignore") if path.suffix.lower() == ".html" else ""
    check(load(path), src)

    print(f"\n=== typecheck: {path.name} ===")
    if not quiet:
        for n in notes:
            print("      " + n)
    for w in warns:
        print("WARN  " + w)
    for f in fails:
        print("FAIL  " + f)
    print(f"\n{len(fails)} fail / {len(warns)} warn"
          + ("   -> PASS\n" if not fails else "   -> FIX THE FAILS\n"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
