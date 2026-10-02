"""Confirm a packed .pptx carries only the house font.

Usage: python fontcheck.py <deck.pptx>

Lists every typeface referenced anywhere in the packed file. Prints CLEAN and exits 0 if the
only typefaces present are the house font (font.name in house.json), theme references that
start with "+" (+mj-lt, +mn-lt, +mj-ea, +mn-cs), or the symbol/dingbat fonts (Wingdings,
Wingdings 2, Wingdings 3, Symbol, Webdings, MT Extra, Segoe UI Symbol, Segoe UI Emoji).
Otherwise lists each offending typeface with the OOXML part(s) it was found in and exits 1.

Run this after patch_fonts.py + office_io.pack to verify the font patch actually took.
"""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli  # noqa: E402 - shared --help / arg-count handling
import config as C  # noqa: E402

SYMBOL_FONTS = {"Wingdings", "Wingdings 2", "Wingdings 3", "Symbol", "Webdings",
                "MT Extra", "Segoe UI Symbol", "Segoe UI Emoji"}
TYPEFACE_RE = re.compile(r'typeface="([^"]*)"')


def _is_exempt(name, target):
    return name == "" or name.startswith("+") or name in SYMBOL_FONTS or name == target


def scan(pptx_path):
    """Returns (target font name, {every typeface seen}, [(offending typeface, part name), ...])."""
    target = C.FONT_NAME
    seen = set()
    offenders = []
    with zipfile.ZipFile(pptx_path) as z:
        for name in z.namelist():
            if not name.endswith(".xml"):
                continue
            text = z.read(name).decode("utf-8", errors="ignore")
            for m in TYPEFACE_RE.finditer(text):
                face = m.group(1)
                seen.add(face)
                if not _is_exempt(face, target):
                    offenders.append((face, name))
    return target, seen, offenders


def main():
    _cli.usage(__doc__, sys.argv[1:], 1, 1)
    pptx_path = Path(sys.argv[1])
    target, seen, offenders = scan(pptx_path)
    print(f"typefaces found in {pptx_path.name}: {', '.join(sorted(seen)) or '(none)'}")
    if not offenders:
        print(f"CLEAN - only '{target}' (+ theme/symbol exceptions) present.")
        sys.exit(0)
    by_face = {}
    for face, part in offenders:
        by_face.setdefault(face, []).append(part)
    for face, parts in sorted(by_face.items(), key=lambda kv: -len(kv[1])):
        uniq_parts = sorted(set(parts))
        print(f"  OFFENDER '{face}' x{len(parts)} in: {', '.join(uniq_parts)}")
    sys.exit(1)


if __name__ == "__main__":
    main()
