"""Clone a slide from another .pptx into an unpacked working deck.

Instead of building slides from blank layouts, clone a proven slide from a prior deck
and swap its content - cloned slides inherit the density and craft of human-made decks.

Usage:
    python clone_slide.py <source.pptx> <slide_number> <target_unpacked_dir>

What it handles:
  - slide XML + per-slide rels (rIds kept, targets rewritten)
  - images/media: copied into target ppt/media with collision-safe names
  - slide layout: matched by layout NAME in the target; if absent, the source
    layout (+ its media) is copied in and registered on the target's first
    slide master, preserving visual fidelity across template generations
  - external hyperlinks: kept
  - notes slides: dropped
  - charts/embedded objects: NOT cloned (warned + rel dropped) - rebuild charts
    via the .ppt-chart convention in html_pipeline.md
  - auto-registers the new slide in [Content_Types].xml, presentation.xml.rels
    and <p:sldIdLst> (created in the schema-correct position if missing)

After cloning, run patch_fonts.py on the target dir (older decks may carry Arial).
Exit code 0 on success; prints the created slide filename.
"""

import re
import sys
import zipfile
from pathlib import Path

NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_SLIDE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
CT_LAYOUT = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
MEDIA_DEFAULTS = {
    "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
    "gif": "image/gif", "svg": "image/svg+xml", "emf": "image/x-emf",
    "wmf": "image/x-wmf", "tiff": "image/tiff", "bmp": "image/bmp",
}
SKIP_REL_TYPES = ("notesSlide", "chart", "oleObject", "package", "vmlDrawing")


def rels_of(text):
    """Yield (id, type, target, mode) tuples from a .rels XML string."""
    for m in re.finditer(r"<Relationship\b[^>]*/>", text):
        tag = m.group(0)
        rid = re.search(r'Id="([^"]+)"', tag)
        rtype = re.search(r'Type="([^"]+)"', tag)
        target = re.search(r'Target="([^"]+)"', tag)
        mode = re.search(r'TargetMode="([^"]+)"', tag)
        yield (rid.group(1), rtype.group(1), target.group(1),
               mode.group(1) if mode else None, tag)


def build_rels(entries):
    body = "\n".join(f"  {tag}" for tag in entries)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{NS_REL}">\n{body}\n</Relationships>')


def layout_name(xml_text):
    m = re.search(r'<p:cSld[^>]*\bname="([^"]*)"', xml_text)
    return m.group(1) if m else None


def ensure_media_default(unpacked, ext):
    ext = ext.lower().lstrip(".")
    ct_path = unpacked / "[Content_Types].xml"
    ct = ct_path.read_text(encoding="utf-8")
    if f'Extension="{ext}"' in ct:
        return
    mime = MEDIA_DEFAULTS.get(ext, "application/octet-stream")
    ct = ct.replace("</Types>", f'  <Default Extension="{ext}" ContentType="{mime}"/>\n</Types>')
    ct_path.write_text(ct, encoding="utf-8")


def add_override(unpacked, partname, ctype):
    ct_path = unpacked / "[Content_Types].xml"
    ct = ct_path.read_text(encoding="utf-8")
    if partname in ct:
        return
    ct = ct.replace("</Types>", f'  <Override PartName="{partname}" ContentType="{ctype}"/>\n</Types>')
    ct_path.write_text(ct, encoding="utf-8")


def copy_media(z, src_target, unpacked, copied):
    """Copy a media part from the source zip. Returns new relative target."""
    src_part = "ppt/" + src_target.replace("../", "")
    if src_part in copied:
        return copied[src_part]
    data = z.read(src_part)
    media_dir = unpacked / "ppt" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(src_part).stem
    ext = Path(src_part).suffix
    candidate = f"clone_{stem}{ext}"
    i = 1
    while (media_dir / candidate).exists():
        i += 1
        candidate = f"clone_{stem}_{i}{ext}"
    (media_dir / candidate).write_bytes(data)
    ensure_media_default(unpacked, ext)
    new_target = f"../media/{candidate}"
    copied[src_part] = new_target
    return new_target


def next_numbered(dirpath, prefix):
    nums = [int(m.group(1)) for f in dirpath.glob(f"{prefix}*.xml")
            if (m := re.match(rf"{prefix}(\d+)\.xml$", f.name))]
    return max(nums) + 1 if nums else 1


def resolve_layout(z, src_layout_target, unpacked, copied):
    """Map the source slide's layout to a target layout file. Returns ../slideLayouts/<file>."""
    src_part = "ppt/" + src_layout_target.replace("../", "")
    src_xml = z.read(src_part).decode("utf-8", errors="ignore")
    src_name = layout_name(src_xml)

    layouts_dir = unpacked / "ppt" / "slideLayouts"
    if src_name:
        for lf in sorted(layouts_dir.glob("slideLayout*.xml")):
            if layout_name(lf.read_text(encoding="utf-8", errors="ignore")) == src_name:
                return f"../slideLayouts/{lf.name}", f"matched by name '{src_name}'"

    # No match: copy the source layout in and register it on slideMaster1.
    n = next_numbered(layouts_dir, "slideLayout")
    new_file = f"slideLayout{n}.xml"
    (layouts_dir / new_file).write_text(src_xml, encoding="utf-8")
    add_override(unpacked, f"/ppt/slideLayouts/{new_file}", CT_LAYOUT)

    # Layout rels: keep master ref pointing at target master1; copy media.
    src_rels_part = f"ppt/slideLayouts/_rels/{Path(src_part).name}.rels"
    entries = []
    try:
        src_rels = z.read(src_rels_part).decode("utf-8")
        for rid, rtype, target, mode, _tag in rels_of(src_rels):
            if rtype.endswith("/slideMaster"):
                entries.append(f'<Relationship Id="{rid}" Type="{RT}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>')
            elif rtype.endswith("/image") and mode != "External":
                new_t = copy_media(z, target, unpacked, copied)
                entries.append(f'<Relationship Id="{rid}" Type="{rtype}" Target="{new_t}"/>')
            elif mode == "External":
                entries.append(f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}" TargetMode="External"/>')
    except KeyError:
        entries.append(f'<Relationship Id="rId1" Type="{RT}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>')
    rels_dir = layouts_dir / "_rels"
    rels_dir.mkdir(exist_ok=True)
    (rels_dir / f"{new_file}.rels").write_text(build_rels(entries), encoding="utf-8")

    # Register on master: sldLayoutIdLst entry + master rels.
    master = unpacked / "ppt" / "slideMasters" / "slideMaster1.xml"
    master_rels_p = unpacked / "ppt" / "slideMasters" / "_rels" / "slideMaster1.xml.rels"
    mr = master_rels_p.read_text(encoding="utf-8")
    rids = [int(m) for m in re.findall(r'Id="rId(\d+)"', mr)]
    new_rid = f"rId{max(rids) + 1 if rids else 1}"
    mr = mr.replace("</Relationships>",
                    f'  <Relationship Id="{new_rid}" Type="{RT}/slideLayout" Target="../slideLayouts/{new_file}"/>\n</Relationships>')
    master_rels_p.write_text(mr, encoding="utf-8")
    mx = master.read_text(encoding="utf-8")
    lid = max([int(i) for i in re.findall(r'<p:sldLayoutId[^>]*id="(\d+)"', mx)] or [2147483648])
    mx = mx.replace("</p:sldLayoutIdLst>",
                    f'<p:sldLayoutId id="{lid + 1}" r:id="{new_rid}"/></p:sldLayoutIdLst>')
    master.write_text(mx, encoding="utf-8")
    return f"../slideLayouts/{new_file}", f"copied source layout as {new_file} (no name match)"


def strip_dropped_refs(xml, dropped_rids):
    """Remove slide-XML elements that reference relationships we dropped.

    Order matters: mc:AlternateContent often wraps the graphicFrame that hosts
    an oleObj/chart (Choice + Fallback both reference the rId), so strip the
    outermost wrapper first.
    """
    for rid in dropped_rids:
        for tag in ("mc:AlternateContent", "p:graphicFrame", "p:pic"):
            pattern = re.compile(
                rf"<{tag}\b(?:(?!</{tag}>).)*?\"{rid}\".*?</{tag}>", re.S)
            xml = pattern.sub("", xml)
        # self-closing references, e.g. <p:tags r:id="rId1"/>
        xml = re.sub(rf'<[^<>]+r:(?:id|embed)="{rid}"[^<>]*/>', "", xml)
    xml = re.sub(r"<p:custDataLst>\s*</p:custDataLst>", "", xml)
    return xml


def register_slide(unpacked, dest):
    """presentation.xml.rels + sldIdLst (auto-insert, schema-correct position)."""
    pres_rels_p = unpacked / "ppt" / "_rels" / "presentation.xml.rels"
    pr = pres_rels_p.read_text(encoding="utf-8")
    rids = [int(m) for m in re.findall(r'Id="rId(\d+)"', pr)]
    rid = f"rId{max(rids) + 1 if rids else 1}"
    pr = pr.replace("</Relationships>",
                    f'  <Relationship Id="{rid}" Type="{RT}/slide" Target="slides/{dest}"/>\n</Relationships>')
    pres_rels_p.write_text(pr, encoding="utf-8")

    pres_p = unpacked / "ppt" / "presentation.xml"
    px = pres_p.read_text(encoding="utf-8")
    sids = {int(i) for i in re.findall(r'<p:sldId[^>]*id="(\d+)"', px)}
    # PowerPoint requires 256 <= sldId <= 2147483647. Taking max()+1 overflows that ceiling
    # the moment a deck already carries an id at the top of the range (hit repeatedly on real
    # decks, producing a file PowerPoint refuses to open), so take the lowest FREE id.
    sid = next(i for i in range(256, 2147483648) if i not in sids)
    entry = f'<p:sldId id="{sid}" r:id="{rid}"/>'
    if "<p:sldIdLst" in px:
        px = px.replace("</p:sldIdLst>", f"{entry}</p:sldIdLst>")
    elif "</p:handoutMasterIdLst>" in px:
        px = px.replace("</p:handoutMasterIdLst>",
                        f"</p:handoutMasterIdLst><p:sldIdLst>{entry}</p:sldIdLst>")
    elif "</p:notesMasterIdLst>" in px:
        px = px.replace("</p:notesMasterIdLst>",
                        f"</p:notesMasterIdLst><p:sldIdLst>{entry}</p:sldIdLst>")
    else:
        px = px.replace("</p:sldMasterIdLst>",
                        f"</p:sldMasterIdLst><p:sldIdLst>{entry}</p:sldIdLst>")
    pres_p.write_text(px, encoding="utf-8")


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    src_pptx, slide_no, unpacked = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    if not src_pptx.exists() or not unpacked.exists():
        print("Error: source pptx or target dir not found", file=sys.stderr)
        sys.exit(1)

    warnings = []
    with zipfile.ZipFile(src_pptx) as z:
        names = z.namelist()
        slide_part = f"ppt/slides/slide{slide_no}.xml"
        if slide_part not in names:
            print(f"Error: {slide_part} not in {src_pptx.name} "
                  f"({len([n for n in names if re.match(r'ppt/slides/slide[0-9]+[.]xml$', n)])} slides)",
                  file=sys.stderr)
            sys.exit(1)

        slide_xml = z.read(slide_part).decode("utf-8")
        slides_dir = unpacked / "ppt" / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)
        (slides_dir / "_rels").mkdir(exist_ok=True)
        dest = f"slide{next_numbered(slides_dir, 'slide')}.xml"

        copied = {}
        entries = []
        dropped = []
        try:
            src_rels = z.read(f"ppt/slides/_rels/slide{slide_no}.xml.rels").decode("utf-8")
        except KeyError:
            src_rels = build_rels([])
        for rid, rtype, target, mode, tag in rels_of(src_rels):
            short = rtype.rsplit("/", 1)[-1]
            if short in SKIP_REL_TYPES:
                if short != "notesSlide":
                    dropped.append(rid)
                    warnings.append(f"DROPPED {short} rel ({rid}) and stripped its element "
                                    f"from the slide - rebuild the chart via .ppt-chart")
                continue
            if short == "slideLayout":
                new_target, how = resolve_layout(z, target, unpacked, copied)
                entries.append(f'<Relationship Id="{rid}" Type="{rtype}" Target="{new_target}"/>')
                warnings.append(f"layout: {how}")
            elif mode == "External":
                entries.append(f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}" TargetMode="External"/>')
            elif short in ("image", "media"):
                new_target = copy_media(z, target, unpacked, copied)
                entries.append(f'<Relationship Id="{rid}" Type="{rtype}" Target="{new_target}"/>')
            else:
                dropped.append(rid)
                warnings.append(f"DROPPED unsupported rel type {short} ({rid}) and stripped its element")

        if dropped:
            slide_xml = strip_dropped_refs(slide_xml, dropped)
        (slides_dir / dest).write_text(slide_xml, encoding="utf-8")
        (slides_dir / "_rels" / f"{dest}.rels").write_text(build_rels(entries), encoding="utf-8")
        add_override(unpacked, f"/ppt/slides/{dest}", CT_SLIDE)
        register_slide(unpacked, dest)

    print(f"Cloned {src_pptx.name} slide {slide_no} -> {dest} (registered in sldIdLst)")
    for w in warnings:
        print(f"  note: {w}")
    print("  reminder: run patch_fonts.py before packing")


if __name__ == "__main__":
    main()
