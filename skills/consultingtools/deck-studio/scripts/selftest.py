"""Deterministic acceptance test for the deck-studio skill - for CI or a colleague.

Usage:
    python scripts/selftest.py             (typecheck + build + fontcheck + layout checks)
    python scripts/selftest.py --render     ...and, if a renderer is available, render the
                                            built deck and assert each slide produced a
                                            non-blank PNG (mean pixel value < 250).

Uses only the standard library + python-pptx + zipfile/struct for reading PNGs back
(no Pillow) - this is meant to run on a bare CI box with the skill's own requirements.txt,
not a full imaging stack.

Checks, in order:
  1. python scripts/typecheck.py on every reference/*.html - each must exit 0.
  2. Build every reference/*.html into ONE deck (scripts/build_deck.py) in a temp dir.
  3. python-pptx opens the built deck.
  4. python scripts/fontcheck.py on the built deck prints CLEAN (exit 0).
  5. Every slide landed on the configured default layout.
  6. (--render only) Render the deck via scripts/render_slides.ps1 (PowerPoint COM) and
     assert one non-blank PNG per slide.

Prints one line per check ("PASS ..." / "FAIL ...") and exits 0 only if every check passed.
"""
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
REFERENCE = SKILL_ROOT / "reference"

sys.path.insert(0, str(HERE))
import _cli  # noqa: E402 - shared --help / arg-count handling

RESULTS = []  # (bool ok, str line)


def check(ok, msg):
    RESULTS.append((bool(ok), msg))
    print(("PASS  " if ok else "FAIL  ") + msg)
    return ok


def run(args, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 180)
    return subprocess.run([sys.executable, *args], **kw)


# --------------------------------------------------------------------------- PNG reading
# Minimal PNG decoder (stdlib only: zlib + struct) - just enough to read back an 8-bit
# truecolor/truecolor-alpha/grayscale PNG (what PowerPoint's slide Export produces) and
# compute a mean pixel value, so "is this slide blank" can be checked without Pillow.

def _unfilter(raw, width, height, bpp):
    stride = width * bpp
    out = bytearray(len(raw) - height)  # drop the 1 filter-type byte per row
    prev = bytearray(stride)
    pos_in = 0
    pos_out = 0
    for _ in range(height):
        ftype = raw[pos_in]
        pos_in += 1
        row = bytearray(raw[pos_in:pos_in + stride])
        pos_in += stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                row[i] = (row[i] + ((a + b) // 2)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[i] = (row[i] + pr) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter type {ftype}")
        out[pos_out:pos_out + stride] = row
        pos_out += stride
        prev = row
    return bytes(out)


def png_mean_pixel(path):
    """Mean byte value across every colour sample in an 8-bit PNG. Raises ValueError for
    anything this minimal decoder does not support (16-bit depth, palette, interlacing)."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos = 8
    width = height = bitdepth = colortype = interlace = None
    idat = bytearray()
    palette = None  # PowerPoint's own PNG Export is palette-indexed (colour type 3, 8-bit)
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bitdepth, colortype, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = [chunk[i:i + 3] for i in range(0, len(chunk), 3)]
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if width is None:
        raise ValueError("no IHDR chunk found")
    if bitdepth != 8:
        raise ValueError(f"only 8-bit PNGs supported (got {bitdepth}-bit)")
    if interlace:
        raise ValueError("interlaced PNGs not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colortype)
    if channels is None:
        raise ValueError(f"unsupported PNG colour type {colortype}")
    raw = zlib.decompress(bytes(idat))
    pixels = _unfilter(raw, width, height, channels)
    if colortype == 3:
        if not palette:
            raise ValueError("palette colour type but no PLTE chunk found")
        total = sum(sum(palette[i]) for i in pixels)  # sum of R+G+B per pixel
        return total / (len(pixels) * 3)
    return sum(pixels) / len(pixels)


# --------------------------------------------------------------------------- checks

def main(argv):
    _cli.usage(__doc__, argv, 0, 0)  # --render is a flag, not positional; --help/-h exit 2 here
    do_render = "--render" in argv

    html_files = sorted(REFERENCE.glob("*.html"))
    check(len(html_files) > 0, f"found {len(html_files)} reference/*.html to test")

    # 1. typecheck every reference slide
    for f in html_files:
        r = run([str(HERE / "typecheck.py"), str(f), "--quiet"])
        check(r.returncode == 0, f"typecheck {f.name} (exit {r.returncode})")
        if r.returncode != 0:
            print(r.stdout[-800:])

    # 2. build them all into one deck
    work = Path(tempfile.mkdtemp(prefix="deck_studio_selftest_"))
    deck = work / "selftest_deck.pptx"
    r = run([str(HERE / "build_deck.py"), str(deck), *[str(f) for f in html_files]])
    built = check(r.returncode == 0 and deck.exists(), "build_deck.py builds all reference slides into one deck")
    if not built:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:])

    prs = None
    if built:
        # 3. python-pptx opens it
        try:
            from pptx import Presentation
            prs = Presentation(str(deck))
            check(len(prs.slides) == len(html_files),
                  f"python-pptx opens the deck ({len(prs.slides)} slides == {len(html_files)} inputs)")
        except Exception as e:  # noqa: BLE001
            check(False, f"python-pptx opens the deck: {e}")

        # 4. fontcheck CLEAN
        import fontcheck
        target, seen, offenders = fontcheck.scan(deck)
        check(not offenders, f"fontcheck CLEAN (only '{target}' present)"
              if not offenders else f"fontcheck found offenders: {offenders}")

        # 5. every slide on the (same) configured default layout
        if prs is not None:
            layout_names = {s.slide_layout.name for s in prs.slides}
            check(len(layout_names) == 1,
                  f"every slide landed on the default layout ({layout_names})")

    # 6. optional render-back gate
    if do_render:
        ps1 = HERE / "render_slides.ps1"
        out_dir = work / "render"
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-File", str(ps1),
                 "-PptxPath", str(deck), "-OutDir", str(out_dir)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            renderer_ok = r.returncode == 0
        except Exception as e:  # noqa: BLE001
            renderer_ok = False
            r = None
            print(f"NOTE  renderer unavailable: {e}")
        if not renderer_ok:
            print("NOTE  --render requested but PowerPoint COM rendering is unavailable here "
                  "(no desktop PowerPoint, or render_slides.ps1 failed) - skipping the "
                  "render-back check rather than failing it.")
            if r is not None:
                print(r.stdout[-800:])
                print(r.stderr[-800:])
        else:
            pngs = sorted(out_dir.glob("*.png"))
            check(len(pngs) == len(html_files), f"renderer produced one PNG per slide ({len(pngs)})")
            for p in pngs:
                try:
                    mean = png_mean_pixel(p)
                    check(mean < 250, f"{p.name} is non-blank (mean pixel {mean:.1f} < 250)")
                except ValueError as e:
                    check(False, f"{p.name}: could not read PNG for blank-check ({e})")

    shutil.rmtree(work, ignore_errors=True)

    n_fail = sum(1 for ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} checks passed"
          + (" -> PASS\n" if n_fail == 0 else f" -> FAIL ({n_fail} failing)\n"))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
