"""Feedback ledger - every review comment the user makes, and what the agent did about it,
accumulated in one place so recurring feedback can be distilled into rules, exemplars, checks
or evals later (roadmap 2.4).

Usage:
  python ledger.py register <deck-dir>              # remember a deck; workroom.py --serve does this on start
  python ledger.py sync                              # rebuild feedback/ledger.jsonl + feedback/summary.md
  python ledger.py note <id> --category <cat> --fix "<what the agent changed>"
  python ledger.py show [--deck <dir-or-name>] [--uncategorised]

Categories: format | density | type | colour | translator | content | other

Source of truth is every registered deck's workroom_state.json (comments, rounds, builds) -
sync() derives feedback/ledger.jsonl from those, one row per comment:
  {id, deck, slide, round, ts, comment, view, anchor, target, category, fix, fix_ts,
   rounds_to_build, built_version, promoted}
`id` is "<deck>:<slide>:<comment index>" (0-based index into that slide's comments list).
`view` is "html" or "ppt" - which card view the comment was left against (defaults to "html"
for older comments that predate the field). `anchor`/`target` are present only for a pinned
comment (workroom.py Feature 2): `anchor` is {x, y, w, h} in 1280x720 slide-pixel space (w=h=0
for a point pin); `target` is the element the pin landed on, or None if it couldn't be
identified.
sync() is idempotent and additive: re-running it never overwrites an existing row's `category`,
`fix` or `fix_ts` (those are the agent's own notes, set only via `note`), only adds new rows and
refreshes their derived fields (rounds_to_build, built_version, promoted).

`rounds_to_build` is a best-effort figure, not an exact historical replay: workroom_state.json
only stores each slide's CURRENT round count, not a timestamped history of every round, so this
is that slide's current `rounds` value the first time sync() sees it has a successful build - an
honest approximation, not a retroactive reconstruction. If the slide is edited again after that
build, later syncs will not retroactively change an already-recorded row's rounds_to_build, since
existing rows are only refreshed for slides that have not yet reached their first build; once a
slide's first-build figure is captured for a given row it is left alone, same as category/fix.

Called from scripts/workroom.py in-process (no subprocess) on server start (register) and after
every comment POST / successful build (sync), so the ledger is always current for a served deck.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _cli  # noqa: E402 - shared --help / arg-count handling

LAB_ROOT = HERE.parent
VALID_CATEGORIES = {"format", "density", "type", "colour", "translator", "content", "other"}


# ---------------------------------------------------------------------------
# paths - functions, not constants, so tests can monkeypatch LAB_ROOT and have
# every path below follow it
# ---------------------------------------------------------------------------

def feedback_dir():
    return LAB_ROOT / "feedback"


def decks_file():
    return feedback_dir() / "decks.txt"


def ledger_file():
    return feedback_dir() / "ledger.jsonl"


def summary_file():
    return feedback_dir() / "summary.md"


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def register(deck_dir):
    """Append the absolute deck dir to decks.txt, deduplicated. Returns the resolved path."""
    resolved = str(Path(deck_dir).resolve())
    fd = feedback_dir()
    fd.mkdir(parents=True, exist_ok=True)
    f = decks_file()
    existing = _read_lines(f)
    if resolved not in existing:
        existing.append(resolved)
        f.write_text("\n".join(existing) + "\n", encoding="utf-8")
    return resolved


def _read_lines(p):
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def registered_decks():
    return _read_lines(decks_file())


# ---------------------------------------------------------------------------
# ledger read/write
# ---------------------------------------------------------------------------

def _load_ledger():
    """Return (rows_by_id, id_order) from the existing ledger.jsonl, or ({}, []) if none yet."""
    f = ledger_file()
    rows, order = {}, []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows[row["id"]] = row
            order.append(row["id"])
    return rows, order


def _write_ledger(rows):
    fd = feedback_dir()
    fd.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r) + "\n" for r in rows)
    ledger_file().write_text(text, encoding="utf-8")


def _first_successful_build_with(builds, slide):
    for b in builds or []:
        if b.get("ok") and slide in (b.get("slides") or []):
            return b
    return None


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

def sync():
    """Rebuild ledger.jsonl from every registered deck's workroom_state.json and rewrite
    summary.md. Returns the full list of rows (dicts) written. Existing rows keep their
    category/fix/fix_ts; a deck directory or state file that has vanished leaves its old rows
    untouched at the end of the file rather than deleting them.

    A row's id is "<deck>:<slide>:<cid>" when the comment carries a `cid` (workroom.py assigns
    one to every comment, including legacy ones, as soon as it next loads that deck - see
    workroom._ensure_comment_ids), or the older "<deck>:<slide>:<index>" form for a comment
    that somehow still lacks one. Because a cid travels with its comment regardless of the
    comment's position in the list, a category/fix noted against a cid-based row survives a
    *different*, earlier comment on the same slide being deleted - the whole reason cids exist.
    A comment actually removed by the user (workroom.py's comment/<cid>/delete) drops out of the
    ledger on this next sync: its rid simply isn't reproduced for that (still-present) slide, and
    unlike a vanished deck/slide, an existing slide's own comment list is trusted as complete."""
    old_rows, old_order = _load_ledger()
    seen = set()
    fresh_rows = []
    # (deck, slide) pairs whose comment list was actually rebuilt this pass - a prior row for
    # one of these that isn't in `seen` means its comment was deleted, not that the deck/slide
    # itself vanished, so it must NOT be carried forward into `leftover` below.
    processed_slides = set()

    for deck_dir in registered_decks():
        state_path = Path(deck_dir) / "workroom_state.json"
        if not state_path.exists():
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            continue

        deck_name = state.get("deck") or Path(deck_dir).name
        builds = state.get("builds") or []
        slides = state.get("slides") or {}
        for slide in state.get("order", []):
            processed_slides.add((deck_name, slide))
            sinfo = slides.get(slide) or {}
            comments = sinfo.get("comments") or []
            first_build = _first_successful_build_with(builds, slide)
            built_version = sinfo.get("built_version")
            promoted = bool(sinfo.get("promoted"))
            for idx, c in enumerate(comments):
                cid = c.get("cid")
                rid = "%s:%s:%s" % (deck_name, slide, cid) if cid else "%s:%s:%d" % (deck_name, slide, idx)
                row = {
                    "id": rid,
                    "deck": deck_name,
                    "slide": slide,
                    "round": c.get("round"),
                    "ts": c.get("ts"),
                    "comment": c.get("text"),
                    "view": c.get("view") or "html",
                    "anchor": c.get("anchor"),
                    "target": c.get("target"),
                    "category": None,
                    "fix": None,
                    "fix_ts": None,
                    "rounds_to_build": sinfo.get("rounds") if first_build else None,
                    "built_version": built_version,
                    "promoted": promoted,
                }
                if rid in old_rows:
                    old = old_rows[rid]
                    row["category"] = old.get("category")
                    row["fix"] = old.get("fix")
                    row["fix_ts"] = old.get("fix_ts")
                    # once a slide has a recorded first-build figure, never let a later sync
                    # (after further edits bump `rounds` again) silently inflate it
                    if old.get("rounds_to_build") is not None:
                        row["rounds_to_build"] = old["rounds_to_build"]
                seen.add(rid)
                fresh_rows.append(row)

    leftover = [old_rows[rid] for rid in old_order
                if rid not in seen
                and (old_rows[rid].get("deck"), old_rows[rid].get("slide")) not in processed_slides]
    all_rows = fresh_rows + leftover
    _write_ledger(all_rows)
    _write_summary(all_rows)
    return all_rows


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------

def _write_summary(rows):
    by_deck = {}
    for r in rows:
        by_deck.setdefault(r["deck"], []).append(r)

    lines = ["# Feedback ledger summary", "",
             "Regenerated by `python scripts/ledger.py sync`. Do not hand-edit; use `ledger.py note`.", ""]
    uncategorised = []

    for deck_name in sorted(by_deck):
        deck_rows = by_deck[deck_name]
        slides = sorted({r["slide"] for r in deck_rows})

        rtb_by_slide = {}
        for r in deck_rows:
            if r.get("rounds_to_build") is not None:
                rtb_by_slide.setdefault(r["slide"], r["rounds_to_build"])
        mean_rtb = (sum(rtb_by_slide.values()) / len(rtb_by_slide)) if rtb_by_slide else None

        cats = {}
        for r in deck_rows:
            key = r.get("category") or "uncategorised"
            cats[key] = cats.get(key, 0) + 1

        lines.append("## %s" % deck_name)
        lines.append("- slides with comments: %d" % len(slides))
        lines.append("- comments: %d" % len(deck_rows))
        if mean_rtb is not None:
            lines.append("- mean rounds to build: %.1f over %d built slides" % (mean_rtb, len(rtb_by_slide)))
        else:
            lines.append("- mean rounds to build: n/a (no built slides yet)")
        lines.append("- by category: " + ", ".join("%s %d" % (k, v) for k, v in sorted(cats.items())))
        lines.append("")

        for r in deck_rows:
            if not r.get("category"):
                uncategorised.append(r)

    lines.append("## Uncategorised comments")
    if uncategorised:
        for r in uncategorised:
            lines.append("- %s: %s" % (r["id"], r["comment"]))
    else:
        lines.append("- none")
    lines.append("")

    summary_file().write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# note / show
# ---------------------------------------------------------------------------

def note(row_id, category=None, fix=None):
    rows, order = _load_ledger()
    if row_id not in rows:
        raise KeyError("unknown ledger id: %s" % row_id)
    row = rows[row_id]
    if category is not None:
        if category not in VALID_CATEGORIES:
            raise ValueError("invalid category %r; choose from %s" % (category, sorted(VALID_CATEGORIES)))
        row["category"] = category
    if fix is not None:
        row["fix"] = fix
        row["fix_ts"] = datetime.now().isoformat(timespec="seconds")
    all_rows = [rows[rid] for rid in order]
    _write_ledger(all_rows)
    _write_summary(all_rows)
    return row


def _resolve_deck_name(deck_arg):
    """--deck accepts either a deck directory (its workroom_state.json's "deck" name is used,
    matching how sync() names rows) or a bare deck name already."""
    p = Path(deck_arg)
    if p.is_dir():
        sp = p / "workroom_state.json"
        if sp.exists():
            try:
                return json.loads(sp.read_text(encoding="utf-8")).get("deck") or p.name
            except ValueError:
                return p.name
        return p.name
    return deck_arg


def _format_pin_line(row):
    """A compact second line for a pinned comment (one with an `anchor`), e.g.:
      [ppt] @(440,160 400x396) div.card "Lab demo-deck..." : too dense
    Returns None for a row with no anchor - the caller just skips printing it."""
    anchor = row.get("anchor")
    if not anchor:
        return None
    loc = "@(%d,%d %dx%d)" % (anchor.get("x", 0), anchor.get("y", 0),
                               anchor.get("w", 0), anchor.get("h", 0))
    parts = ["[%s]" % (row.get("view") or "html"), loc]
    target = row.get("target") or {}
    tag = target.get("tag") or ""
    if tag:
        classes = target.get("classes") or ""
        sel = tag + ("." + ".".join(classes.split()) if classes else "")
        parts.append(sel)
    text = target.get("text") or ""
    if text:
        excerpt = text if len(text) <= 40 else text[:40].rstrip() + "..."
        parts.append('"%s"' % excerpt)
    return "  %s : %s" % (" ".join(parts), row.get("comment"))


def show(deck=None, uncategorised=False):
    rows, order = _load_ledger()
    out = [rows[rid] for rid in order]
    if deck is not None:
        name = _resolve_deck_name(deck)
        out = [r for r in out if r["deck"] == name]
    if uncategorised:
        out = [r for r in out if not r.get("category")]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _flag_value(argv, name):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main():
    argv = sys.argv[1:]
    _cli.usage(__doc__, argv, 1, 10 ** 6)
    args = [a for a in argv if not a.startswith("--")]
    cmd = args[0]

    if cmd == "register":
        if len(args) < 2:
            print("register needs a deck dir")
            sys.exit(1)
        p = register(args[1])
        print("registered: %s" % p)

    elif cmd == "sync":
        rows = sync()
        print("ledger: %d rows -> %s" % (len(rows), ledger_file()))
        print("summary: %s" % summary_file())

    elif cmd == "note":
        if len(args) < 2:
            print("note needs an id")
            sys.exit(1)
        row_id = args[1]
        category = _flag_value(argv, "--category")
        fix = _flag_value(argv, "--fix")
        if category is None and fix is None:
            print("note needs --category and/or --fix")
            sys.exit(1)
        try:
            row = note(row_id, category=category, fix=fix)
        except (KeyError, ValueError) as e:
            print(str(e))
            sys.exit(1)
        print("noted: %s" % row["id"])

    elif cmd == "show":
        deck = _flag_value(argv, "--deck")
        rows = show(deck=deck, uncategorised="--uncategorised" in argv)
        if not rows:
            print("(no ledger rows)")
        for r in rows:
            cat = "[%s]" % r["category"] if r.get("category") else "[uncategorised]"
            print("%s  round %s  %s  %s" % (r["id"], r.get("round"), cat, r.get("comment")))
            pin_line = _format_pin_line(r)
            if pin_line:
                print(pin_line)

    else:
        print("unknown subcommand: %s (expected register | sync | note | show)" % cmd)
        sys.exit(2)


if __name__ == "__main__":
    main()
