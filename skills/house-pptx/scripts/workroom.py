"""Build the browser workroom for a deck - one HTML page that is the focal point for all
review of that deck's slides.

Usage:
  python workroom.py <dir>                 # regenerate <dir>/workroom.html
  python workroom.py <dir> --open          # ...and open it in the default browser
  python workroom.py <dir> --title "Name"  # set the deck name shown in the header

Every slide HTML in <dir> is wrapped (font + canvas boilerplate) and embedded in its own iframe, so
slides cannot leak CSS into each other and each one still opens standalone. Zoom controls switch
between full size, half size and a contact-sheet grid, which replaces the old PNG contact sheet for
human review.

Status per slide lives in <dir>/workroom.json - {"file.html": {"status": "...", "note": "..."}} with
status one of: mockup | review | approved | built. New files default to "mockup". Statuses survive
regeneration, so this file is also the record of which mockups are already in the .pptx.

NOTE for agents: you cannot see a browser. Keep rendering PNGs (render_html.ps1 / render_slides.ps1)
for your own QA - this page is for the human. Delete those PNGs when done; this page is what persists.
"""
import html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as _cfg                       # house settings + machine paths; see scripts/config.py
FONT_CSS = _cfg.font_face_css()             # a CSS comment for a system font
FONT_STACK = _cfg.font_stack_css()
STATUSES = ["mockup", "review", "approved", "built"]

WRAP = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
{fontcss}
*{{box-sizing:border-box;}}
html,body{{margin:0;padding:0;width:1280px;height:720px;overflow:hidden;background:#fff;font-family:{stack};}}
.variant-label{{display:none;}}
.slide{{width:1280px;height:720px;position:relative;overflow:hidden;margin:0;}}
table{{border-collapse:collapse;}}
</style></head><body>
{body}
</body></html>"""


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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    d = Path(args[0]).resolve()
    if not d.is_dir():
        print(f"not a directory: {d}")
        sys.exit(1)
    deck = d.name
    if "--title" in sys.argv:
        i = sys.argv.index("--title")
        if i + 1 < len(sys.argv):
            deck = sys.argv[i + 1]

    slides = sorted([p for p in d.glob("*.html") if is_slide(p)])
    if not slides:
        print(f"no slide HTML found in {d} (looking for files containing class=\"slide\")")
        sys.exit(1)

    state_p = d / "workroom.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}

    work = d / "_workroom"
    work.mkdir(exist_ok=True)
    for old in work.glob("*.html"):
        old.unlink()

    rail, panes = [], []
    for i, p in enumerate(slides, 1):
        text = p.read_text(encoding="utf-8", errors="ignore")
        (work / p.name).write_text(
            WRAP.format(fontcss=FONT_CSS, stack=FONT_STACK, body=fragment_of(text)), encoding="utf-8")
        meta = state.setdefault(p.name, {"status": "mockup", "note": ""})
        st = meta.get("status", "mockup")
        if st not in STATUSES:
            st = "mockup"
        vid = re.split(r"[_.]", p.stem)[0][:14]        # V44, slide1, etc - keeps the rail scannable
        ttl = html.escape(title_of(text, p.stem))
        note = html.escape(meta.get("note", ""))
        edited = meta.get("edited", "")
        edit_badge = f'<span class="editedtag" title="Edited {html.escape(edited)}">edited</span>' if edited else ""
        rail.append(
            f'<a class="railitem{" edited" if edited else ""}" href="#s{i}"><span class="dot {st}"></span>'
            f'<span class="rn">{html.escape(vid)}</span><span class="rt">{ttl}</span>{edit_badge}</a>')
        panes.append(f"""<section class="pane" id="s{i}">
  <div class="cap">
    <span class="idx">{i}</span>
    <span class="vid">{html.escape(vid)}</span>
    <span class="ttl">{ttl}</span>
    <span class="chip {st}">{st}</span>
    <span class="fn">{html.escape(p.name)}</span>
    {f'<span class="note">{note}</span>' if note else ''}
  </div>
  <div class="frame"><iframe src="_workroom/{html.escape(p.name)}" scrolling="no" loading="lazy"></iframe></div>
</section>""")

    state_p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{html.escape(deck)} - workroom</title><style>
{FONT_CSS}
*{{box-sizing:border-box;}}
body{{margin:0;font-family:{FONT_STACK};background:#EEEEEE;color:#1E1E1E;}}
header{{position:sticky;top:0;z-index:20;background:#FFFFFF;border-bottom:1px solid #BEBFBE;
  padding:12px 20px;display:flex;align-items:baseline;gap:16px;}}
header h1{{font-size:17px;margin:0;font-weight:700;}}
header .meta{{font-size:12px;color:#7E7F7E;}}
header .zooms{{margin-left:auto;display:flex;gap:6px;}}
header button{{font-family:inherit;font-size:12px;padding:5px 12px;border:1px solid #BEBFBE;
  background:#fff;cursor:pointer;color:#1E1E1E;}}
header button.on{{background:#373737;color:#fff;border-color:#373737;}}
.wrap{{display:flex;align-items:flex-start;}}
nav{{position:sticky;top:53px;width:260px;flex:0 0 260px;max-height:calc(100vh - 53px);overflow:auto;
  background:#fff;border-right:1px solid #BEBFBE;padding:10px 0;}}
.railitem{{display:flex;align-items:center;gap:8px;padding:7px 14px;text-decoration:none;color:#1E1E1E;font-size:12px;}}
.railitem:hover{{background:#EEEEEE;}}
.railitem.edited{{background:rgba(204,187,157,0.22);}}
.rn{{color:#585958;width:52px;flex:0 0 52px;font-weight:700;font-size:11px;}}
.rt{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.editedtag{{flex:0 0 auto;font-size:9px;font-weight:700;color:#373737;background:#CCBB9D;padding:1px 6px;margin-left:auto;}}
body.z33 .editedtag{{display:none;}}
.dot{{width:8px;height:8px;flex:0 0 8px;border-radius:50%;}}
main{{flex:1;padding:22px;display:flex;flex-direction:column;gap:26px;align-items:flex-start;}}
main.grid{{flex-direction:row;flex-wrap:wrap;gap:18px;}}
.pane{{background:#fff;border:1px solid #BEBFBE;}}
.cap{{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid #E4E4E4;font-size:12px;}}
.idx{{font-weight:700;color:#9F9A94;}}
.vid{{font-weight:700;background:#EEEEEE;padding:2px 7px;font-size:11px;}}
.ttl{{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:52%;}}
.fn{{color:#9F9A94;font-size:11px;margin-left:auto;}}
.note{{color:#585958;font-style:italic;font-size:11px;}}
.chip{{font-size:10px;padding:2px 8px;border:1px solid #BEBFBE;}}
.frame{{width:1280px;height:720px;overflow:hidden;}}
iframe{{width:1280px;height:720px;border:0;display:block;}}
.mockup{{background:#BEBFBE;}} .review{{background:#CCBB9D;}}
.approved{{background:#373737;}} .built{{background:#1D405C;}}
.chip.mockup{{background:#EEEEEE;}} .chip.review{{background:#CCBB9D;}}
.chip.approved{{background:#373737;color:#fff;border-color:#373737;}}
.chip.built{{background:#1D405C;color:#fff;border-color:#1D405C;}}
body.z75 .frame{{width:960px;height:540px;}}  body.z75 iframe{{transform:scale(.75);transform-origin:0 0;}}
body.z50 .frame{{width:640px;height:360px;}}  body.z50 iframe{{transform:scale(.5);transform-origin:0 0;}}
body.z33 .frame{{width:426px;height:240px;}}  body.z33 iframe{{transform:scale(.3328);transform-origin:0 0;}}
body.z33 .ttl{{max-width:200px;}} body.z33 .fn,body.z33 .note{{display:none;}}
</style></head><body>
<header>
  <h1>{html.escape(deck)}</h1>
  <span class="meta">{len(slides)} slides &middot; regenerated {datetime.now().strftime('%d %b %Y %H:%M')}</span>
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
    counts = {}
    for v in state.values():
        counts[v.get("status", "mockup")] = counts.get(v.get("status", "mockup"), 0) + 1
    print(f"workroom.html written: {len(slides)} slides  "
          + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"  {out}")
    if "--open" in sys.argv:
        subprocess.run(["powershell", "-NoProfile", "-Command", f'Start-Process "{out}"'], check=False)


if __name__ == "__main__":
    main()
