"""Build a multi-slide deck from several constrained-HTML slides via the pipeline.

Usage: python build_deck.py "<out.pptx>" slide1.html slide2.html ...
Each HTML is extracted (extract_geometry.py) -> shapes + native-chart regions; all slides
are assembled into ONE pptx on the configured template, packed via office_io (validated by
python-pptx), then native charts are inserted per slide. Reuses html_to_pptx for shape XML
+ chart insertion.
"""
import sys, json, re, shutil, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli
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


def main():
    _cli.usage(__doc__, sys.argv[1:], 2, 10**6)
    args = sys.argv[1:]
    out = Path(args[0]); htmls = [Path(a) for a in args[1:]]

    work = out.parent/"_deck_work"
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    unp = work/"unpacked"
    office_io.unpack(TPL, unp)
    _pf.patch(str(unp))
    (unp/"ppt"/"slides"/"_rels").mkdir(parents=True, exist_ok=True)
    media = H.MediaRegistry(unp)   # shared across every slide - dedupes a photo reused twice

    def fail(msg):
        print(msg)
        print("  (work kept at %s for inspection)" % work)
        sys.exit(1)

    charts_per_slide = []   # index-aligned to slide order
    rid_list = []
    for i, htmlp in enumerate(htmls, start=1):
        geom = work/("geom%d.json" % i)
        r = subprocess.run([sys.executable, str(HERE/"extract_geometry.py"), str(htmlp), str(geom)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            if r.stderr:
                print(r.stderr, file=sys.stderr)
            if r.stdout:
                print(r.stdout)
            fail("BUILD FAILED: geometry extraction failed for %s" % htmlp.name)
        data = json.loads(geom.read_text(encoding="utf-8"))
        if not (data.get("texts") or data.get("rects") or data.get("charts")):
            print("WARN  %s: slide is empty (no shapes translated)" % htmlp.name)
        for w in data.get("warnings") or []:
            print("  WARN  %s: %s - %s" % (w["sel"], w["why"], w["fix"]))
        idg = H.IdGen()
        slide_rels = H.SlideRels()
        (unp/"ppt"/"slides"/("slide%d.xml" % i)).write_text(
            H.build_slide_xml(data, idg, media, slide_rels), encoding="utf-8")
        (unp/"ppt"/"slides"/"_rels"/("slide%d.xml.rels" % i)).write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="%s/slideLayout" Target="../slideLayouts/%s"/>%s</Relationships>'
            % (RT, H.layout_target(data, unp), slide_rels.rels_xml()),
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

    media.ensure_content_types()
    try:
        office_io.pack(unp, out)
    except ValueError as e:
        fail("PACK FAILED: %s" % e)

    if any(charts_per_slide):
        from pptx import Presentation as PPTXPres
        prs = PPTXPres(str(out))
        for idx, charts in enumerate(charts_per_slide):
            if charts:
                H.add_charts_to_slide(prs.slides[idx], charts)
        prs.save(str(out))
    print("DECK: %d slides -> %s" % (len(htmls), out.name))
    shutil.rmtree(work, ignore_errors=True)

if __name__ == "__main__":
    main()
