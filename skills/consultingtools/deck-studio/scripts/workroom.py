"""Build the browser workroom for a deck - one HTML page that is the focal point for all
review of that deck's slides.

Usage:
  python workroom.py <dir>                                    # regenerate <dir>/workroom.html
  python workroom.py <dir> --open                              # ...and open it in the default browser
  python workroom.py <dir> --title "Name"                      # set the deck name shown in the header
  python workroom.py <dir> --serve [--port 8765] [--open]      # serve a live, editable workroom
  python workroom.py <dir> --serve --idle-hours 4             # stop after 4 h without requests (0 = never)

Every slide HTML in <dir> is wrapped (font + canvas boilerplate) and embedded in its own iframe, so
slides cannot leak CSS into each other and each one still opens standalone. Zoom controls switch
between full size, half size and a contact-sheet grid, which replaces the old PNG contact sheet for
human review.

--serve starts a local HTTP server (127.0.0.1 only) that turns the static page into a live review
tool: archive/restore slides, leave round-numbered comments, reorder the build sequence, and build
the deck (and render it through PowerPoint) from the browser. State lives in
<dir>/workroom_state.json, written only by the server in response to clicks - never by build
scripts. See PIPELINE.md for the review loop this supports. The server stops by itself after
--idle-hours (default 2) without any request and with no build running, so a forgotten review
round does not leave a process behind; Ctrl+C stops it at once.
If port 8765 is taken it moves to the next free port and prints the URL; if a server is already
running for the same deck it reuses that one (opens the browser on it and exits).

NOTE for agents: you cannot see a browser. Keep rendering PNGs (render_html.py / render_slides.py)
for your own QA - this page is for the human. Delete those PNGs when done; this page is what persists.
"""
import hashlib
import html
import http.server
import json
import mimetypes
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _cli                                 # noqa: E402 - shared --help / arg-count handling
import analysis                             # Analysis tab: sidecar + Excel-range reads; see scripts/analysis.py
import config as _cfg                       # house settings + machine paths; see scripts/config.py
import ledger                               # feedback ledger; see scripts/ledger.py
FONT_CSS = _cfg.font_face_css()             # a CSS comment for a system font
FONT_STACK = _cfg.font_stack_css()
CHART_JS = (HERE / "chart_preview.js").read_text(encoding="utf-8")   # draws .ppt-chart boxes for the human; never reaches the .pptx

STATE_FILENAME = "workroom_state.json"
LAB_ROOT = HERE.parent
REFERENCE_DIR = LAB_ROOT / "reference"      # roadmap 2.3 "promote to reference" writes here - see _handle_promote
MSGTYPES = ("cover", "end", "statement", "credentials", "contrast", "trend", "composition",
            "evidence", "org", "decomposition", "comparison", "roadmap", "operatingmodel",
            "system", "triangulation", "other")

WRAP = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
{fontcss}
*{{box-sizing:border-box;}}
html,body{{margin:0;padding:0;width:1280px;height:720px;overflow:hidden;background:#fff;font-family:{stack};}}
.variant-label{{display:none;}}
.slide{{width:1280px;height:720px;position:relative;overflow:hidden;margin:0;}}
table{{border-collapse:collapse;}}
</style></head><body>
{body}
<script>{chartjs}</script>
</body></html>"""


# ============================================================================
# Shared helpers (static mode and server mode both use these)
# ============================================================================

def is_slide(path):
    if path.name.startswith("_") or path.name == "workroom.html":
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:200000]
    except OSError:
        return False
    return 'class="slide"' in head or "class='slide'" in head


def fragment_of(text):
    """Strip an html/head/body wrapper if present, keeping <style> blocks and the slide markup."""
    m = re.search(r"<body[^>]*>(.*)</body>", text, re.S | re.I)
    body = m.group(1) if m else text
    # keep any <style> that lived in <head>
    if m:
        head = text[:m.start()]
        body = "".join(re.findall(r"<style[^>]*>.*?</style>", head, re.S | re.I)) + body
    return body


def title_of(text, fallback):
    for pat in (r'class="title"[^>]*>(.*?)</div>', r"<title>(.*?)</title>"):
        m = re.search(pat, text, re.S | re.I)
        if m:
            t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if t and "variant preview" not in t.lower():
                return t[:120]
    return fallback


def vid_of(fname):
    return re.split(r"[_.]", Path(fname).stem)[0][:14]


# ---------------------------------------------------------------- image reference rewriting
#
# Slides reference pictures three ways (PIPELINE.md "Images"): an absolute file:/// URL, a bare
# absolute local path, or a path relative to the slide's own HTML file. All three work when the
# .pptx is built (build_deck.py runs the extractor against the original slide file on disk) and
# when workroom.html is opened as a file:// page itself (file-to-file loads fine). But a page
# served over http://127.0.0.1 cannot load file:// URLs at all, and a relative path stops
# resolving once the slide is wrapped into _workroom/ (one directory down from the slide). So the
# wrapped _workroom/ copies need their image references rewritten - see _rewrite_image_refs.
IMG_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"}
# The brand @font-face block (config.font_face_css()) has exactly the same file:/// problem as
# images - see _server_font_css below - so the /file route also serves font files. mimetypes
# does not reliably know these extensions, so they get an explicit Content-Type.
FONT_EXTS = {"otf", "ttf", "woff", "woff2"}
ASSET_EXTS = IMG_EXTS | FONT_EXTS
_FONT_CONTENT_TYPES = {"otf": "font/otf", "ttf": "font/ttf", "woff": "font/woff", "woff2": "font/woff2"}

_SRC_DQ = re.compile(r'(\bsrc\s*=\s*")([^"]*)(")', re.I)
_SRC_SQ = re.compile(r"(\bsrc\s*=\s*')([^']*)(')", re.I)
_CSS_URL = re.compile(r'(url\(\s*)([\'"]?)([^\'")]+)(\2)(\s*\))', re.I)


def _classify_ref(u):
    """Return (kind, value) for a src=/url(...) reference, or None if it should be left alone
    (data:, http(s), an in-page anchor, or empty)."""
    u = (u or "").strip()
    if not u or u.startswith("#") or u.lower().startswith("data:"):
        return None
    low = u.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return None
    if low.startswith("file:///"):
        return "file", urllib.parse.unquote(u[8:])
    if low.startswith("file://"):
        return "file", urllib.parse.unquote(u[7:])
    if re.match(r"^[A-Za-z]:[\\/]", u):
        return "abs", u
    return "rel", u


def _file_route_url(path):
    return "/file?p=" + urllib.parse.quote(str(path), safe="")


def _server_font_css():
    """A serve-mode variant of config.font_face_css(): the same @font-face rules FONT_CSS
    carries, but each font file is reached through /file?p=... instead of a file:/// URL - a
    page served over http cannot load file:// URLs any more than it can for a slide's own
    images (see _rewrite_image_refs). Used for both the wrapped slide copies and the workroom
    page's own chrome, so the rail/header render in the house font too. Static mode keeps using
    the module-level FONT_CSS unchanged - file-to-file loading works there."""
    if _cfg.IS_SYSTEM_FONT or not _cfg.FONT_DIR:
        return FONT_CSS
    out = []
    for key, weight, italic in (("regular", 400, False), ("bold", 700, False),
                                 ("italic", 400, True), ("bolditalic", 700, True)):
        f = _cfg.FONT_FACES.get(key)
        if not f:
            continue
        path = Path(_cfg.FONT_DIR) / f
        out.append("@font-face{font-family:'%s';font-weight:%d;%ssrc:url('%s');}" % (
            _cfg.FONT_NAME, weight, "font-style:italic;" if italic else "", _file_route_url(path)))
    return "\n".join(out)


SERVER_FONT_CSS = _server_font_css()


def _rewrite_image_refs(text, mode, slide_dir=None):
    """Rewrite every src=/url(...) image reference in a slide fragment (body + any <style>
    block) for the given mode:

    mode="serve" - file:///, bare absolute paths, and paths relative to `slide_dir` all become
    /file?p=<abs path>, served by the workroom HTTP server's /file route.

    mode="static" - file:/// and bare absolute paths are left as-is (file-to-file loading
    works); a relative path is rewritten to ../<path> so it still resolves from _workroom/,
    one directory below the slide. A slide with no relative image references is returned
    byte-identical.
    """

    def handle(u):
        ref = _classify_ref(u)
        if ref is None:
            return None
        kind, value = ref
        if mode == "serve":
            if kind == "rel":
                value = str((slide_dir / value).resolve())
            return _file_route_url(value)
        if kind == "rel":
            return "../" + value
        return None  # static mode: file:// and bare absolute paths already work

    def sub_attr(m):
        new = handle(m.group(2))
        return m.group(1) + (new if new is not None else m.group(2)) + m.group(3)

    def sub_url(m):
        new = handle(m.group(3))
        return m.group(1) + m.group(2) + (new if new is not None else m.group(3)) + m.group(4) + m.group(5)

    text = _SRC_DQ.sub(sub_attr, text)
    text = _SRC_SQ.sub(sub_attr, text)
    text = _CSS_URL.sub(sub_url, text)
    return text


def build_workroom_copies(d, slides, mode="static"):
    """(Re)write d/_workroom/<slide>.html wrapped copies for the given list of slide Paths.
    Deletes every existing wrapped copy first, same as the original static-mode behaviour, so
    a slide removed from `slides` never leaves a stale copy behind. `mode` controls image
    reference rewriting - see _rewrite_image_refs."""
    work = d / "_workroom"
    work.mkdir(exist_ok=True)
    for old in work.glob("*.html"):
        old.unlink()
    fontcss = SERVER_FONT_CSS if mode == "serve" else FONT_CSS
    for p in slides:
        text = p.read_text(encoding="utf-8", errors="ignore")
        body = _rewrite_image_refs(fragment_of(text), mode, slide_dir=p.parent)
        (work / p.name).write_text(
            WRAP.format(fontcss=fontcss, stack=FONT_STACK, body=body, chartjs=CHART_JS),
            encoding="utf-8")


def _open_in_browser(target):
    """Open `target` (a Path or a URL string) in the user's real default browser, on any
    platform. Not an in-app browser pane: those are sandboxed to a project folder and fail on
    files written elsewhere. Falls back to webbrowser, then prints the target for the user."""
    import platform
    url = target.as_uri() if isinstance(target, Path) else str(target)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(["powershell", "-NoProfile", "-Command", f'Start-Process "{url}"'],
                           check=True, capture_output=True)
        elif system == "Darwin":
            subprocess.run(["open", url], check=True, capture_output=True)
        else:
            subprocess.run(["xdg-open", url], check=True, capture_output=True)
        return
    except Exception:  # noqa: BLE001 - any failure falls through to the portable path
        pass
    try:
        import webbrowser
        if webbrowser.open(url):
            return
    except Exception:  # noqa: BLE001
        pass
    print("  could not open a browser automatically - open this yourself:")
    print(f"  {url}")


# ============================================================================
# Static mode: python workroom.py <dir> [--open] [--title X]
# ============================================================================

def write_static(d, deck, open_browser):
    slides = sorted([p for p in d.glob("*.html") if is_slide(p)])
    if not slides:
        print(f"no slide HTML found in {d} (looking for files containing class=\"slide\")")
        sys.exit(1)

    build_workroom_copies(d, slides)

    rail, panes = [], []
    for i, p in enumerate(slides, 1):
        text = p.read_text(encoding="utf-8", errors="ignore")
        vid = vid_of(p.name)        # V44, slide1, etc - keeps the rail scannable
        ttl = html.escape(title_of(text, p.stem))
        rail.append(
            f'<a class="railitem" href="#s{i}"><span class="rn">{html.escape(vid)}</span>'
            f'<span class="rt">{ttl}</span></a>')
        panes.append(f"""<section class="pane" id="s{i}">
  <div class="cap">
    <span class="idx">{i}</span>
    <span class="vid">{html.escape(vid)}</span>
    <span class="ttl">{ttl}</span>
    <span class="fn">{html.escape(p.name)}</span>
  </div>
  <div class="frame"><iframe src="_workroom/{html.escape(p.name)}" scrolling="no" loading="lazy"></iframe></div>
</section>""")

    chartnote = (" &middot; charts are previews; the PowerPoint render is the reference"
                 if any("ppt-chart" in p.read_text(encoding="utf-8", errors="ignore")
                        for p in slides) else "")
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{html.escape(deck)} - workroom</title><style>
{FONT_CSS}
*{{box-sizing:border-box;}}
body{{margin:0;font-family:{FONT_STACK};background:#EEEEEE;color:#1E1E1E;}}
header{{position:sticky;top:0;z-index:20;background:#FFFFFF;border-bottom:1px solid #BFBFBF;
  padding:12px 20px;display:flex;align-items:baseline;gap:16px;}}
header h1{{font-size:17px;margin:0;font-weight:700;}}
header .meta{{font-size:12px;color:#7F7F7F;}}
header .zooms{{margin-left:auto;display:flex;gap:6px;}}
header button{{font-family:inherit;font-size:12px;padding:5px 12px;border:1px solid #BFBFBF;
  background:#fff;cursor:pointer;color:#1E1E1E;}}
header button.on{{background:#373737;color:#fff;border-color:#373737;}}
.wrap{{display:flex;align-items:flex-start;}}
nav{{position:sticky;top:53px;width:260px;flex:0 0 260px;max-height:calc(100vh - 53px);overflow:auto;
  background:#fff;border-right:1px solid #BFBFBF;padding:10px 0;}}
.railitem{{display:flex;align-items:center;gap:8px;padding:7px 14px;text-decoration:none;color:#1E1E1E;font-size:12px;}}
.railitem:hover{{background:#EEEEEE;}}
.rn{{color:#595959;width:52px;flex:0 0 52px;font-weight:700;font-size:11px;}}
.rt{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
main{{flex:1;padding:22px;display:flex;flex-direction:column;gap:26px;align-items:flex-start;}}
main.grid{{flex-direction:row;flex-wrap:wrap;gap:18px;}}
.pane{{background:#fff;border:1px solid #BFBFBF;}}
.cap{{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid #E4E4E4;font-size:12px;}}
.idx{{font-weight:700;color:#8C8C8C;}}
.vid{{font-weight:700;background:#EEEEEE;padding:2px 7px;font-size:11px;}}
.ttl{{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:52%;}}
.fn{{color:#8C8C8C;font-size:11px;margin-left:auto;}}
.frame{{width:1280px;height:720px;overflow:hidden;}}
iframe{{width:1280px;height:720px;border:0;display:block;}}
body.z75 .frame{{width:960px;height:540px;}}  body.z75 iframe{{transform:scale(.75);transform-origin:0 0;}}
body.z50 .frame{{width:640px;height:360px;}}  body.z50 iframe{{transform:scale(.5);transform-origin:0 0;}}
body.z33 .frame{{width:426px;height:240px;}}  body.z33 iframe{{transform:scale(.3328);transform-origin:0 0;}}
body.z33 .ttl{{max-width:300px;}} body.z33 .fn{{display:none;}}
body.z33 .pane{{width:428px;flex:0 0 428px;}}
body.z33 .cap{{flex-wrap:nowrap;overflow:hidden;}}
</style></head><body>
<header>
  <h1>{html.escape(deck)}</h1>
  <span class="meta">{len(slides)} slides &middot; regenerated {datetime.now().strftime('%d %b %Y %H:%M')}{chartnote}</span>
  <span class="zooms">
    <button data-z="" class="on">100%</button><button data-z="z75">75%</button>
    <button data-z="z50">50%</button><button data-z="z33">grid</button>
  </span>
</header>
<div class="wrap"><nav>{''.join(rail)}</nav><main>{''.join(panes)}</main></div>
<script>
const btns=[...document.querySelectorAll('header button')], main=document.querySelector('main');
btns.forEach(b=>b.onclick=()=>{{
  document.body.className=b.dataset.z;
  main.classList.toggle('grid', b.dataset.z==='z33');
  btns.forEach(x=>x.classList.toggle('on',x===b));
}});
const panes=[...document.querySelectorAll('.pane')]; let cur=0;
addEventListener('keydown',e=>{{
  if(e.target.tagName==='INPUT') return;
  if(e.key==='j'||e.key==='ArrowDown') cur=Math.min(cur+1,panes.length-1);
  else if(e.key==='k'||e.key==='ArrowUp') cur=Math.max(cur-1,0);
  else return;
  e.preventDefault(); panes[cur].scrollIntoView({{behavior:'smooth',block:'start'}});
}});
</script></body></html>"""

    out = d / "workroom.html"
    out.write_text(page, encoding="utf-8")
    print(f"workroom.html written: {len(slides)} slides")
    print(f"  {out}")
    if open_browser:
        _open_in_browser(out)


# ============================================================================
# Server-side state: <dir>/workroom_state.json
# ============================================================================

def _new_slide_entry(mtime):
    return {"status": "active", "comments": [], "rounds": 1, "last_mtime": mtime}


def default_state(deck):
    return {"deck": deck, "order": [], "slides": {}, "builds": []}


def load_state(d, deck):
    p = d / STATE_FILENAME
    state = None
    if p.exists():
        try:
            state = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            state = None
    if state is None:
        state = default_state(deck)
    state.setdefault("deck", deck)
    state.setdefault("order", [])
    state.setdefault("slides", {})
    state.setdefault("builds", [])
    _ensure_comment_ids(state)
    return state


def save_state(d, state):
    (d / STATE_FILENAME).write_text(json.dumps(state, indent=2), encoding="utf-8")


def refresh_state(d, state):
    """Sync `state` with what's on disk: add new slide files at the end of `order`, and bump
    `rounds` for any slide whose mtime has moved since we last recorded it. Does not remove
    entries for files that vanished from disk - those are just flagged `missing` at read time
    (see state_for_api) so review history for a deleted slide isn't lost."""
    changed = False
    disk = sorted(p.name for p in d.glob("*.html") if is_slide(p))
    for f in disk:
        mtime = (d / f).stat().st_mtime
        if f not in state["slides"]:
            state["slides"][f] = _new_slide_entry(mtime)
            state["order"].append(f)
            changed = True
        else:
            st = state["slides"][f]
            last = st.get("last_mtime")
            if last is None:
                st["last_mtime"] = mtime
                changed = True
            elif mtime > last + 1e-6:
                st["rounds"] = int(st.get("rounds", 1)) + 1
                st["last_mtime"] = mtime
                changed = True
    for f in list(state["slides"]):
        if f not in state["order"]:
            state["order"].append(f)
            changed = True
    return changed


def slide_meta(d, fname):
    p = d / fname
    vid = vid_of(fname)
    if not p.exists():
        return {"vid": vid, "title": Path(fname).stem}
    text = p.read_text(encoding="utf-8", errors="ignore")
    return {"vid": vid, "title": title_of(text, Path(fname).stem)}


def state_for_api(d, state):
    """A copy of `state` for JSON responses / page rendering: adds `missing`, `vid`, `title`
    per slide, plus deck-wide `rounds_to_build_mean`/`rounds_to_build_n` - the current `rounds`
    count of every built slide, averaged (roadmap 2.4's first-try metric, shown in the header).
    Never written back to disk - save_state always writes the plain `state`."""
    out = json.loads(json.dumps(state))
    for f, st in out["slides"].items():
        st["missing"] = not (d / f).exists()
        st.update(slide_meta(d, f))
    built_rounds = [s["rounds"] for s in out["slides"].values() if s.get("built_version")]
    out["rounds_to_build_mean"] = (sum(built_rounds) / len(built_rounds)) if built_rounds else None
    out["rounds_to_build_n"] = len(built_rounds)
    return out


def _existing_slide_paths(d, state):
    return [d / f for f in state["order"] if (d / f).exists()]


# ---------------------------------------------------------------- Analysis tab (sidecar + Excel reads)
#
# A slide may carry a `<slide>.analysis.json` sidecar (see scripts/analysis.py) naming the Excel
# source(s) behind its figures. `/api/analysis` reads every sidecar in the deck and the Excel
# ranges they point at, once per request; `/api/analysis/sheet` serves the "whole sheet" toggle,
# gated to files a sidecar in this deck actually references (see _analysis_allowed_files).

def _analysis_allowed_files(d, state):
    """Absolute, resolved paths of every workbook referenced by any slide's sidecar in this
    deck - the allowlist for /api/analysis/sheet, so that endpoint can't be used to read an
    arbitrary file off disk."""
    allowed = set()
    for f in state["order"]:
        sidecar = analysis.load_sidecar(d, f)
        if not sidecar:
            continue
        for src in sidecar.get("sources", []) or []:
            fp = src.get("file")
            if not fp:
                continue
            try:
                allowed.add(str(Path(fp).resolve()))
            except Exception:  # noqa: BLE001 - an unresolvable path just never matches
                pass
    return allowed


def analysis_state_for_api(d, state):
    """The full /api/analysis response: one entry per slide, active slides first then
    archived, each carrying its sidecar (if any) and the grids its sources resolve to. A slide
    with no sidecar still gets an entry (has_sidecar False) so the page can render its
    "no data sources recorded" row."""
    active = [f for f in state["order"] if state["slides"].get(f, {}).get("status") != "archived"]
    archived = [f for f in state["order"] if state["slides"].get(f, {}).get("status") == "archived"]

    out_slides = []
    for f in active + archived:
        st = state["slides"].get(f, {})
        meta = slide_meta(d, f)
        sidecar = analysis.load_sidecar(d, f)
        grids = {}
        errors = []
        if sidecar:
            for src in sidecar.get("sources", []) or []:
                sid = src.get("id")
                if not sid:
                    continue
                grid = analysis.read_range(src.get("file", ""), src.get("sheet", ""),
                                            src.get("range", "A1"))
                grids[sid] = grid
                if isinstance(grid, dict) and grid.get("error"):
                    errors.append("%s: %s" % (sid, grid["error"]))
        out_slides.append({
            "file": f,
            "title": meta["title"],
            "status": st.get("status", "active"),
            "has_sidecar": sidecar is not None,
            "sidecar": sidecar,
            "grids": grids,
            "errors": errors,
        })
    return {"deck": state.get("deck"), "slides": out_slides}


def _safe_name(name):
    s = re.sub(r"[^A-Za-z0-9_.\-]+", "_", name).strip("_")
    return s or "deck"


# ---------------------------------------------------------------- pinned comments (anchor/target)
#
# A comment may optionally carry `view` (which of the HTML|PowerPoint card views it was left
# against - Feature 1) and `anchor`/`target` (where on the slide it points - Feature 2, pinned
# comments). All three are produced client-side by the workroom page's JS; the server's only job
# is to validate shape and clamp coordinates before they land in workroom_state.json.

VALID_VIEWS = ("html", "ppt")


def _valid_view(v):
    return v if v in VALID_VIEWS else "html"


def _clamp_int(v, lo, hi):
    """Coerce `v` to an int clamped into [lo, hi], or None if it isn't numeric."""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _validate_anchor(anchor):
    """A point (`w`/`h` 0) or box anchor in 1280x720 slide-pixel space, or None if `anchor`
    isn't a usable shape. `w`/`h` default to 0 (a point) when omitted."""
    if not isinstance(anchor, dict):
        return None
    x = _clamp_int(anchor.get("x"), 0, 1280)
    y = _clamp_int(anchor.get("y"), 0, 720)
    w = _clamp_int(anchor.get("w", 0), 0, 1280)
    h = _clamp_int(anchor.get("h", 0), 0, 720)
    if x is None or y is None or w is None or h is None:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _clean_str(v, maxlen):
    s = re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""
    return s[:maxlen]


def _validate_target(target):
    """The element under a pinned comment's anchor, captured client-side via
    elementFromPoint. None if `target` isn't a usable shape, or carries nothing meaningful
    (the client already stores null itself when it can't identify an element - this is just
    the server-side mirror of that same validation)."""
    if not isinstance(target, dict):
        return None
    tag = _clean_str(target.get("tag"), 40).lower()
    classes = _clean_str(target.get("classes"), 300)
    tid = _clean_str(target.get("id"), 120)
    text = _clean_str(target.get("text"), 90)
    if not (tag or classes or tid or text):
        return None
    box = target.get("box")
    box_out = None
    if isinstance(box, dict):
        bx, by = _clamp_int(box.get("x"), 0, 1280), _clamp_int(box.get("y"), 0, 720)
        bw, bh = _clamp_int(box.get("w", 0), 0, 1280), _clamp_int(box.get("h", 0), 0, 720)
        if None not in (bx, by, bw, bh):
            box_out = {"x": bx, "y": by, "w": bw, "h": bh}
    return {"tag": tag, "classes": classes, "id": tid, "text": text, "box": box_out}


# ---------------------------------------------------------------- comment ids (cid)
#
# Every comment gets a stable `cid` (8 hex chars) so it can be edited/deleted, and so a
# ledger row can follow it, regardless of its position in the slide's comment list - an
# index-based id breaks the moment an earlier comment on the same slide is deleted, since
# every later comment's index shifts down. A freshly created comment gets a random one
# (_new_cid); a comment written before this field existed gets one lazily, computed
# deterministically from its slide/index/timestamp so the same legacy comment always maps to
# the same cid (see _ensure_comment_ids, called from load_state).

def _new_cid(existing):
    for _ in range(50):
        cid = secrets.token_hex(4)
        if cid not in existing:
            return cid
    return secrets.token_hex(8)  # astronomically unlikely fallback


def _legacy_cid(slide, idx, ts, taken):
    base = "%s:%d:%s" % (slide, idx, ts or "")
    cid = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    while cid in taken:
        base += "!"
        cid = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return cid


def _ensure_comment_ids(state):
    """Assign a `cid` to any comment that doesn't have one yet. Mutates `state` in place;
    returns True if anything changed (so a caller could choose to save only when needed -
    in practice every caller of load_state() already saves state unconditionally)."""
    changed = False
    for slide, sinfo in state.get("slides", {}).items():
        comments = sinfo.get("comments") or []
        taken = {c["cid"] for c in comments if c.get("cid")}
        for idx, c in enumerate(comments):
            if not c.get("cid"):
                cid = _legacy_cid(slide, idx, c.get("ts"), taken)
                taken.add(cid)
                c["cid"] = cid
                changed = True
    return changed


# ---------------------------------------------------------------- promote to reference (2.3)

def _slugify(s, maxlen=40):
    s = re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_").lower()
    s = re.sub(r"_+", "_", s)
    return s[:maxlen].strip("_")


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _md_cell(s):
    """A markdown table cell must be one line with no unescaped pipes."""
    return str(s or "").replace("|", "\\|").replace("\n", " ").strip()


def _append_manifest_row(manifest_path, name, tier_label, msgtype, what_it_is, learn):
    """Insert a new row right after the last existing row of MANIFEST.md's exhibit table."""
    text = manifest_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    last_row = None
    for i, line in enumerate(lines):
        if line.startswith("|"):
            last_row = i
    if last_row is None:
        raise ValueError("no markdown table found in %s" % manifest_path)
    row = "| `%s` | %s | %s | %s | %s |" % (
        name, tier_label, _md_cell(msgtype), _md_cell(what_it_is), _md_cell(learn))
    lines.insert(last_row + 1, row)
    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def _append_sha256(corpus_path, pairs):
    """Append `<hexdigest> *<filename>` lines - the format already used in CORPUS_SHA256.txt."""
    with corpus_path.open("a", encoding="utf-8") as f:
        for digest, name in pairs:
            f.write("%s *%s\n" % (digest, name))


# ============================================================================
# Server-side build job (runs in a worker thread, started from POST /api/build)
# ============================================================================

def _run_build(d, deck, version, state_lock, build_status):
    try:
        with state_lock:
            state = load_state(d, deck)
            refresh_state(d, state)
            active = [f for f in state["order"]
                      if state["slides"].get(f, {}).get("status") != "archived" and (d / f).exists()]
            save_state(d, state)

        if not active:
            record = {"version": version, "at": datetime.now().isoformat(timespec="seconds"),
                       "file": None, "slides": [], "ok": False, "log": "no active slides to build"}
        else:
            build_dir = d / "build"
            build_dir.mkdir(exist_ok=True)
            out_pptx = build_dir / f"{_safe_name(deck)}_v{version:02d}.pptx"
            cmd = [sys.executable, str(HERE / "build_deck.py"), str(out_pptx)] + [str(d / f) for f in active]
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            log = (r.stdout or "") + (r.stderr or "")
            ok = r.returncode == 0 and out_pptx.exists()

            if ok:
                png_dir = build_dir / f"v{version:02d}_png"
                png_dir.mkdir(exist_ok=True)
                cmd2 = [sys.executable, str(HERE / "render_slides.py"), str(out_pptx), str(png_dir)]
                r2 = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8", errors="replace")
                log += "\n" + (r2.stdout or "") + (r2.stderr or "")
                ok = ok and r2.returncode == 0

            record = {"version": version, "at": datetime.now().isoformat(timespec="seconds"),
                       "file": f"build/{out_pptx.name}", "slides": list(active), "ok": ok, "log": log}
    except Exception as e:  # noqa: BLE001 - a failed build must never take the server down
        record = {"version": version, "at": datetime.now().isoformat(timespec="seconds"),
                   "file": None, "slides": [], "ok": False,
                   "log": "%s: %s" % (type(e).__name__, e)}

    with state_lock:
        state = load_state(d, deck)
        state.setdefault("builds", []).append(record)
        if record["ok"]:
            for f in record["slides"]:
                mtime = (d / f).stat().st_mtime if (d / f).exists() else 0
                entry = state["slides"].setdefault(f, _new_slide_entry(mtime))
                entry["built_version"] = record["version"]
                entry["built_at"] = record["at"]
        save_state(d, state)
        build_status["status"] = "done" if record["ok"] else "error"
        build_status["result"] = record

    if record["ok"]:
        try:
            ledger.sync()
        except Exception:  # noqa: BLE001 - the ledger is a convenience, never a build blocker
            pass


def _build_status_for_page(build_status, state):
    """The header's build status on a freshly loaded page: the live in-memory status if this
    server process has already run (or is running) a build, otherwise the latest persisted
    build from workroom_state.json - so a server restart shows "v02 built, N slides" rather
    than "not built" when the deck already has a build on disk. Only "idle" (never touched
    this session) falls back to state; "not built" is shown only when `builds` is empty too."""
    if build_status["status"] != "idle" or not state.get("builds"):
        return dict(build_status)
    latest = state["builds"][-1]
    return {"status": "done" if latest.get("ok") else "error", "result": latest}


# ============================================================================
# Server mode: python workroom.py <dir> --serve [--port N] [--open]
# ============================================================================

def make_handler(d, deck):
    """Build a BaseHTTPRequestHandler subclass closed over (d, deck) plus the shared
    build-status dict and state lock, and return (HandlerClass, build_status)."""
    build_status = {"status": "idle", "result": None}
    state_lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "WorkroomHTTP/1.0"
        # monotonic time of the last request, read by the idle watchdog in serve()
        last_request = [time.monotonic()]

        def log_message(self, fmt, *args):  # noqa: A003 - keep console clean
            pass

        # ---- response helpers ----
        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, text, status=200):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, fp, content_type=None):
            ctype = content_type or mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError:
                return {}

        def _safe_static_path(self, url_path):
            rel = urllib.parse.unquote(url_path.lstrip("/"))
            if not rel:
                return None
            target = (d / rel).resolve()
            try:
                target.relative_to(d.resolve())
            except ValueError:
                return None
            return target

        def _current_state_for_api(self):
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                save_state(d, state)
                return state_for_api(d, state)

        def _current_analysis_for_api(self):
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                save_state(d, state)
                return analysis_state_for_api(d, state)

        def _serve_analysis_sheet(self, query):
            """GET /api/analysis/sheet?p=<xlsx>&sheet=<name>&whole=1 - the "whole sheet" toggle
            for the Analysis tab. Refuses (403) any file not referenced by some slide's
            sidecar in this deck, so this can't be used to browse an arbitrary path."""
            qs = urllib.parse.parse_qs(query)
            raw = (qs.get("p") or [None])[0]
            sheet = (qs.get("sheet") or [None])[0]
            whole = (qs.get("whole") or ["0"])[0]
            if not raw or not sheet:
                self._send_json({"error": "missing p or sheet"}, status=400)
                return
            try:
                resolved = str(Path(raw).resolve())
            except Exception:  # noqa: BLE001
                self._send_json({"error": "invalid path"}, status=400)
                return
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                save_state(d, state)
                allowed = _analysis_allowed_files(d, state)
            if resolved not in allowed:
                self._send_json({"error": "file not referenced by any sidecar in this deck"}, status=403)
                return
            grid = analysis.whole_sheet(raw, sheet) if whole in ("1", "true") \
                else analysis.read_range(raw, sheet, "A1:A1")
            self._send_json(grid)

        # ---- GET ----
        def do_GET(self):  # noqa: N802 - stdlib method name
            Handler.last_request[0] = time.monotonic()
            try:
                path = urllib.parse.urlsplit(self.path).path
                if path == "/":
                    self._serve_index()
                elif path == "/api/state":
                    self._send_json(self._current_state_for_api())
                elif path == "/api/whoami":
                    self._send_json({"app": WHOAMI_APP, "dir": str(d)})
                elif path == "/api/build/status":
                    with state_lock:
                        self._send_json(dict(build_status))
                elif path == "/api/analysis":
                    self._send_json(self._current_analysis_for_api())
                elif path == "/api/analysis/sheet":
                    self._serve_analysis_sheet(urllib.parse.urlsplit(self.path).query)
                elif path == "/file":
                    self._serve_local_asset(urllib.parse.urlsplit(self.path).query)
                else:
                    fp = self._safe_static_path(path)
                    if fp is None or not fp.exists() or not fp.is_file():
                        self._send_json({"error": "not found"}, status=404)
                    else:
                        self._send_file(fp)
            except Exception as e:  # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(e).__name__, e)}, status=500)

        def _serve_local_asset(self, query):
            """GET /file?p=<urlencoded absolute path> - the only way an image or font file
            referenced by file:/// or a bare absolute/relative path (see _rewrite_image_refs,
            _server_font_css) can reach the browser, since a page served over http cannot load
            file:// URLs itself. This is a single-user local tool: any absolute path is allowed
            as long as its extension is an image or font type and it does not contain "..". """
            raw = (urllib.parse.parse_qs(query).get("p") or [None])[0]
            if not raw:
                self._send_json({"error": "missing p"}, status=400)
                return
            if ".." in raw:
                self._send_json({"error": "invalid path"}, status=400)
                return
            ext = Path(raw).suffix.lower().lstrip(".")
            if ext not in ASSET_EXTS:
                self._send_json({"error": "unsupported file type: .%s" % ext}, status=400)
                return
            fp = Path(raw)
            if not fp.exists() or not fp.is_file():
                self._send_json({"error": "not found"}, status=404)
                return
            self._send_file(fp, content_type=_FONT_CONTENT_TYPES.get(ext))

        def _serve_index(self):
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                save_state(d, state)
                build_workroom_copies(d, _existing_slide_paths(d, state), mode="serve")
                api_state = state_for_api(d, state)
                bstatus = _build_status_for_page(build_status, state)
            self._send_html(server_page_html(deck, api_state, bstatus))

        # ---- POST ----
        def do_POST(self):  # noqa: N802 - stdlib method name
            Handler.last_request[0] = time.monotonic()
            try:
                path = urllib.parse.urlsplit(self.path).path
                m = re.match(r"^/api/slide/([^/]+)/(archive|restore|comment|promote)$", path)
                m2 = re.match(r"^/api/slide/([^/]+)/comment/([^/]+)/(edit|delete)$", path)
                if m:
                    fname, action = urllib.parse.unquote(m.group(1)), m.group(2)
                    if action == "promote":
                        self._handle_promote(fname)
                    else:
                        self._handle_slide_action(fname, action)
                elif m2:
                    fname = urllib.parse.unquote(m2.group(1))
                    cid = urllib.parse.unquote(m2.group(2))
                    self._handle_comment_edit_delete(fname, cid, m2.group(3))
                elif path == "/api/order":
                    self._handle_order()
                elif path == "/api/build":
                    self._handle_build()
                else:
                    self._send_json({"error": "not found"}, status=404)
            except Exception as e:  # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(e).__name__, e)}, status=500)

        def _handle_slide_action(self, fname, action):
            body = self._read_json_body()
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                if fname not in state["slides"]:
                    save_state(d, state)
                    self._send_json({"error": "unknown slide: %s" % fname}, status=404)
                    return
                if action == "archive":
                    state["slides"][fname]["status"] = "archived"
                elif action == "restore":
                    state["slides"][fname]["status"] = "active"
                elif action == "comment":
                    text = str(body.get("text") or "").strip()
                    if not text:
                        save_state(d, state)
                        self._send_json({"error": "empty comment"}, status=400)
                        return
                    rnd = int(state["slides"][fname].get("rounds", 1))
                    existing_cids = {c.get("cid") for c in state["slides"][fname].get("comments", [])
                                      if c.get("cid")}
                    comment = {"cid": _new_cid(existing_cids),
                               "ts": datetime.now().isoformat(timespec="seconds"), "text": text,
                               "round": rnd, "view": _valid_view(body.get("view"))}
                    anchor = _validate_anchor(body.get("anchor"))
                    if anchor is not None:
                        comment["anchor"] = anchor
                    target = _validate_target(body.get("target"))
                    if target is not None:
                        comment["target"] = target
                    state["slides"][fname].setdefault("comments", []).append(comment)
                save_state(d, state)
                out = state_for_api(d, state)
            if action == "comment":
                try:
                    ledger.sync()
                except Exception:  # noqa: BLE001 - the ledger is a convenience, never blocks a comment
                    pass
            self._send_json(out)

        def _handle_comment_edit_delete(self, fname, cid, action):
            """POST /api/slide/<f>/comment/<cid>/edit {text, view?} or
            POST /api/slide/<f>/comment/<cid>/delete {} - the reviewer can fix a typo or drop a comment
            without disturbing any other comment's cid (and therefore its ledger row/category -
            see ledger.py). Pin numbering isn't stored anywhere; it's just the position of a
            comment with an `anchor` in this list, so deleting one renumbers the rest for free."""
            body = self._read_json_body()
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                if fname not in state["slides"]:
                    save_state(d, state)
                    self._send_json({"error": "unknown slide: %s" % fname}, status=404)
                    return
                comments = state["slides"][fname].setdefault("comments", [])
                idx = next((i for i, c in enumerate(comments) if c.get("cid") == cid), None)
                if idx is None:
                    save_state(d, state)
                    self._send_json({"error": "unknown comment: %s" % cid}, status=404)
                    return
                if action == "edit":
                    text = str(body.get("text") or "").strip()
                    if not text:
                        save_state(d, state)
                        self._send_json({"error": "empty comment"}, status=400)
                        return
                    comments[idx]["text"] = text
                    if "view" in body:
                        comments[idx]["view"] = _valid_view(body.get("view"))
                    comments[idx]["edited_ts"] = datetime.now().isoformat(timespec="seconds")
                else:  # delete
                    comments.pop(idx)
                save_state(d, state)
                out = state_for_api(d, state)
            try:
                ledger.sync()
            except Exception:  # noqa: BLE001 - the ledger is a convenience, never blocks edit/delete
                pass
            self._send_json(out)

        def _handle_order(self):
            body = self._read_json_body()
            order = body.get("order")
            if not isinstance(order, list):
                self._send_json({"error": "order must be a list"}, status=400)
                return
            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                known = set(state["order"])
                new_order = [f for f in order if isinstance(f, str) and f in known]
                for f in state["order"]:
                    if f not in new_order:
                        new_order.append(f)
                state["order"] = new_order
                save_state(d, state)
                out = state_for_api(d, state)
            self._send_json(out)

        def _handle_build(self):
            with state_lock:
                if build_status["status"] == "running":
                    self._send_json({"ok": False, "error": "build already running"}, status=409)
                    return
                state = load_state(d, deck)
                refresh_state(d, state)
                save_state(d, state)
                max_v = max([b.get("version", 0) for b in state.get("builds", [])], default=0)
                version = max_v + 1
                build_status["status"] = "running"
                build_status["result"] = None
            t = threading.Thread(target=_run_build, args=(d, deck, version, state_lock, build_status),
                                  daemon=True)
            t.start()
            self._send_json({"ok": True, "status": "running", "version": version})

        def _handle_promote(self, fname):
            """POST /api/slide/<file>/promote {tier, msgtype, slug, learn} - turn a built slide
            into a reference exhibit: copy its HTML and the matching PowerPoint-render PNG from
            the build that produced it into reference/, add a MANIFEST.md row and
            CORPUS_SHA256.txt lines, and record `promoted` on the slide (roadmap 2.3)."""
            body = self._read_json_body()
            tier = str(body.get("tier") or "").strip()
            msgtype = str(body.get("msgtype") or "").strip().lower()
            slug = _slugify(body.get("slug"))
            learn = str(body.get("learn") or "").strip()

            if tier not in ("1", "2", "3"):
                self._send_json({"error": "tier must be 1, 2 or 3"}, status=400)
                return
            if msgtype not in MSGTYPES:
                self._send_json({"error": "unknown message type: %s" % msgtype}, status=400)
                return
            if not slug:
                self._send_json({"error": "slug is required"}, status=400)
                return
            if not learn:
                self._send_json({"error": "\"what to learn\" is required"}, status=400)
                return

            with state_lock:
                state = load_state(d, deck)
                refresh_state(d, state)
                if fname not in state["slides"]:
                    save_state(d, state)
                    self._send_json({"error": "unknown slide: %s" % fname}, status=404)
                    return
                sinfo = state["slides"][fname]
                built_version = sinfo.get("built_version")
                if not built_version:
                    save_state(d, state)
                    self._send_json({"error": "slide has no build yet"}, status=400)
                    return
                build = next((b for b in state.get("builds", []) if b.get("version") == built_version), None)
                if not build or not build.get("ok") or fname not in (build.get("slides") or []):
                    save_state(d, state)
                    self._send_json({"error": "could not find the build that produced this slide"},
                                     status=400)
                    return
                idx = build["slides"].index(fname)
                src_png = d / "build" / ("v%02d_png" % build["version"]) / ("slide%02d.png" % (idx + 1))
                if not src_png.exists():
                    save_state(d, state)
                    self._send_json({"error": "render PNG not found: %s" % src_png}, status=400)
                    return

                name = "T%s_%s_%s" % (tier, msgtype, slug)
                dst_html = REFERENCE_DIR / (name + ".html")
                dst_png = REFERENCE_DIR / (name + ".png")
                if dst_html.exists() or dst_png.exists():
                    save_state(d, state)
                    self._send_json({"error": "reference exhibit already exists: %s - change the slug" % name},
                                     status=409)
                    return

                src_html = d / fname
                REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src_html, dst_html)
                shutil.copyfile(src_png, dst_png)

                title = title_of(src_html.read_text(encoding="utf-8", errors="ignore"), Path(fname).stem)
                _append_manifest_row(REFERENCE_DIR / "MANIFEST.md", name, "T" + tier, msgtype, title, learn)
                _append_sha256(REFERENCE_DIR / "CORPUS_SHA256.txt",
                                [(_sha256_of(dst_html), dst_html.name), (_sha256_of(dst_png), dst_png.name)])

                now = datetime.now().isoformat(timespec="seconds")
                sinfo["promoted"] = {"as": name, "at": now, "version": built_version}
                save_state(d, state)
                out = state_for_api(d, state)

            out["promote"] = {"html": "reference/%s.html" % name, "png": "reference/%s.png" % name}
            self._send_json(out)

    return Handler, build_status


# ---------------------------------------------------------------- server-mode page + JS/CSS

SERVER_CSS = """
*{box-sizing:border-box;}
body{margin:0;font-family:__STACK__;background:#EEEEEE;color:#1E1E1E;}
header{position:sticky;top:0;z-index:20;background:#FFFFFF;border-bottom:1px solid #BFBFBF;
  padding:12px 20px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;}
header h1{font-size:17px;margin:0;font-weight:700;}
header .meta{font-size:12px;color:#7F7F7F;}
header button{font-family:inherit;font-size:12px;padding:5px 12px;border:1px solid #BFBFBF;
  background:#fff;cursor:pointer;color:#1E1E1E;}
header button.on{background:#373737;color:#fff;border-color:#373737;}
header button:disabled{opacity:.5;cursor:default;}
#buildStatusText{font-size:12px;color:#595959;}
#buildLinkText{font-size:11px;color:#8C8C8C;font-family:monospace;word-break:break-all;}
.zooms{margin-left:auto;display:flex;gap:6px;}
.wrap{display:flex;align-items:flex-start;}
nav{position:sticky;top:53px;width:260px;flex:0 0 260px;max-height:calc(100vh - 53px);overflow:auto;
  background:#fff;border-right:1px solid #BFBFBF;padding:10px 0;}
.rail-sec-title{font-size:11px;font-weight:700;color:#595959;padding:8px 14px 4px;display:block;}
button.rail-sec-title{width:100%;text-align:left;background:none;border:0;cursor:pointer;font-family:inherit;}
button.rail-sec-title::before{content:"+ ";}
button.rail-sec-title.open::before{content:"\\2212  ";}
.railitem{display:flex;align-items:center;gap:8px;padding:7px 14px;color:#1E1E1E;font-size:12px;cursor:pointer;}
.railitem:hover{background:#EEEEEE;}
.railitem.missing{color:#8C8C8C;font-style:italic;}
.rn{color:#595959;width:52px;flex:0 0 52px;font-weight:700;font-size:11px;}
.rt{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rarrows{display:flex;gap:2px;flex:0 0 auto;}
.arrowbtn{border:1px solid #BFBFBF;background:#fff;font-size:10px;padding:1px 4px;cursor:pointer;font-family:inherit;}
main{flex:1;padding:22px;display:flex;flex-direction:column;gap:30px;align-items:flex-start;width:100%;}
#activePanes{display:flex;flex-direction:column;gap:26px;align-items:flex-start;width:100%;}
#activePanes.grid{flex-direction:row;flex-wrap:wrap;gap:18px;}
#archivedPanes{display:flex;flex-direction:row;flex-wrap:wrap;gap:14px;width:100%;
  border-top:1px solid #BFBFBF;padding-top:18px;}
#archivedPanes[hidden]{display:none;}
.pane{background:#fff;border:1px solid #BFBFBF;}
.pane.archived{opacity:.85;max-width:640px;}
.pane.archived .cap{flex-wrap:wrap;}
.pane.archived .ttl{max-width:100%;}
.cap{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid #E4E4E4;
  font-size:12px;flex-wrap:wrap;}
.idx{font-weight:700;color:#8C8C8C;}
.vid{font-weight:700;background:#EEEEEE;padding:2px 7px;font-size:11px;}
.ttl{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:36%;}
.fn{color:#8C8C8C;font-size:11px;}
.round{color:#595959;font-size:11px;}
.badge{color:#595959;font-size:11px;}
.miss{color:#B3261E;font-weight:700;font-size:11px;}
.actbtn{font-family:inherit;font-size:11px;padding:4px 9px;border:1px solid #BFBFBF;background:#fff;cursor:pointer;}
.actbtn.on{background:#373737;color:#fff;border-color:#373737;}
.viewtoggle{display:flex;gap:2px;}
.tbtn{font-family:inherit;font-size:11px;padding:4px 9px;border:1px solid #BFBFBF;background:#fff;cursor:pointer;}
.tbtn.on{background:#373737;color:#fff;border-color:#373737;}
.cmtbox{padding:8px 12px;border-bottom:1px solid #E4E4E4;display:flex;gap:8px;align-items:flex-start;}
.cmtbox .cmtboxcol{flex:1;display:flex;flex-direction:column;gap:6px;}
.cmtbox textarea{flex:1;font-family:inherit;font-size:12px;padding:6px;border:1px solid #BFBFBF;
  min-height:50px;resize:vertical;width:100%;}
.savebtn{font-family:inherit;font-size:11px;padding:5px 12px;border:1px solid #373737;
  background:#373737;color:#fff;cursor:pointer;}
.cmtlist{padding:6px 12px;border-bottom:1px solid #E4E4E4;background:#FAFAF9;}
.cmt{padding:4px 0;}
.cmttop{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;}
.cmtctrls{display:flex;gap:6px;flex:0 0 auto;}
.cmtedit{font-family:inherit;font-size:10px;padding:1px 6px;border:1px solid #BFBFBF;background:#fff;
  color:#595959;cursor:pointer;}
.cmtdel{font-family:inherit;font-size:11px;line-height:1;padding:1px 6px;border:1px solid #BFBFBF;
  background:#fff;color:#B3261E;cursor:pointer;}
.cmtedittbox{display:flex;flex-direction:column;gap:6px;margin-top:4px;}
.cmtedittbox textarea{font-family:inherit;font-size:12px;padding:6px;border:1px solid #BFBFBF;
  min-height:50px;resize:vertical;width:100%;}
.cmtmeta{font-size:10px;color:#8C8C8C;}
.cmttext{font-size:12px;white-space:pre-wrap;}
.paneMedia{position:relative;}
.pinlayer{position:absolute;top:0;left:0;width:1280px;height:720px;pointer-events:none;}
.pincap{position:absolute;top:0;left:0;width:100%;height:100%;cursor:crosshair;background:transparent;z-index:5;}
.pinrubber{position:absolute;border:1.5px dashed #373737;background:rgba(55,55,55,.08);pointer-events:none;}
.pinmarker{position:absolute;width:20px;height:20px;margin-left:-10px;margin-top:-10px;border-radius:50%;
  background:#373737;color:#fff;font-size:11px;font-weight:700;line-height:20px;text-align:center;
  pointer-events:auto;cursor:default;}
.pinmarker:hover{z-index:20;}
.pintip{display:none;position:absolute;top:-4px;left:20px;width:240px;background:#fff;color:#1E1E1E;
  border:1px solid #373737;padding:6px 8px;text-align:left;font-weight:400;line-height:1.35;
  box-shadow:0 2px 8px rgba(0,0,0,.2);white-space:pre-wrap;}
.pintip.left{left:auto;right:20px;}
.pintip .tipmeta{display:block;font-size:9px;color:#8C8C8C;margin-bottom:2px;}
.pintip .tiptext{font-size:11px;}
.pintip .tiptop{display:flex;align-items:flex-start;justify-content:space-between;gap:6px;}
.pintip .tipctrls{display:flex;gap:4px;flex:0 0 auto;}
.pintip .tipedit{font-family:inherit;font-size:10px;line-height:1.4;padding:0 4px;border:1px solid #BFBFBF;
  background:#fff;color:#595959;cursor:pointer;}
.pintip .tipdel{font-family:inherit;font-size:10px;line-height:1.4;padding:0 4px;border:1px solid #BFBFBF;
  background:#fff;color:#B3261E;cursor:pointer;}
.pinmarker:hover .pintip{display:block;}
.pinbox{position:absolute;border:1.5px solid #373737;box-sizing:border-box;}
.pinpop{position:absolute;width:260px;background:#fff;border:1px solid #373737;padding:8px;
  display:flex;flex-direction:column;gap:6px;z-index:10;box-shadow:0 2px 8px rgba(0,0,0,.25);}
.pinpop textarea{font-family:inherit;font-size:12px;padding:6px;border:1px solid #BFBFBF;
  min-height:50px;resize:vertical;width:100%;}
.pinpopbtns{display:flex;gap:6px;justify-content:flex-end;}
.refbadge{color:#595959;font-size:11px;background:#EEEEEE;padding:2px 7px;}
.promobox{padding:10px 12px;border-bottom:1px solid #E4E4E4;display:flex;flex-direction:column;
  gap:8px;background:#FAFAF9;}
.promobox .prow{display:flex;align-items:center;gap:8px;font-size:12px;flex-wrap:wrap;}
.promobox .prow>span{color:#595959;width:110px;flex:0 0 auto;}
.promobox .prow label{display:flex;align-items:center;gap:3px;font-weight:400;}
.promobox input[type=text]{flex:1;min-width:180px;font-family:inherit;font-size:12px;padding:5px 7px;
  border:1px solid #BFBFBF;}
.promobox select{font-family:inherit;font-size:12px;padding:5px 7px;border:1px solid #BFBFBF;}
.promoerr{color:#B3261E;font-size:11px;}
.frame{position:relative;width:1280px;height:720px;overflow:hidden;}
.frame iframe{width:1280px;height:720px;border:0;display:block;}
.frame img{width:1280px;height:720px;display:block;object-fit:contain;background:#fff;}
.aframe{position:relative;width:640px;height:360px;overflow:hidden;}
.aframe iframe{width:1280px;height:720px;border:0;transform:scale(.5);transform-origin:0 0;}
.aframe img{width:1280px;height:720px;display:block;transform:scale(.5);transform-origin:0 0;background:#fff;}
.aframe .pinlayer{transform:scale(.5);transform-origin:0 0;}
.missingmsg{width:1280px;height:200px;display:flex;align-items:center;justify-content:center;
  color:#8C8C8C;font-size:13px;}
body.z75 .frame{width:960px;height:540px;} body.z75 .frame iframe,body.z75 .frame img,body.z75 .frame .pinlayer{transform:scale(.75);transform-origin:0 0;}
body.z50 .frame{width:640px;height:360px;} body.z50 .frame iframe,body.z50 .frame img,body.z50 .frame .pinlayer{transform:scale(.5);transform-origin:0 0;}
body.z33 .frame{width:426px;height:240px;} body.z33 .frame iframe,body.z33 .frame img,body.z33 .frame .pinlayer{transform:scale(.3328);transform-origin:0 0;}
body.z33 .ttl{max-width:300px;} body.z33 .fn{display:none;}
/* grid (contact-sheet) mode: a fixed-width card per pane, one-line caption, no comment/action
   chrome except Archive and Pin - see WORKROOM.md "grid" zoom. Pins/markers and their tooltips stay. */
body.z33 .pane{width:428px;flex:0 0 428px;}
body.z33 .cap{flex-wrap:nowrap;overflow:hidden;}
body.z33 .cap .vid,body.z33 .cap .badge,body.z33 .cap .miss,body.z33 .cap .refbadge,
body.z33 .cap .viewtoggle,body.z33 .cap .actbtn:not(.pinbtn):not(.archbtn){display:none;}
/* Archive/Restore and Pin stay in grid mode (v0.3.4, reviewers often work in grid): they sit at the right edge
   of the one-line caption and the title/file name shrink with an ellipsis so they are never clipped; the
   pin note popover is kept too. */
body.z33 .cap .archbtn,body.z33 .cap .pinbtn{display:inline-block;flex:0 0 auto;padding:2px 7px;}
body.z33 .cap .archbtn{margin-left:auto;}
body.z33 .cap .ttl,body.z33 .cap .fn{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
body.z33 .cap .ttl{max-width:none;}
body.z33 .cmtbox,body.z33 .cmtlist,body.z33 .promobox{display:none;}
#hidePinsToggle.on{background:#373737;color:#fff;border-color:#373737;}
"""

# ---------------------------------------------------------------- Analysis tab CSS
#
# The Excel look (.axl / .agrid / .alegend / ...) mirrors the approved mockup
# (the approved analysis-tab mockup, variation 1 "source sheet"): a ribbon
# line, a formula bar, a grid with column letters and row numbers, Excel's own colour
# convention (blue typed numbers, green cross-sheet links, black formulas), a sand fill for
# cells shown on the slide, and blue/green outlines for precedents/selection.
ANALYSIS_CSS = """
.tabs{display:flex;gap:2px;margin-left:4px;}
.tabbtn{font-family:inherit;font-size:12px;padding:5px 12px;border:1px solid #BFBFBF;background:#fff;
  cursor:pointer;color:#1E1E1E;}
.tabbtn.on{background:#373737;color:#fff;border-color:#373737;}
#slidesView{display:contents;}
#slidesView[hidden]{display:none;}
#analysisView{width:100%;display:flex;flex-direction:column;gap:24px;}
#analysisView[hidden]{display:none;}
.asec{background:#fff;border:1px solid #BFBFBF;display:flex;gap:16px;padding:14px;flex-wrap:wrap;}
.asec.nosc{padding:8px 14px;font-size:12px;color:#595959;flex-wrap:nowrap;}
.asub{font-size:11px;color:#8C8C8C;font-weight:700;margin:0 0 6px 0;}
.acol-thumb{flex:0 0 400px;}
.aframe2{position:relative;width:400px;height:225px;overflow:hidden;border:1px solid #E4E4E4;background:#fff;}
.aframe2 iframe{width:1280px;height:720px;border:0;transform:scale(.3125);transform-origin:0 0;}
.amk{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:#373737;
  color:#fff;font-size:9px;font-weight:700;line-height:16px;text-align:center;cursor:pointer;z-index:5;}
.amk.on{background:#B3261E;}
.acol-xl{flex:1 1 560px;min-width:320px;}
.axl{background:#fff;border:1px solid #D4D4D4;font-family:Calibri,'Segoe UI',Arial,sans-serif;
  font-size:12px;color:#000;}
.axl .aribbon{display:flex;align-items:center;gap:8px;padding:6px 8px;background:#F3F2F1;
  border-bottom:1px solid #D4D4D4;font-family:__STACK__;font-size:11px;color:#595959;flex-wrap:wrap;}
.axl .aribbon .afile{font-weight:700;color:#1E1E1E;}
.axl .afbar{display:flex;align-items:stretch;border-bottom:1px solid #D4D4D4;height:26px;}
.axl .afbar .aref{width:90px;flex:0 0 auto;border-right:1px solid #D4D4D4;padding:0 8px;line-height:26px;
  font-weight:700;}
.axl .afbar .afx{width:28px;flex:0 0 auto;border-right:1px solid #D4D4D4;text-align:center;line-height:26px;
  color:#595959;font-style:italic;}
.axl .afbar .af{flex:1;padding:0 8px;line-height:26px;font-family:Consolas,monospace;font-size:12px;
  white-space:nowrap;overflow:auto;}
.agridwrap{max-height:560px;overflow:auto;}
.agrid{border-collapse:collapse;width:100%;table-layout:fixed;}
.agrid th,.agrid td{border:1px solid #D4D4D4;height:20px;padding:0 5px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;font-size:12px;}
.agrid th{background:#F3F2F1;color:#444;font-weight:400;text-align:center;position:sticky;top:0;z-index:2;}
.agrid td.arn{background:#F3F2F1;color:#444;text-align:center;width:34px;position:sticky;left:0;}
.agrid td.anum{text-align:right;font-variant-numeric:tabular-nums;}
.agrid td.atxt{text-align:left;}
.agrid td.aempty{color:#BFBFBF;}
.agrid td.abold{font-weight:700;}
.agrid td.ainp{color:#0000CC;}
.agrid td.alink{color:#008000;}
.agrid td.ashown{background:#F0EAE0;position:relative;}
.agrid td.ashown::after{content:attr(data-m);position:absolute;right:2px;top:1px;width:13px;height:13px;
  border-radius:50%;background:#373737;color:#fff;font-size:8px;line-height:13px;text-align:center;
  font-family:__STACK__;font-weight:700;}
.agrid td.asel{outline:2px solid #217346;outline-offset:-2px;}
.agrid td.aprec{outline:2px solid #1F5FBF;outline-offset:-2px;background:#E8F0FB;}
.alegend{display:flex;gap:14px;padding:6px 8px;border-top:1px solid #D4D4D4;font-family:__STACK__;
  font-size:11px;color:#595959;background:#F3F2F1;flex-wrap:wrap;}
.alegend span::before{content:"";display:inline-block;width:10px;height:10px;margin-right:4px;
  vertical-align:-1px;border:1px solid #D4D4D4;}
.al1::before{background:#F0EAE0;}
.al2::before{background:#E8F0FB;border-color:#1F5FBF;}
.al3::before{background:#fff;border-color:#0000CC;}
.al4::before{background:#fff;border-color:#008000;}
.asheet-tabsx{display:flex;gap:0;background:#F3F2F1;font-family:Calibri,Arial,sans-serif;font-size:11px;
  border-top:1px solid #D4D4D4;flex-wrap:wrap;}
.asheet-tabsx span{padding:4px 10px;border-right:1px solid #D4D4D4;color:#444;cursor:pointer;}
.asheet-tabsx span.on{background:#fff;color:#217346;font-weight:700;border-bottom:2px solid #217346;}
.awholetoggle{margin-left:auto;font-family:inherit;font-size:11px;padding:3px 9px;border:1px solid #BFBFBF;
  background:#fff;cursor:pointer;}
.awholetoggle.on{background:#373737;color:#fff;border-color:#373737;}
.anotes{margin:10px 0 0;padding-left:18px;font-size:12px;color:#595959;}
.anotes li{margin-bottom:3px;}
.afigtable{margin-top:10px;width:100%;border-collapse:collapse;font-size:11px;}
.afigtable th,.afigtable td{border:1px solid #E4E4E4;padding:3px 6px;text-align:left;}
.afigtable th{background:#FAFAF9;font-weight:700;color:#595959;}
.aerr{color:#B3261E;font-size:12px;margin-top:8px;}
"""

# No Python interpolation happens inside this JS - it is entirely generic and driven by the
# two inline JSON blobs (#initial-state, #initial-build) the page embeds, plus the JSON API.
SERVER_JS = """
(function(){
  var STATE = JSON.parse(document.getElementById('initial-state').textContent);
  var BUILD = JSON.parse(document.getElementById('initial-build').textContent);
  var commentOpen = {};
  var commentViewSel = {};    // Feature 1: HTML|PowerPoint toggle inside an open comment box
  var commentDraftText = {};  // preserves a typed-but-unsaved comment across re-renders
  var commentEditOpen = {};   // ckey(file,cid) -> true while that comment's inline editor is open
  var commentEditDraft = {};  // ckey(file,cid) -> {text, view}
  var viewMode = {};
  var promoteOpen = {};
  var promoteError = {};
  var archOpen = false;
  var pollTimer = null;
  var panes = [];
  var curIdx = 0;

  // Feature 2: pinned comments
  var pinMode = {};       // file -> true while the crosshair capture overlay is armed
  var pinNoteOpen = {};   // file -> true while the note popover is open (after a click/drag)
  var pinDraft = {};      // file -> {anchor, target, text, view, popLeft, popTop}
  var dragState = null;   // in-flight mousedown->mouseup drag, never re-rendered mid-drag
  var pinsHidden = false;
  try { pinsHidden = localStorage.getItem('wr_hide_pins_' + STATE.deck) === '1'; } catch(e){}

  var MSGTYPES = ['cover','end','statement','credentials','contrast','trend','composition',
    'evidence','org','decomposition','comparison','roadmap','operatingmodel','system',
    'triangulation','other'];

  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function slugify(s){
    return String(s||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'').slice(0,40);
  }

  function ckey(file, cid){
    return file + '::' + cid;
  }

  function activeFiles(){
    return STATE.order.filter(function(f){ return (STATE.slides[f]||{}).status !== 'archived'; });
  }
  function archivedFiles(){
    return STATE.order.filter(function(f){ return (STATE.slides[f]||{}).status === 'archived'; });
  }
  function buildForVersion(v){
    var bs = STATE.builds || [];
    for(var i=0;i<bs.length;i++){ if(bs[i].version === v) return bs[i]; }
    return null;
  }
  function pngSrc(file, slide){
    if(!slide.built_version) return null;
    var b = buildForVersion(slide.built_version);
    if(!b || !b.ok) return null;
    var idx = (b.slides||[]).indexOf(file);
    if(idx < 0) return null;
    var vv = ('0'+b.version).slice(-2);
    var nn = ('0'+(idx+1)).slice(-2);
    return 'build/v'+vv+'_png/slide'+nn+'.png';
  }

  function railItem(file){
    var s = STATE.slides[file] || {};
    var cls = 'railitem' + (s.missing ? ' missing' : '');
    return '<div class="'+cls+'" data-file="'+esc(file)+'">'
      + '<span class="rn">'+esc(s.vid)+'</span>'
      + '<span class="rt">'+esc(s.title || file)+'</span>'
      + '<span class="rarrows">'
      +   '<button type="button" class="arrowbtn" data-move="-1" data-file="'+esc(file)+'" title="move up">&uarr;</button>'
      +   '<button type="button" class="arrowbtn" data-move="1" data-file="'+esc(file)+'" title="move down">&darr;</button>'
      + '</span></div>';
  }

  function pinsForFile(file){
    var s = STATE.slides[file] || {};
    var pins = [], n = 0;
    (s.comments || []).forEach(function(c){
      if(c.anchor){
        n++;
        pins.push({num: n, anchor: c.anchor, target: c.target, view: c.view || 'html',
                   text: c.text || '', round: c.round, cid: c.cid});
      }
    });
    return pins;
  }

  function pinLayerHtml(file){
    if(pinsHidden) return '<div class="pinlayer"></div>';
    var marks = pinsForFile(file).map(function(p){
      var a = p.anchor;
      var box = (a.w > 0 || a.h > 0)
        ? '<div class="pinbox" style="left:'+a.x+'px;top:'+a.y+'px;width:'+a.w+'px;height:'+a.h+'px;"></div>'
        : '';
      var tip = '<div class="pintip'+(a.x > 960 ? ' left' : '')+'">'
        + '<div class="tiptop"><span class="tipmeta">#'+p.num+' &middot; round '+esc(String(p.round||''))+' &middot; '+(p.view==='ppt'?'PowerPoint':'HTML')+'</span>'
        +   '<span class="tipctrls">'
        +     '<button type="button" class="tipedit" data-file="'+esc(file)+'" data-cid="'+esc(p.cid)+'">edit</button>'
        +     '<button type="button" class="tipdel" data-file="'+esc(file)+'" data-cid="'+esc(p.cid)+'">&times;</button>'
        +   '</span></div>'
        + '<span class="tiptext">'+esc(p.text)+'</span></div>';
      return box + '<div class="pinmarker" style="left:'+a.x+'px;top:'+a.y+'px;">'+p.num+tip+'</div>';
    }).join('');
    return '<div class="pinlayer">'+marks+'</div>';
  }

  function pinCaptureHtml(file){
    return pinMode[file] ? '<div class="pincap" data-file="'+esc(file)+'"></div>' : '';
  }

  function pinPopoverHtml(file, draft){
    var mode = draft.view || 'html';
    return '<div class="pinpop" style="left:'+draft.popLeft+'px;top:'+draft.popTop+'px;">'
      + '<textarea placeholder="Pin note...">'+esc(draft.text || '')+'</textarea>'
      + '<div class="viewtoggle">'
      +   '<button type="button" class="tbtn'+(mode==='html'?' on':'')+'" data-pinview="html" data-file="'+esc(file)+'">HTML</button>'
      +   '<button type="button" class="tbtn'+(mode==='ppt'?' on':'')+'" data-pinview="ppt" data-file="'+esc(file)+'">PowerPoint</button>'
      + '</div>'
      + '<div class="pinpopbtns">'
      +   '<button type="button" class="actbtn pincancel" data-file="'+esc(file)+'">Cancel</button>'
      +   '<button type="button" class="savebtn pinsave" data-file="'+esc(file)+'">Save</button>'
      + '</div></div>';
  }

  function commentEntryHtml(file, c, pinNum){
    var key = ckey(file, c.cid);
    var viewLabel = c.view === 'ppt' ? 'PowerPoint' : 'HTML';
    var meta = 'round '+c.round+' &middot; '+viewLabel+' &middot; '+esc(c.ts) + (c.edited_ts ? ' &middot; edited' : '');
    if(pinNum){
      var t = c.target;
      var sel = (t && t.tag) ? t.tag + (t.classes ? '.'+t.classes.split(/\\s+/).join('.') : '') : '';
      var rawExcerpt = (t && t.text) || '';
      var excerpt = rawExcerpt ? ' "'+esc(rawExcerpt.length > 40 ? rawExcerpt.slice(0,40)+'...' : rawExcerpt)+'"' : '';
      meta = '#'+pinNum+' &middot; ' + meta + (sel ? ' &middot; '+esc(sel)+excerpt : '');
    }
    var controls = '<span class="cmtctrls">'
      + '<button type="button" class="cmtedit" data-file="'+esc(file)+'" data-cid="'+esc(c.cid)+'">edit</button>'
      + '<button type="button" class="cmtdel" data-file="'+esc(file)+'" data-cid="'+esc(c.cid)+'">&times;</button>'
      + '</span>';
    var body;
    if(commentEditOpen[key]){
      var draft = commentEditDraft[key] || {text: c.text, view: c.view || 'html'};
      body = '<div class="cmtedittbox">'
        + '<textarea>'+esc(draft.text)+'</textarea>'
        + '<div class="viewtoggle">'
        +   '<button type="button" class="tbtn'+(draft.view==='html'?' on':'')+'" data-eview="html" data-file="'+esc(file)+'" data-cid="'+esc(c.cid)+'">HTML</button>'
        +   '<button type="button" class="tbtn'+(draft.view==='ppt'?' on':'')+'" data-eview="ppt" data-file="'+esc(file)+'" data-cid="'+esc(c.cid)+'">PowerPoint</button>'
        + '</div>'
        + '<div class="pinpopbtns">'
        +   '<button type="button" class="actbtn cmteditcancel" data-file="'+esc(file)+'" data-cid="'+esc(c.cid)+'">Cancel</button>'
        +   '<button type="button" class="savebtn cmteditsave" data-file="'+esc(file)+'" data-cid="'+esc(c.cid)+'">Save</button>'
        + '</div></div>';
    } else {
      body = '<div class="cmttext">'+esc(c.text)+'</div>';
    }
    return '<div class="cmt" data-cid="'+esc(c.cid)+'"><div class="cmttop"><span class="cmtmeta">'+meta+'</span>'+controls+'</div>'+body+'</div>';
  }

  function commentsHtml(file, s){
    var n = 0;
    return (s.comments || []).map(function(c){
      var pinNum = null;
      if(c.anchor){ n++; pinNum = n; }
      return commentEntryHtml(file, c, pinNum);
    }).join('');
  }

  function paneHtml(file, i, archived){
    var s = STATE.slides[file] || {};
    var png = pngSrc(file, s);
    var mode = viewMode[file] || 'html';
    var showPng = png && mode === 'ppt';
    var frameClass = archived ? 'aframe' : 'frame';
    var media;
    if(s.missing){
      media = '<div class="missingmsg">file no longer on disk: '+esc(file)+'</div>';
    } else if(showPng){
      media = '<img src="'+png+'" alt="'+esc(file)+' (PowerPoint render)">';
    } else {
      media = '<iframe src="_workroom/'+encodeURIComponent(file)+'" scrolling="no" loading="lazy"></iframe>';
    }
    var badge = s.built_version
      ? 'built v'+('0'+s.built_version).slice(-2) + (s.built_at ? ' &middot; '+esc(s.built_at) : '')
      : 'not built';
    var toggle = png
      ? '<span class="viewtoggle">'
        + '<button type="button" class="tbtn'+(mode==='html'?' on':'')+'" data-view="html" data-file="'+esc(file)+'">HTML</button>'
        + '<button type="button" class="tbtn'+(mode==='ppt'?' on':'')+'" data-view="ppt" data-file="'+esc(file)+'">PowerPoint</button>'
        + '</span>'
      : '';
    var comments = commentsHtml(file, s);
    var box = commentOpen[file]
      ? (function(){
          var cvm = commentViewSel[file] || mode;
          return '<div class="cmtbox"><div class="cmtboxcol">'
            + '<textarea placeholder="Leave a comment...">'+esc(commentDraftText[file] || '')+'</textarea>'
            + '<div class="viewtoggle">'
            +   '<button type="button" class="tbtn'+(cvm==='html'?' on':'')+'" data-cview="html" data-file="'+esc(file)+'">HTML</button>'
            +   '<button type="button" class="tbtn'+(cvm==='ppt'?' on':'')+'" data-cview="ppt" data-file="'+esc(file)+'">PowerPoint</button>'
            + '</div></div>'
            + '<button type="button" class="savebtn" data-file="'+esc(file)+'">Save</button></div>';
        })()
      : '';
    var promoteBtn = s.built_version
      ? '<button type="button" class="actbtn" data-action="promote" data-file="'+esc(file)+'">Promote</button>'
      : '';
    var refBadge = s.promoted
      ? '<span class="refbadge">reference: '+esc(s.promoted.as)+'</span>'
      : '';
    var promoBox = promoteOpen[file] ? promoteFormHtml(file, s) : '';
    var popover = (pinNoteOpen[file] && pinDraft[file]) ? pinPopoverHtml(file, pinDraft[file]) : '';
    return '<section class="pane'+(archived?' archived':'')+'" data-file="'+esc(file)+'">'
      + '<div class="cap">'
      +   '<span class="idx">'+(i+1)+'</span>'
      +   '<span class="vid">'+esc(s.vid)+'</span>'
      +   '<span class="ttl">'+esc(s.title || file)+'</span>'
      +   (s.missing ? '<span class="miss">missing</span>' : '')
      +   '<span class="fn">'+esc(file)+'</span>'
      +   '<span class="round">round '+(s.rounds||1)+'</span>'
      +   '<span class="badge">'+badge+'</span>'
      +   refBadge
      +   toggle
      +   '<button type="button" class="actbtn archbtn" data-action="'+(archived?'restore':'archive')+'" data-file="'+esc(file)+'">'+(archived?'Restore':'Archive')+'</button>'
      +   '<button type="button" class="actbtn" data-action="comment" data-file="'+esc(file)+'">Comment</button>'
      +   '<button type="button" class="actbtn pinbtn'+(pinMode[file]?' on':'')+'" data-action="pin" data-file="'+esc(file)+'">'+(pinMode[file]?'Pin: click or drag':'Pin')+'</button>'
      +   promoteBtn
      + '</div>'
      + box
      + promoBox
      + (comments ? '<div class="cmtlist">'+comments+'</div>' : '')
      + '<div class="paneMedia">'
      +   '<div class="'+frameClass+'">'+media+pinLayerHtml(file)+pinCaptureHtml(file)+'</div>'
      +   popover
      + '</div>'
      + '</section>';
  }

  function promoteFormHtml(file, s){
    var err = promoteError[file] ? '<div class="promoerr">'+esc(promoteError[file])+'</div>' : '';
    var defaultSlug = slugify(s.title || file);
    var tiers = ['1','2','3'].map(function(t){
      return '<label><input type="radio" name="tier_'+esc(file)+'" value="'+t+'"'+(t==='1'?' checked':'')+'> T'+t+'</label>';
    }).join('');
    var options = MSGTYPES.map(function(m){ return '<option value="'+m+'">'+m+'</option>'; }).join('');
    return '<div class="promobox" data-file="'+esc(file)+'">'
      + err
      + '<div class="prow"><span>Tier</span>'+tiers+'</div>'
      + '<div class="prow"><span>Message type</span><select class="promsgtype">'+options+'</select></div>'
      + '<div class="prow"><span>Slug</span><input type="text" class="proslug" maxlength="40" value="'+esc(defaultSlug)+'"></div>'
      + '<div class="prow"><span>What to learn</span><input type="text" class="prolearn" placeholder="one line for the reference manifest"></div>'
      + '<button type="button" class="savebtn prosave" data-file="'+esc(file)+'">Save</button>'
      + '</div>';
  }

  function render(){
    var act = activeFiles(), arch = archivedFiles();
    document.getElementById('activeCount').textContent = act.length;
    document.getElementById('archCount').textContent = arch.length;
    document.getElementById('metaLine').textContent =
      STATE.order.length + ' slides total \\u00b7 ' + act.length + ' active \\u00b7 ' + arch.length + ' archived';
    var rtbN = STATE.rounds_to_build_n || 0;
    document.getElementById('rtbLine').textContent = rtbN > 0
      ? 'rounds to build: mean ' + STATE.rounds_to_build_mean.toFixed(1) + ' over ' + rtbN + ' built slides'
      : '';
    document.getElementById('activeRail').innerHTML = act.map(railItem).join('');
    document.getElementById('archRail').innerHTML = arch.map(railItem).join('');
    document.getElementById('activePanes').innerHTML = act.map(function(f,i){ return paneHtml(f,i,false); }).join('');
    document.getElementById('archivedPanes').innerHTML = arch.map(function(f,i){ return paneHtml(f,i,true); }).join('');
    document.getElementById('buildBtn').textContent = 'Build deck ('+act.length+' active)';
    bindEvents();
  }

  function bindEvents(){
    document.querySelectorAll('.railitem').forEach(function(el){
      el.addEventListener('click', function(e){
        if(e.target.closest('.arrowbtn')) return;
        var pane = document.querySelector('.pane[data-file="'+CSS.escape(el.dataset.file)+'"]');
        if(pane) pane.scrollIntoView({behavior:'smooth', block:'start'});
      });
    });
    document.querySelectorAll('.arrowbtn').forEach(function(b){
      b.addEventListener('click', function(e){
        e.stopPropagation();
        moveSlide(b.dataset.file, parseInt(b.dataset.move, 10));
      });
    });
    document.querySelectorAll('.actbtn[data-action="archive"]').forEach(function(b){
      b.addEventListener('click', function(){ slideAction(b.dataset.file, 'archive'); });
    });
    document.querySelectorAll('.actbtn[data-action="restore"]').forEach(function(b){
      b.addEventListener('click', function(){ slideAction(b.dataset.file, 'restore'); });
    });
    document.querySelectorAll('.actbtn[data-action="comment"]').forEach(function(b){
      b.addEventListener('click', function(){
        commentOpen[b.dataset.file] = !commentOpen[b.dataset.file];
        render();
        if(commentOpen[b.dataset.file]){
          var pane = document.querySelector('.pane[data-file="'+CSS.escape(b.dataset.file)+'"]');
          var ta = pane && pane.querySelector('textarea');
          if(ta) ta.focus();
        }
      });
    });
    document.querySelectorAll('.cmtbox .savebtn').forEach(function(b){
      b.addEventListener('click', function(){
        var box = b.closest('.cmtbox');
        var text = box.querySelector('textarea').value.trim();
        if(!text) return;
        var file = b.dataset.file;
        var view = commentViewSel[file] || viewMode[file] || 'html';
        postComment(file, text, view);
      });
    });
    document.querySelectorAll('.tbtn[data-view]').forEach(function(b){
      b.addEventListener('click', function(){
        viewMode[b.dataset.file] = b.dataset.view;
        render();
      });
    });
    document.querySelectorAll('.tbtn[data-cview]').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        var box = b.closest('.cmtbox');
        commentDraftText[file] = box.querySelector('textarea').value;
        commentViewSel[file] = b.dataset.cview;
        render();
        var pane = document.querySelector('.pane[data-file="'+CSS.escape(file)+'"]');
        var ta = pane && pane.querySelector('.cmtbox textarea');
        if(ta) ta.focus();
      });
    });
    document.querySelectorAll('.cmtedit').forEach(function(b){
      b.addEventListener('click', function(){ openCommentEdit(b.dataset.file, b.dataset.cid, true); });
    });
    document.querySelectorAll('.cmtdel').forEach(function(b){
      b.addEventListener('click', function(){
        if(!confirm('Remove this comment?')) return;
        deleteComment(b.dataset.file, b.dataset.cid);
      });
    });
    document.querySelectorAll('.tbtn[data-eview]').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file, cid = b.dataset.cid, key = ckey(file, cid);
        var cmtEl = b.closest('.cmt');
        var ta = cmtEl && cmtEl.querySelector('textarea');
        if(!commentEditDraft[key]) commentEditDraft[key] = {text: '', view: 'html'};
        if(ta) commentEditDraft[key].text = ta.value;
        commentEditDraft[key].view = b.dataset.eview;
        render();
        var pane = document.querySelector('.cmt[data-cid="'+CSS.escape(cid)+'"] textarea');
        if(pane) pane.focus();
      });
    });
    document.querySelectorAll('.cmteditsave').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file, cid = b.dataset.cid, key = ckey(file, cid);
        var cmtEl = b.closest('.cmt');
        var text = cmtEl.querySelector('textarea').value.trim();
        if(!text) return;
        var draft = commentEditDraft[key] || {};
        editComment(file, cid, text, draft.view || 'html');
      });
    });
    document.querySelectorAll('.cmteditcancel').forEach(function(b){
      b.addEventListener('click', function(){
        var key = ckey(b.dataset.file, b.dataset.cid);
        commentEditOpen[key] = false;
        commentEditDraft[key] = null;
        render();
      });
    });
    document.querySelectorAll('.tipedit').forEach(function(b){
      b.addEventListener('click', function(e){
        e.stopPropagation();
        openCommentEdit(b.dataset.file, b.dataset.cid, false);
        var target = document.querySelector('.cmt[data-cid="'+CSS.escape(b.dataset.cid)+'"]');
        if(target){
          target.scrollIntoView({behavior: 'smooth', block: 'center'});
          var ta = target.querySelector('textarea');
          if(ta) ta.focus();
        }
      });
    });
    document.querySelectorAll('.tipdel').forEach(function(b){
      b.addEventListener('click', function(e){
        e.stopPropagation();
        if(!confirm('Remove this comment?')) return;
        deleteComment(b.dataset.file, b.dataset.cid);
      });
    });
    document.querySelectorAll('.actbtn[data-action="pin"]').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        pinMode[file] = !pinMode[file];
        if(pinMode[file]){
          pinNoteOpen[file] = false;
          pinDraft[file] = null;
        }
        render();
      });
    });
    document.querySelectorAll('.tbtn[data-pinview]').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        var pop = b.closest('.pinpop');
        if(pinDraft[file]) pinDraft[file].text = pop.querySelector('textarea').value;
        pinDraft[file].view = b.dataset.pinview;
        render();
        var pane = document.querySelector('.pane[data-file="'+CSS.escape(file)+'"]');
        var ta = pane && pane.querySelector('.pinpop textarea');
        if(ta) ta.focus();
      });
    });
    document.querySelectorAll('.pinsave').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        var pop = b.closest('.pinpop');
        var text = pop.querySelector('textarea').value.trim();
        if(!text) return;
        var draft = pinDraft[file];
        postComment(file, text, draft.view, draft.anchor, draft.target);
      });
    });
    document.querySelectorAll('.pincancel').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        pinDraft[file] = null;
        pinNoteOpen[file] = false;
        render();
      });
    });
    bindPinCapture();
    document.querySelectorAll('.actbtn[data-action="promote"]').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        promoteOpen[file] = !promoteOpen[file];
        promoteError[file] = null;
        render();
      });
    });
    document.querySelectorAll('.prosave').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file;
        var box = b.closest('.promobox');
        var tierInput = box.querySelector('input[type=radio]:checked');
        var payload = {
          tier: tierInput ? tierInput.value : '1',
          msgtype: box.querySelector('.promsgtype').value,
          slug: box.querySelector('.proslug').value.trim(),
          learn: box.querySelector('.prolearn').value.trim()
        };
        postJSON('/api/slide/'+encodeURIComponent(file)+'/promote', payload).then(function(out){
          if(out && out.error){
            promoteError[file] = out.error;
            render();
            return;
          }
          promoteOpen[file] = false;
          promoteError[file] = null;
          STATE = out;
          render();
        });
      });
    });
    panes = Array.prototype.slice.call(document.querySelectorAll('#activePanes .pane'));
    curIdx = Math.min(curIdx, Math.max(panes.length-1, 0));
  }

  function postJSON(url, body){
    return fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    }).then(function(r){ return r.json(); });
  }

  function slideAction(file, action){
    postJSON('/api/slide/'+encodeURIComponent(file)+'/'+action, {}).then(function(out){
      if(out && out.error) return;
      STATE = out; render();
    });
  }

  function postComment(file, text, view, anchor, target){
    var payload = {text: text, view: view || 'html'};
    if(anchor) payload.anchor = anchor;
    if(target) payload.target = target;
    postJSON('/api/slide/'+encodeURIComponent(file)+'/comment', payload).then(function(out){
      if(out && out.error) return;
      STATE = out;
      commentOpen[file] = false;
      commentDraftText[file] = '';
      commentViewSel[file] = null;
      pinDraft[file] = null;
      pinNoteOpen[file] = false;
      render();
    });
  }

  // ---- comment edit / delete (stable cid, independent of the comment's position) ----

  function openCommentEdit(file, cid, focusNow){
    var key = ckey(file, cid);
    var s = STATE.slides[file] || {};
    var c = (s.comments || []).find(function(x){ return x.cid === cid; });
    if(!c) return;
    commentEditOpen[key] = true;
    commentEditDraft[key] = {text: c.text, view: c.view || 'html'};
    render();
    if(focusNow){
      var ta = document.querySelector('.cmt[data-cid="'+CSS.escape(cid)+'"] textarea');
      if(ta) ta.focus();
    }
  }

  function editComment(file, cid, text, view){
    var key = ckey(file, cid);
    postJSON('/api/slide/'+encodeURIComponent(file)+'/comment/'+encodeURIComponent(cid)+'/edit',
             {text: text, view: view}).then(function(out){
      if(out && out.error) return;
      STATE = out;
      commentEditOpen[key] = false;
      commentEditDraft[key] = null;
      render();
    });
  }

  function deleteComment(file, cid){
    postJSON('/api/slide/'+encodeURIComponent(file)+'/comment/'+encodeURIComponent(cid)+'/delete', {})
      .then(function(out){
        if(out && out.error) return;
        STATE = out;
        render();
      });
  }

  // ---- Feature 2: pinned comments - crosshair capture, drag-to-box, element detection ----

  function meaningfulTarget(doc, sx, sy){
    var el = doc.elementFromPoint(sx, sy);
    if(!el || !el.tagName) return null;
    var tag = el.tagName.toLowerCase();
    if(tag === 'html' || tag === 'body') return null;
    if(el.classList && el.classList.contains('slide')) return null;
    return el;
  }

  function computeTarget(file, sx, sy){
    var pane = document.querySelector('.pane[data-file="'+CSS.escape(file)+'"]');
    var iframe = pane && pane.querySelector('.frame iframe');
    if(!iframe) return null;   // PowerPoint view (an <img>, not an iframe) - nothing to hit-test
    try {
      var doc = iframe.contentDocument;
      if(!doc) return null;
      var el = meaningfulTarget(doc, sx, sy);
      if(!el) return null;
      var r = el.getBoundingClientRect();   // iframe's own 1280x720 viewport - unaffected by the
                                             // parent page's CSS transform on the iframe itself
      var text = (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 90);
      var classes = (el.className && typeof el.className === 'string') ? el.className.trim() : '';
      return {
        tag: el.tagName.toLowerCase(),
        classes: classes,
        id: el.id || '',
        text: text,
        box: {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)}
      };
    } catch(e){
      return null;   // cross-origin or anything else going wrong - never blocks saving the pin
    }
  }

  function finishPin(file, rect, downX, downY, upX, upY){
    function toSlide(cx, cy){
      return [(cx - rect.left) / rect.width * 1280, (cy - rect.top) / rect.height * 720];
    }
    var p1 = toSlide(downX, downY), p2 = toSlide(upX, upY);
    var moved = Math.abs(upX - downX) > 3 || Math.abs(upY - downY) > 3;
    var anchor;
    if(moved){
      var x0 = Math.min(p1[0], p2[0]), x1 = Math.max(p1[0], p2[0]);
      var y0 = Math.min(p1[1], p2[1]), y1 = Math.max(p1[1], p2[1]);
      anchor = {x: Math.round(x0), y: Math.round(y0), w: Math.round(x1 - x0), h: Math.round(y1 - y0)};
    } else {
      anchor = {x: Math.round(p2[0]), y: Math.round(p2[1]), w: 0, h: 0};
    }
    var cx = anchor.x + anchor.w / 2, cy = anchor.y + anchor.h / 2;
    var target = null;
    try { target = computeTarget(file, cx, cy); } catch(e){ target = null; }

    var localX = (moved ? Math.min(downX, upX) : upX) - rect.left;
    var localY = (moved ? Math.min(downY, upY) : upY) - rect.top;
    var popW = 260, popH = 180;
    var left = Math.max(4, Math.min(localX, rect.width - popW - 4));
    var top = Math.max(4, Math.min(localY, rect.height - popH - 4));

    pinDraft[file] = {anchor: anchor, target: target, text: '', view: viewMode[file] || 'html',
                       popLeft: Math.round(left), popTop: Math.round(top)};
    pinNoteOpen[file] = true;
    pinMode[file] = false;
    render();
    var pane = document.querySelector('.pane[data-file="'+CSS.escape(file)+'"]');
    var ta = pane && pane.querySelector('.pinpop textarea');
    if(ta) ta.focus();
  }

  function bindPinCapture(){
    document.querySelectorAll('.pincap').forEach(function(cap){
      cap.addEventListener('mousedown', function(e){
        e.preventDefault();
        var file = cap.dataset.file;
        var rect = cap.getBoundingClientRect();
        var rubber = document.createElement('div');
        rubber.className = 'pinrubber';
        cap.appendChild(rubber);
        dragState = {file: file, rect: rect, downX: e.clientX, downY: e.clientY, rubber: rubber};

        function onMove(ev){
          if(!dragState) return;
          var x0 = Math.min(dragState.downX, ev.clientX) - dragState.rect.left;
          var y0 = Math.min(dragState.downY, ev.clientY) - dragState.rect.top;
          var w = Math.abs(ev.clientX - dragState.downX);
          var h = Math.abs(ev.clientY - dragState.downY);
          dragState.rubber.style.left = x0 + 'px';
          dragState.rubber.style.top = y0 + 'px';
          dragState.rubber.style.width = w + 'px';
          dragState.rubber.style.height = h + 'px';
        }
        function onUp(ev){
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          var ds = dragState;
          dragState = null;
          if(ds.rubber && ds.rubber.parentNode) ds.rubber.parentNode.removeChild(ds.rubber);
          finishPin(ds.file, ds.rect, ds.downX, ds.downY, ev.clientX, ev.clientY);
        }
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
    });
  }

  function moveSlide(file, dir){
    var st = (STATE.slides[file]||{}).status;
    var list = STATE.order.filter(function(f){ return (STATE.slides[f]||{}).status === st; });
    var idx = list.indexOf(file), j = idx + dir;
    if(j < 0 || j >= list.length) return;
    var a = STATE.order.indexOf(file), b = STATE.order.indexOf(list[j]);
    var newOrder = STATE.order.slice();
    var tmp = newOrder[a]; newOrder[a] = newOrder[b]; newOrder[b] = tmp;
    postJSON('/api/order', {order: newOrder}).then(function(out){
      if(out && out.error) return;
      STATE = out; render();
    });
  }

  function refreshState(){
    return fetch('/api/state').then(function(r){ return r.json(); }).then(function(out){
      STATE = out; render();
    });
  }

  function setBuildUi(status, result){
    BUILD = {status: status, result: result};
    var btn = document.getElementById('buildBtn');
    var txt = document.getElementById('buildStatusText');
    var link = document.getElementById('buildLinkText');
    btn.disabled = (status === 'running');
    if(status === 'running'){
      txt.textContent = 'building...';
      link.textContent = '';
    } else if(status === 'done' && result){
      txt.textContent = 'v'+('0'+result.version).slice(-2)+' built, '+(result.slides||[]).length+' slides';
      link.textContent = result.file || '';
    } else if(status === 'error'){
      txt.textContent = 'build failed: ' + ((result && result.log) ? result.log.slice(0,400) : 'unknown error');
      link.textContent = '';
    } else {
      txt.textContent = 'not built';
      link.textContent = '';
    }
  }

  function pollBuild(){
    if(pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function(){
      fetch('/api/build/status').then(function(r){ return r.json(); }).then(function(b){
        if(b.status !== 'running'){
          clearInterval(pollTimer); pollTimer = null;
          setBuildUi(b.status, b.result);
          refreshState();
        }
      });
    }, 1200);
  }

  function startBuild(){
    setBuildUi('running', null);
    postJSON('/api/build', {}).then(function(out){
      if(out && out.ok === false){
        setBuildUi('error', {log: out.error || 'could not start build'});
        return;
      }
      pollBuild();
    });
  }

  function setHidePinsUi(){
    var btn = document.getElementById('hidePinsToggle');
    btn.classList.toggle('on', pinsHidden);
    btn.textContent = pinsHidden ? 'Show pins' : 'Hide pins';
  }

  document.getElementById('hidePinsToggle').addEventListener('click', function(){
    pinsHidden = !pinsHidden;
    try { localStorage.setItem('wr_hide_pins_' + STATE.deck, pinsHidden ? '1' : '0'); } catch(e){}
    setHidePinsUi();
    render();
  });
  setHidePinsUi();

  addEventListener('keydown', function(e){
    if(e.key !== 'Escape') return;
    var openFile = null;
    Object.keys(pinNoteOpen).forEach(function(f){ if(pinNoteOpen[f]) openFile = f; });
    if(openFile){
      pinNoteOpen[openFile] = false;
      pinDraft[openFile] = null;
      render();
      return;
    }
    var openEditKey = null;
    Object.keys(commentEditOpen).forEach(function(k){ if(commentEditOpen[k]) openEditKey = k; });
    if(openEditKey){
      commentEditOpen[openEditKey] = false;
      commentEditDraft[openEditKey] = null;
      render();
      return;
    }
    var anyPinMode = false;
    Object.keys(pinMode).forEach(function(f){ if(pinMode[f]){ pinMode[f] = false; anyPinMode = true; } });
    if(anyPinMode) render();
  });

  document.getElementById('buildBtn').addEventListener('click', startBuild);
  document.getElementById('archToggle').addEventListener('click', function(){
    archOpen = !archOpen;
    document.getElementById('archRail').hidden = !archOpen;
    document.getElementById('archivedPanes').hidden = !archOpen;
    document.getElementById('archToggle').classList.toggle('open', archOpen);
  });
  Array.prototype.forEach.call(document.querySelectorAll('.zooms button'), function(b){
    b.addEventListener('click', function(){
      document.body.className = b.dataset.z;
      document.getElementById('activePanes').classList.toggle('grid', b.dataset.z === 'z33');
      Array.prototype.forEach.call(document.querySelectorAll('.zooms button'), function(x){
        x.classList.toggle('on', x === b);
      });
    });
  });
  addEventListener('keydown', function(e){
    var tag = e.target.tagName;
    if(tag === 'INPUT' || tag === 'TEXTAREA') return;
    if(e.key === 'j' || e.key === 'ArrowDown') curIdx = Math.min(curIdx+1, panes.length-1);
    else if(e.key === 'k' || e.key === 'ArrowUp') curIdx = Math.max(curIdx-1, 0);
    else return;
    e.preventDefault();
    if(panes[curIdx]) panes[curIdx].scrollIntoView({behavior:'smooth', block:'start'});
  });

  render();
  if(BUILD && BUILD.status === 'running'){
    setBuildUi('running', null);
    pollBuild();
  } else {
    setBuildUi(BUILD ? BUILD.status : 'idle', BUILD ? BUILD.result : null);
  }
})();
"""


# ---------------------------------------------------------------- Analysis tab JS
#
# A second, independent IIFE. It talks to the Slides-tab IIFE above only through the two tab
# buttons and three container elements (#slidesView, #analysisView, nav) - no shared state - so
# it can lazily fetch /api/analysis on first activation without touching STATE/render() above.
ANALYSIS_JS = """
(function(){
  var loaded = false, loading = false;
  var DATA = null;
  var sel = {};        // file -> {sourceId, ref}
  var wholeMode = {};  // "file::sourceId" -> bool
  var wholeCache = {}; // "file::sourceId" -> grid

  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function fmtVal(v){
    if(v === null || v === undefined || v === '') return '';
    if(typeof v === 'number'){
      var a = Math.abs(v);
      var s = (Math.round(a * 10) / 10).toFixed(1);
      return v < 0 ? '(' + s + ')' : s;
    }
    return String(v);
  }

  function colIdx(col){ var idx = 0; col = col.toUpperCase();
    for(var i = 0; i < col.length; i++){ idx = idx * 26 + (col.charCodeAt(i) - 64); } return idx; }
  function idxCol(idx){ var s = '';
    while(idx > 0){ var rem = (idx - 1) % 26; s = String.fromCharCode(65 + rem) + s; idx = Math.floor((idx - 1) / 26); }
    return s; }

  // Mirrors analysis.precedents' same-sheet handling (client-side, for instant highlighting):
  // cross-sheet refs are stripped out first, then plain same-sheet refs/ranges are expanded.
  function precedentRefs(formula){
    if(!formula) return [];
    var out = [];
    var stripped = formula.replace(
      /(?:'[^']+'|[A-Za-z_][A-Za-z0-9_. ]*)!\\$?[A-Za-z]{1,3}\\$?\\d+(?::\\$?[A-Za-z]{1,3}\\$?\\d+)?/g, ' ');
    var re = /(?<![A-Za-z0-9_])\\$?([A-Za-z]{1,3})\\$?(\\d+)(?::\\$?([A-Za-z]{1,3})\\$?(\\d+))?(?![A-Za-z0-9(_])/g;
    var m;
    while((m = re.exec(stripped))){
      var c1 = m[1], r1 = parseInt(m[2], 10);
      var c2 = m[3] || c1, r2 = m[4] ? parseInt(m[4], 10) : r1;
      var i1 = colIdx(c1), i2 = colIdx(c2);
      for(var r = Math.min(r1, r2); r <= Math.max(r1, r2); r++){
        for(var ci = Math.min(i1, i2); ci <= Math.max(i1, i2); ci++){ out.push(idxCol(ci) + r); }
      }
    }
    return out;
  }

  function cellAt(grid, ref){
    if(!grid || !grid.rows || !ref) return null;
    for(var i = 0; i < grid.rows.length; i++){
      var cells = grid.rows[i].cells;
      for(var j = 0; j < cells.length; j++){ if(cells[j].ref === ref) return cells[j]; }
    }
    return null;
  }

  function shownMarkers(sidecar, sourceId){
    // Only a figure whose `cell` is a single, unambiguous reference gets a sand badge - a
    // compound expression (e.g. "E45,D45" for a figure that is itself a difference of two
    // other figures) has no one cell to badge, per the sidecar contract ("no grid badge if
    // you cannot map an expression").
    var out = {};
    (sidecar.figures || []).forEach(function(fg){
      var cell = String(fg.cell || '');
      if(fg.source === sourceId && /^[A-Za-z]{1,3}\\d+$/.test(cell)) out[cell] = fg.marker;
    });
    return out;
  }

  function firstSelectableRef(sidecar, sourceId){
    var ref = null;
    (sidecar.figures || []).some(function(fg){
      if(fg.source === sourceId && /^[A-Za-z]{1,3}\\d+$/.test(String(fg.cell || ''))){ ref = fg.cell; return true; }
      return false;
    });
    return ref;
  }

  function gridHtml(grid, sidecar, sourceId, selRef, precRefs){
    if(!grid) return '<div class="aerr">no data</div>';
    if(grid.error) return '<div class="aerr">' + esc(grid.error) + '</div>';
    var shown = shownMarkers(sidecar, sourceId);
    var cols = grid.cols || [];
    var h = '<div class="agridwrap"><table class="agrid"><tr><th style="width:34px"></th>';
    cols.forEach(function(c){ h += '<th>' + esc(c) + '</th>'; });
    h += '</tr>';
    (grid.rows || []).forEach(function(row){
      h += '<tr><td class="arn">' + row.row + '</td>';
      row.cells.forEach(function(cell){
        var cls;
        if(cell.kind === 'text') cls = 'atxt';
        else if(cell.kind === 'empty') cls = 'aempty';
        else cls = 'anum' + (cell.kind === 'input' ? ' ainp' : cell.kind === 'link' ? ' alink' : '');
        if(cell.bold) cls += ' abold';
        if(shown[cell.ref]) cls += ' ashown';
        if(cell.ref === selRef) cls += ' asel';
        if(precRefs.indexOf(cell.ref) >= 0) cls += ' aprec';
        var txt = esc(fmtVal(cell.value));
        h += '<td class="' + cls + '" data-ref="' + esc(cell.ref) + '" data-m="' + (shown[cell.ref] || '')
          + '" title="' + esc(cell.ref) + '">' + txt + '</td>';
      });
      h += '</tr>';
    });
    h += '</table></div>';
    return h;
  }

  function sectionHtml(slide, idx){
    var sc = slide.sidecar;
    if(!sc || !sc.sources || !sc.sources.length){
      return '<div class="asec nosc">' + (idx + 1) + ' ' + esc(slide.title || slide.file)
        + ' - no data sources recorded</div>';
    }
    var st = sel[slide.file];
    if(!st){
      var srcId0 = sc.sources[0].id;
      st = {sourceId: srcId0, ref: firstSelectableRef(sc, srcId0)};
      sel[slide.file] = st;
    }
    var src = sc.sources.filter(function(s){ return s.id === st.sourceId; })[0] || sc.sources[0];
    var wkey = slide.file + '::' + st.sourceId;
    var grid = (wholeMode[wkey] && wholeCache[wkey]) ? wholeCache[wkey] : (slide.grids || {})[st.sourceId];
    var selCell = cellAt(grid, st.ref);
    var precRefs = selCell ? precedentRefs(selCell.formula) : [];
    var formulaText = selCell
      ? (selCell.formula ? selCell.formula : (selCell.kind === 'empty' ? '' : 'typed number, no formula'))
      : '';

    var tabs = sc.sources.map(function(s){
      return '<span class="' + (s.id === st.sourceId ? 'on' : '') + '" data-file="' + esc(slide.file)
        + '" data-src="' + esc(s.id) + '">' + esc(s.sheet || s.id) + '</span>';
    }).join('');

    var markers = (sc.figures || []).map(function(fg){
      if(!fg.box || fg.source !== st.sourceId) return '';
      var cx = fg.box.x + fg.box.w / 2, cy = fg.box.y + fg.box.h / 2;
      var left = (cx / 1280 * 100).toFixed(2), top = (cy / 720 * 100).toFixed(2);
      var firstCell = String(fg.cell || '').split(',')[0].trim();
      return '<div class="amk' + (firstCell === st.ref ? ' on' : '') + '" style="left:' + left
        + '%;top:' + top + '%;" data-file="' + esc(slide.file) + '" data-src="' + esc(fg.source)
        + '" data-cell="' + esc(firstCell) + '">' + esc(fg.marker) + '</div>';
    }).join('');
    var thumbHtml = '<div class="aframe2"><iframe src="_workroom/' + encodeURIComponent(slide.file)
      + '" scrolling="no" loading="lazy"></iframe>' + markers + '</div>';

    var errHtml = (slide.errors && slide.errors.length)
      ? '<div class="aerr">' + slide.errors.map(esc).join('<br>') + '</div>' : '';
    var notesHtml = (sc.notes && sc.notes.length)
      ? '<ul class="anotes">' + sc.notes.map(function(n){ return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' : '';
    var figRows = (sc.figures || []).map(function(fg){
      return '<tr><td>' + esc(fg.marker) + '</td><td>' + esc(fg.shown || '') + '</td><td>' + esc(fg.label || '')
        + '</td><td>' + esc(fg.cell || '') + '</td><td>' + esc(fg.transform || '') + '</td></tr>';
    }).join('');
    var figTable = figRows
      ? '<table class="afigtable"><tr><th>Marker</th><th>Shown</th><th>Label</th><th>Cell</th><th>Transform</th></tr>'
        + figRows + '</table>' : '';

    var fileName = (src.file || '').split(/[\\\\/]/).pop();
    var ribbonRead = src.read ? 'read ' + src.read.slice(0, 10) : '';

    return '<div class="asec" data-file="' + esc(slide.file) + '">'
      + '<div class="acol-thumb">'
      +   '<div class="asub">' + (idx + 1) + ' ' + esc(slide.title || slide.file) + '</div>'
      +   thumbHtml + errHtml + notesHtml + figTable
      + '</div>'
      + '<div class="acol-xl"><div class="axl">'
      +   '<div class="aribbon"><span class="afile">' + esc(fileName) + '</span><span>' + esc(ribbonRead) + '</span>'
      +     '<button type="button" class="awholetoggle' + (wholeMode[wkey] ? ' on' : '') + '" data-file="'
      +       esc(slide.file) + '" data-src="' + esc(st.sourceId) + '">Whole sheet</button></div>'
      +   '<div class="afbar"><div class="aref">' + esc(st.ref || '') + '</div><div class="afx">fx</div>'
      +     '<div class="af">' + esc(formulaText) + '</div></div>'
      +   gridHtml(grid, sc, st.sourceId, st.ref, precRefs)
      +   '<div class="alegend"><span class="al1">shown on slide</span><span class="al2">feeds the selected cell</span>'
      +     '<span class="al3">typed number</span><span class="al4">link to another sheet</span></div>'
      +   '<div class="asheet-tabsx">' + tabs + '</div>'
      + '</div></div>'
      + '</div>';
  }

  function render(){
    if(!DATA) return;
    document.getElementById('analysisView').innerHTML = DATA.slides.map(sectionHtml).join('');
    bind();
  }

  function selectCell(file, sourceId, ref){
    sel[file] = {sourceId: sourceId, ref: ref};
    render();
    var esc2 = window.CSS && CSS.escape ? CSS.escape : function(s){ return s; };
    var td = document.querySelector('.asec[data-file="' + esc2(file) + '"] td[data-ref="' + esc2(ref) + '"]');
    if(td) td.scrollIntoView({block: 'center', inline: 'center'});
  }

  function bind(){
    document.querySelectorAll('.amk').forEach(function(m){
      m.addEventListener('click', function(){ selectCell(m.dataset.file, m.dataset.src, m.dataset.cell); });
    });
    document.querySelectorAll('.agrid td[data-ref]').forEach(function(td){
      td.addEventListener('click', function(){
        var file = td.closest('.asec').dataset.file;
        selectCell(file, sel[file].sourceId, td.dataset.ref);
      });
    });
    document.querySelectorAll('.asheet-tabsx span[data-src]').forEach(function(s){
      s.addEventListener('click', function(){
        sel[s.dataset.file] = {sourceId: s.dataset.src, ref: null};
        render();
      });
    });
    document.querySelectorAll('.awholetoggle').forEach(function(b){
      b.addEventListener('click', function(){
        var file = b.dataset.file, srcId = b.dataset.src, wkey = file + '::' + srcId;
        if(wholeMode[wkey]){ wholeMode[wkey] = false; render(); return; }
        var slide = DATA.slides.filter(function(s){ return s.file === file; })[0];
        var src = slide.sidecar.sources.filter(function(s){ return s.id === srcId; })[0];
        fetch('/api/analysis/sheet?whole=1&p=' + encodeURIComponent(src.file) + '&sheet=' + encodeURIComponent(src.sheet))
          .then(function(r){ return r.json(); })
          .then(function(grid){ wholeCache[wkey] = grid; wholeMode[wkey] = true; render(); });
      });
    });
  }

  function ensureLoaded(){
    if(loaded || loading) return;
    loading = true;
    fetch('/api/analysis').then(function(r){ return r.json(); }).then(function(out){
      DATA = out; loaded = true; loading = false; render();
    });
  }

  var tabSlides = document.getElementById('tabSlides');
  var tabAnalysis = document.getElementById('tabAnalysis');
  var navEl = document.querySelector('nav');
  var slidesView = document.getElementById('slidesView');
  var analysisView = document.getElementById('analysisView');
  if(tabSlides && tabAnalysis){
    tabSlides.addEventListener('click', function(){
      tabSlides.classList.add('on'); tabAnalysis.classList.remove('on');
      navEl.hidden = false; slidesView.hidden = false; analysisView.hidden = true;
    });
    tabAnalysis.addEventListener('click', function(){
      tabAnalysis.classList.add('on'); tabSlides.classList.remove('on');
      navEl.hidden = true; slidesView.hidden = true; analysisView.hidden = false;
      ensureLoaded();
    });
  }
})();
"""


def server_page_html(deck, state, build_status):
    css = SERVER_CSS.replace("__STACK__", FONT_STACK)
    acss = ANALYSIS_CSS.replace("__STACK__", FONT_STACK)
    state_json = json.dumps(state).replace("</", "<\\/")
    build_json = json.dumps(build_status).replace("</", "<\\/")
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        f'<title>{html.escape(deck)} - workroom</title>'
        f'<style>\n{SERVER_FONT_CSS}\n{css}\n{acss}\n</style></head><body>'
        "<header>"
        f'<h1>{html.escape(deck)}</h1>'
        '<div class="tabs">'
        '<button id="tabSlides" type="button" class="tabbtn on">Slides</button>'
        '<button id="tabAnalysis" type="button" class="tabbtn">Analysis</button>'
        "</div>"
        '<span class="meta" id="metaLine"></span>'
        '<span class="meta" id="rtbLine"></span>'
        '<button id="buildBtn" type="button">Build deck</button>'
        '<span id="buildStatusText" class="buildstatus"></span>'
        '<span id="buildLinkText" class="buildlink"></span>'
        '<button id="hidePinsToggle" type="button">Hide pins</button>'
        '<span class="zooms">'
        '<button data-z="" class="on" type="button">100%</button>'
        '<button data-z="z75" type="button">75%</button>'
        '<button data-z="z50" type="button">50%</button>'
        '<button data-z="z33" type="button">grid</button>'
        "</span>"
        "</header>"
        '<div class="wrap"><nav>'
        '<div class="rail-sec"><div class="rail-sec-title">Active (<span id="activeCount">0</span>)</div>'
        '<div id="activeRail"></div></div>'
        '<div class="rail-sec"><button id="archToggle" class="rail-sec-title toggle" type="button">'
        'Archived (<span id="archCount">0</span>)</button><div id="archRail" hidden></div></div>'
        "</nav><main>"
        '<div id="slidesView">'
        '<div id="activePanes"></div>'
        '<div id="archivedPanes" hidden></div>'
        "</div>"
        '<div id="analysisView" hidden></div>'
        "</main></div>"
        f'<script id="initial-state" type="application/json">{state_json}</script>'
        f'<script id="initial-build" type="application/json">{build_json}</script>'
        f"<script>{SERVER_JS}</script>"
        f"<script>{ANALYSIS_JS}</script>"
        "</body></html>"
    )


DEFAULT_IDLE_HOURS = 2
DEFAULT_PORT = 8765
PORT_TRIES = 30          # 8765-8794: a second deck moves to the next free port instead of failing
WHOAMI_APP = "deck-studio-workroom"


class WorkroomHTTPServer(http.server.ThreadingHTTPServer):
    """Exclusive bind. The stdlib default sets SO_REUSEADDR, which on Windows lets a second server
    bind a port that is already serving, silently: the browser then reaches whichever answers."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):   # Windows only
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _same_dir(a, b):
    import os
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


SERVER_FILE = ".workroom_server.json"   # in the deck folder while its server runs: {"port", "pid"}


def find_running(d):
    """Port of a workroom server already serving deck dir d, or None. Two servers on one deck
    would both write workroom_state.json, so a running one is reused instead. Reads the deck's
    SERVER_FILE and asks that one port who it is - never scans ports (on Windows each probe of a
    closed port hangs until the timeout)."""
    try:
        port = int(json.loads((Path(d) / SERVER_FILE).read_text(encoding="utf-8"))["port"])
    except Exception:  # noqa: BLE001 - no file, or unreadable: nothing running
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/whoami", timeout=2) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - stale file from a server that was killed
        return None
    if info.get("app") == WHOAMI_APP and _same_dir(info.get("dir", ""), d):
        return port
    return None


def write_server_file(d, port):
    import os
    try:
        (Path(d) / SERVER_FILE).write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass   # read-only deck folder: reuse detection is a convenience


def clear_server_file(d, port):
    f = Path(d) / SERVER_FILE
    try:
        if int(json.loads(f.read_text(encoding="utf-8")).get("port", -1)) == port:
            f.unlink()
    except Exception:  # noqa: BLE001
        pass


def bind_free(handler, start=DEFAULT_PORT, tries=PORT_TRIES):
    """(server, port) on the first free port from start; SystemExit if all are taken."""
    for p in range(start, start + tries):
        try:
            return WorkroomHTTPServer(("127.0.0.1", p), handler), p
        except OSError:
            continue
    print(f"workroom server: ports {start}-{start + tries - 1} are all in use; pass --port N")
    sys.exit(1)


def idle_watchdog(httpd, handler, build_status, idle_s, check_every=60.0):
    """Stop the server once no request has arrived for idle_s seconds and no build is running.
    Runs in a daemon thread; httpd.shutdown() makes serve_forever() return in the main thread."""
    while True:
        time.sleep(check_every)
        idle = time.monotonic() - handler.last_request[0]
        if idle >= idle_s and build_status.get("status") != "running":
            print(f"workroom server: no requests for {idle / 3600:.1f} h - stopping "
                  f"(--idle-hours to change, 0 = never)")
            httpd.shutdown()
            return


def serve(d, deck, port, open_browser, idle_hours=DEFAULT_IDLE_HOURS):
    running = find_running(d)
    if running is not None:
        url = f"http://127.0.0.1:{running}/"
        print(f"workroom server: already running for this deck at {url} - reusing it")
        if open_browser:
            _open_in_browser(url)
        return
    try:
        ledger.register(d)   # every deck ever served gets remembered for `ledger.py sync`
    except Exception:  # noqa: BLE001 - the ledger is a convenience, never blocks the server
        pass
    Handler, build_status = make_handler(d, deck)
    httpd, bound = bind_free(Handler, port)
    if bound != port:
        print(f"workroom server: port {port} is taken - using {bound}")
    port = bound
    write_server_file(d, port)
    url = f"http://127.0.0.1:{port}/"
    state_path = d / STATE_FILENAME
    print(f"workroom server: {url}")
    print(f"  state file: {state_path}")
    if idle_hours and idle_hours > 0:
        print(f"  stops by itself after {idle_hours:g} h without requests (Ctrl+C stops it now)")
        threading.Thread(target=idle_watchdog, args=(httpd, Handler, build_status, idle_hours * 3600),
                         daemon=True).start()
    if open_browser:
        _open_in_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        clear_server_file(d, port)
        print("workroom server stopped")


# ============================================================================
# CLI
# ============================================================================

def main():
    raw = sys.argv[1:]
    # --title and --port each take a value that is not itself a flag - drop them before
    # handing argv to the generic --help / positional-count check, or the value would be
    # miscounted as a second positional (see scripts/_cli.py).
    argv_for_cli = list(raw)
    for flag in ("--title", "--port", "--idle-hours"):
        while flag in argv_for_cli:
            i = argv_for_cli.index(flag)
            del argv_for_cli[i:i + 2]
    _cli.usage(__doc__, argv_for_cli, 1, 1)

    args = [a for a in raw if not a.startswith("--")]
    d = Path(args[0]).resolve()
    if not d.is_dir():
        print(f"not a directory: {d}")
        sys.exit(1)
    deck = d.name
    if "--title" in raw:
        i = raw.index("--title")
        if i + 1 < len(raw):
            deck = raw[i + 1]

    if "--serve" in raw:
        port = DEFAULT_PORT
        if "--port" in raw:
            i = raw.index("--port")
            if i + 1 < len(raw):
                try:
                    port = int(raw[i + 1])
                except ValueError:
                    print(f"--port needs a number, got: {raw[i + 1]!r}")
                    sys.exit(1)
        idle_hours = DEFAULT_IDLE_HOURS
        if "--idle-hours" in raw:
            i = raw.index("--idle-hours")
            try:
                idle_hours = float(raw[i + 1])
            except (IndexError, ValueError):
                print("--idle-hours needs a number of hours (0 = never stop)")
                sys.exit(1)
        serve(d, deck, port, open_browser="--open" in raw, idle_hours=idle_hours)
        return

    write_static(d, deck, open_browser="--open" in raw)


if __name__ == "__main__":
    main()
