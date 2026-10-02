"""Print the approximate token cost of the skill's documents (bytes / 4).

    python scripts/tokens.py

Shows each Markdown file, the always-read path (SKILL.md + 00_intake.md + STYLE.md + PIPELINE.md +
reference/MANIFEST.md) and the read-when-needed set, so a doc change that quietly inflates every deck
request is visible. Target for the always-read path: 8,000 tokens or fewer.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cli import usage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ALWAYS = ["SKILL.md", "00_intake.md", "STYLE.md", "PIPELINE.md", "reference/MANIFEST.md"]
TARGET = 8000


def tokens(p: Path) -> int:
    return round(len(p.read_bytes()) / 4)


def main(argv):
    usage(__doc__, argv, 0, 0)
    docs = sorted(list(ROOT.glob("*.md")) + [ROOT / "reference" / "MANIFEST.md"])
    total_always = 0
    print("%7s  %s" % ("~tokens", "document"))
    for p in docs:
        rel = p.relative_to(ROOT).as_posix()
        t = tokens(p)
        tag = "  always" if rel in ALWAYS else ""
        if rel in ALWAYS:
            total_always += t
        print("%7d  %s%s" % (t, rel, tag))
    print("-" * 40)
    verdict = "OK" if total_always <= TARGET else "OVER TARGET (%d)" % TARGET
    print("%7d  always-read path  -> %s" % (total_always, verdict))
    return 0 if total_always <= TARGET else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
