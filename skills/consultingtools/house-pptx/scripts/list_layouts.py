"""List the layouts in a .pptx template, with the filename the pipeline addresses them by.

Usage: python list_layouts.py [template.pptx]      (default: the configured template)

Use the printed name (or slideLayoutN.xml) in <body data-ppt-layout="..."> to place a slide
on a specific layout. Names are matched case-insensitively as substrings, so "blank" finds
"Blank" and "No Content - White" alike.
"""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402


def layouts_of(pptx):
    """[(filename, name, n_placeholders, has_picture)] in slideLayoutN order."""
    out = []
    with zipfile.ZipFile(pptx) as z:
        names = [n for n in z.namelist() if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        for n in names:
            x = z.read(n).decode("utf-8", errors="ignore")
            m = re.search(r'<p:cSld[^>]*\bname="([^"]*)"', x)
            out.append((n.rsplit("/", 1)[1], m.group(1) if m else "?",
                        len(re.findall(r"<p:ph\b", x)), "<p:pic>" in x))
    return out


def main():
    tpl = Path(sys.argv[1]) if len(sys.argv) > 1 else C.require("the template", C.TEMPLATE)
    rows = layouts_of(tpl)
    print(f"{tpl}\n{len(rows)} layouts\n")
    print(f"{'file':<22} {'placeholders':>12}  {'picture':<8} name")
    for f, name, nph, pic in rows:
        print(f"{f:<22} {nph:>12}  {'yes' if pic else '':<8} {name}")


if __name__ == "__main__":
    main()
