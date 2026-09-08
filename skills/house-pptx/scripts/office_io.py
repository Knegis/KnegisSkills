"""Unpack and pack .pptx files with the standard library only - no external skill required.

Usage:
    python office_io.py unpack <deck.pptx> <out_dir>
    python office_io.py pack   <unpacked_dir> <out.pptx>

unpack: extracts the OOXML package to a directory (an existing directory is cleared first).
pack:   writes the package back. [Content_Types].xml goes first (readers expect it), then
        _rels/.rels, then everything else. XML is deflated; media is stored as-is. The result
        is opened once with python-pptx as a smoke check - a package PowerPoint cannot read
        usually fails that too, and a ValueError here is far cheaper than a "corrupted and
        unreadable" dialog later.

Both are importable: office_io.unpack(pptx, out_dir) / office_io.pack(src_dir, out_pptx).
"""
import shutil
import sys
import zipfile
from pathlib import Path

MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".emf", ".wmf", ".tiff", ".bmp", ".bin", ".mp4", ".wav", ".otf", ".ttf"}


def unpack(pptx, out_dir):
    pptx, out_dir = Path(pptx), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    with zipfile.ZipFile(pptx) as z:
        z.extractall(out_dir)
    return out_dir


def pack(src_dir, out_pptx, validate=True):
    src_dir, out_pptx = Path(src_dir), Path(out_pptx)
    files = [p for p in src_dir.rglob("*") if p.is_file()]
    rel = {p: p.relative_to(src_dir).as_posix() for p in files}

    def order(p):
        r = rel[p]
        if r == "[Content_Types].xml":
            return (0, r)
        if r == "_rels/.rels":
            return (1, r)
        return (2, r)

    tmp = out_pptx.with_suffix(out_pptx.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as z:
        for p in sorted(files, key=order):
            comp = zipfile.ZIP_STORED if p.suffix.lower() in MEDIA_EXT else zipfile.ZIP_DEFLATED
            z.write(p, rel[p], compress_type=comp)
    if validate:
        try:
            from pptx import Presentation
            prs = Presentation(str(tmp))
            _ = len(prs.slides)
        except Exception as e:                     # noqa: BLE001 - report whatever python-pptx raised
            tmp.unlink(missing_ok=True)
            raise ValueError(f"packed file did not open in python-pptx: {e}") from e
    if out_pptx.exists():
        out_pptx.unlink()
    tmp.rename(out_pptx)
    return out_pptx


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("unpack", "pack"):
        print(__doc__)
        sys.exit(2)
    cmd, a, b = sys.argv[1:]
    if cmd == "unpack":
        d = unpack(a, b)
        print(f"unpacked {a} -> {d} ({sum(1 for _ in d.rglob('*') if _.is_file())} parts)")
    else:
        out = pack(a, b)
        print(f"packed {a} -> {out} ({out.stat().st_size // 1024} KB, opens in python-pptx)")


if __name__ == "__main__":
    main()
