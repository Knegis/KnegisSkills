"""Force every typeface in an unpacked .pptx directory to the house font.

Replaces typeface="<other>" with typeface="<house font>" across every .xml file under the
given directory, for the common fallback fonts that templates and pasted content carry
(Arial, Calibri, Calibri Light, Helvetica, Times New Roman, Arial Black). Idempotent.

Why: most templates ship with a fallback font hardcoded in the theme, the slide master and
every layout, and content pasted from elsewhere brings its own. Silent fallbacks are how a
deck ends up mixing fonts, so run this right after unpacking and again right before packing.

The house font comes from house.json (font.name). If the house font IS one of the fallbacks
(e.g. Arial), that name is simply left alone.

Usage:
    python patch_fonts.py <unpacked-dir>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

FALLBACKS = ["Arial", "Calibri", "Calibri Light", "Helvetica", "Times New Roman", "Arial Black"]
TARGET = C.FONT_NAME
BANNED = [f for f in FALLBACKS if f.lower() != TARGET.lower()]


def patch(root: str) -> None:
    total = 0
    files_touched = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".xml"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            original = text
            for banned in BANNED:
                text = text.replace(f'typeface="{banned}"', f'typeface="{TARGET}"')
            if text != original:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                hits = sum(original.count(f'typeface="{b}"') for b in BANNED)
                total += hits
                files_touched += 1
                print(f"  patched {path} ({hits} refs)")
    print(f"Done. {total} font references rewritten to '{TARGET}' across {files_touched} files.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python patch_fonts.py <unpacked-dir>", file=sys.stderr)
        sys.exit(1)
    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    patch(root)
