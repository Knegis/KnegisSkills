"""Force every typeface in an unpacked .pptx directory to the house font.

Rewrites typeface="<other>" -> typeface="<house font>" across every .xml file under the
given directory, for every typeface found EXCEPT: theme references, which start with "+"
(+mj-lt, +mn-lt, +mj-ea, +mn-cs - these resolve through the theme, not a literal name), and
the symbol/dingbat fonts (Wingdings, Wingdings 2, Wingdings 3, Symbol, Webdings, MT Extra,
Segoe UI Symbol, Segoe UI Emoji), which are never meant to carry the house font. Idempotent.

Why: most templates ship with a fallback font hardcoded in the theme, the slide master and
every layout, and content pasted from elsewhere brings its own. Silent fallbacks are how a
deck ends up mixing fonts, so run this right after unpacking and again right before packing.
Run scripts/fontcheck.py against the packed .pptx afterwards to confirm the result is CLEAN.

The house font comes from house.json (font.name). If the house font IS the only typeface
present, nothing is rewritten.

Usage:
    python patch_fonts.py <unpacked-dir>
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli  # noqa: E402 - shared --help / arg-count handling
import config as C  # noqa: E402

TARGET = C.FONT_NAME
SYMBOL_FONTS = {"Wingdings", "Wingdings 2", "Wingdings 3", "Symbol", "Webdings",
                "MT Extra", "Segoe UI Symbol", "Segoe UI Emoji"}
TYPEFACE_RE = re.compile(r'typeface="([^"]*)"')


def _is_exempt(name: str) -> bool:
    return name == "" or name.startswith("+") or name in SYMBOL_FONTS or name == TARGET


def patch(root: str) -> None:
    counts: dict[str, int] = {}
    files_touched = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".xml"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()

            hits_here: dict[str, int] = {}

            def _sub(m):
                name = m.group(1)
                if _is_exempt(name):
                    return m.group(0)
                hits_here[name] = hits_here.get(name, 0) + 1
                return 'typeface="%s"' % TARGET

            new_text = TYPEFACE_RE.sub(_sub, text)
            if new_text != text:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_text)
                files_touched += 1
                total_here = sum(hits_here.values())
                print(f"  patched {path} ({total_here} refs)")
                for name, n in hits_here.items():
                    counts[name] = counts.get(name, 0) + n
    total = sum(counts.values())
    if counts:
        print("  by typeface:")
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {name}: {n}")
    print(f"Done. {total} font references rewritten to '{TARGET}' across {files_touched} files.")


if __name__ == "__main__":
    _cli.usage(__doc__, sys.argv[1:], 1, 1)
    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    patch(root)
