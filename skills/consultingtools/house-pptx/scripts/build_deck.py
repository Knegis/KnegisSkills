"""Build a multi-slide deck from several constrained-HTML slides via the pipeline.

Usage: python build_deck.py "<out.pptx>" slide1.html slide2.html ... [--approved]
Each HTML is extracted (extract_geometry.py) -> shapes + native-chart regions; all slides
are assembled into ONE pptx on the configured template, packed via office_io (validated by
python-pptx), then native charts are inserted per slide. Reuses html_to_pptx for shape XML
+ chart insertion.
"""
import sys, json, re, shutil, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import html_to_pptx as H
import office_io
import patch_fonts as _pf

HERE = Path(__file__).resolve().parent
TPL, RT = H.TPL, H.RT

def register(unp, n):
    ct = unp/"[Content_Types].xml"; s = ct.read_text(encoding="utf-8")
    part = "/ppt/slides/slide%d.xml" % n
    if part not in s:
        s = s.replace("</Types>", '<Override PartName="%s" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>' % part)
        ct.write_text(s, encoding="utf-8")
    pr = unp/"ppt"/"_rels"/"presentation.xml.rels"; s = pr.read_text(encoding="utf-8")
    rids = [int(m) for m in re.findall(r'Id="rId(\d+)"', s)]; rid = "rId%d" % (max(rids)+1 if rids else 1)
    s = s.replace("</Relationships>", '<Relationship Id="%s" Type="%s/slide" Target="slides/slide%d.xml"/></Relationships>' % (rid, RT, n))
    pr.write_text(s, encoding="utf-8")
    return rid

def review_gate(htmls):
    """Warn loudly if these slides were never shown to the human.

    Building a .pptx the user has not seen is the failure mode this skill most wants to
    prevent (html_pipeline.md -> "The build loop"). This does not block - pass --approved,
    or just proceed - but it should never happen silently.
    """
    import json as _json
    unseen, no_page = [], set()
    for h in htmls:
        state_p = h.parent / "workroom.json"
        if not state_p.exists():
            no_page.add(str(h.parent)); unseen.append(h.name); continue
        try:
            st = _json.loads(state_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unseen.append(h.name); continue
        if st.get(h.name, {}).get("status") != "approved":
            unseen.append(h.name)
    if not unseen:
        return
    print(chr(10) + "!" * 76)
    print("  REVIEW GATE: %d of %d slides are not marked approved." % (len(unseen), len(htmls)))
    for n in unseen[:8]:
        print("    - " + n)
    if no_page:
        print("  No workroom.json in: " + ", ".join(sorted(no_page)))
        print("  Run:  python scripts/workroom.py <dir> --open   and show the user the mockups.")
    print("  Building a deck the user has not seen is a failed run. If they approved it,")
    print("  mark the slides approved in workroom.json or re-run with --approved.")
    print("!" * 76 + chr(10))


def main():
    args = [a for a in sys.argv[1:] if a != "--approved"]
    out = Path(args[0]); htmls = [Path(a) for a in args[1:]]
    if not htmls:
        print("need at least one slide HTML"); sys.exit(1)
    if "--approved" not in sys.argv:
        review_gate(htmls)
    work = out.parent/"_deck_work"
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    unp = work/"unpacked"
    office_io.unpack(TPL, unp)
    _pf.patch(str(unp))
    (unp/"ppt"/"slides"/"_rels").mkdir(parents=True, exist_ok=True)

    charts_per_slide = []   # index-aligned to slide order
    rid_list = []
    for i, htmlp in enumerate(htmls, start=1):
        geom = work/("geom%d.json" % i)
        subprocess.run([sys.executable, str(HERE/"extract_geometry.py"), str(htmlp), str(geom)], check=True, capture_output=True)
        data = json.loads(geom.read_text(encoding="utf-8"))
        idg = H.IdGen()
        (unp/"ppt"/"slides"/("slide%d.xml" % i)).write_text(H.build_slide_xml(data, idg), encoding="utf-8")
        (unp/"ppt"/"slides"/"_rels"/("slide%d.xml.rels" % i)).write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="%s/slideLayout" Target="../slideLayouts/%s"/></Relationships>'
            % (RT, H.layout_target(data, unp)),
            encoding="utf-8")
        rid_list.append(register(unp, i))
        charts_per_slide.append(data.get("charts") or [])
        print("  slide %d: %s | %d charts" % (i, htmlp.name, len(charts_per_slide[-1])))

    # sldIdLst with all slides in order
    pp = unp/"ppt"/"presentation.xml"; s = pp.read_text(encoding="utf-8")
    entries = "".join('<p:sldId id="%d" r:id="%s"/>' % (256+i, rid) for i, rid in enumerate(rid_list))
    lst = "<p:sldIdLst>%s</p:sldIdLst>" % entries
    if "</p:handoutMasterIdLst>" in s:
        s = s.replace("</p:handoutMasterIdLst>", "</p:handoutMasterIdLst>"+lst)
    elif "</p:notesMasterIdLst>" in s:
        s = s.replace("</p:notesMasterIdLst>", "</p:notesMasterIdLst>"+lst)
    else:
        s = s.replace("</p:sldMasterIdLst>", "</p:sldMasterIdLst>"+lst)
    pp.write_text(s, encoding="utf-8")

    try:
        office_io.pack(unp, out)
    except ValueError as e:
        print("PACK FAILED:", e); sys.exit(1)

    if any(charts_per_slide):
        from pptx import Presentation as PPTXPres
        prs = PPTXPres(str(out))
        for idx, charts in enumerate(charts_per_slide):
            if charts:
                H.add_charts_to_slide(prs.slides[idx], charts)
        prs.save(str(out))
    print("DECK: %d slides -> %s" % (len(htmls), out.name))

if __name__ == "__main__":
    main()
