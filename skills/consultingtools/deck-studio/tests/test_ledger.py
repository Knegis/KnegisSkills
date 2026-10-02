"""scripts/ledger.py: register/sync/note/show over the feedback ledger derived from
workroom_state.json files.

Every test monkeypatches ledger.LAB_ROOT to a tmp_path, so the real <lab>/feedback/ directory
is never read or written by this suite.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ledger  # noqa: E402


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LAB_ROOT", tmp_path)
    return tmp_path


def _write_state(deck_dir, deck_name, order, slides, builds):
    deck_dir.mkdir(parents=True, exist_ok=True)
    state = {"deck": deck_name, "order": order, "slides": slides, "builds": builds}
    (deck_dir / "workroom_state.json").write_text(json.dumps(state), encoding="utf-8")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def test_register_dedupes(lab):
    d1 = lab / "deckA"
    d1.mkdir()
    p1 = ledger.register(d1)
    p2 = ledger.register(d1)
    assert p1 == p2 == str(d1.resolve())
    decks = ledger.registered_decks()
    assert decks.count(str(d1.resolve())) == 1
    assert ledger.decks_file().exists()


def test_register_two_different_decks_both_kept(lab):
    d1, d2 = lab / "deckA", lab / "deckB"
    d1.mkdir(); d2.mkdir()
    ledger.register(d1)
    ledger.register(d2)
    decks = ledger.registered_decks()
    assert str(d1.resolve()) in decks
    assert str(d2.resolve()) in decks
    assert len(decks) == 2


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

def test_sync_produces_rows_and_rounds_to_build(lab):
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 3,
                      "comments": [{"ts": "t1", "text": "fix this", "round": 1},
                                   {"ts": "t2", "text": "and this", "round": 2}],
                      "built_version": 1}},
        [{"version": 1, "ok": True, "slides": ["s1.html"]}])

    d2 = lab / "deckB"
    _write_state(
        d2, "deckB", ["s2.html"],
        {"s2.html": {"status": "active", "rounds": 1,
                      "comments": [{"ts": "t3", "text": "unbuilt slide comment", "round": 1}]}},
        [])

    ledger.register(d1)
    ledger.register(d2)
    rows = ledger.sync()

    ids = {r["id"] for r in rows}
    assert {"deckA:s1.html:0", "deckA:s1.html:1", "deckB:s2.html:0"} <= ids

    row0 = next(r for r in rows if r["id"] == "deckA:s1.html:0")
    assert row0["deck"] == "deckA"
    assert row0["slide"] == "s1.html"
    assert row0["round"] == 1
    assert row0["comment"] == "fix this"
    assert row0["rounds_to_build"] == 3
    assert row0["built_version"] == 1
    assert row0["promoted"] is False
    assert row0["category"] is None
    assert row0["fix"] is None

    row_unbuilt = next(r for r in rows if r["id"] == "deckB:s2.html:0")
    assert row_unbuilt["rounds_to_build"] is None
    assert row_unbuilt["built_version"] is None

    assert ledger.ledger_file().exists()
    assert ledger.summary_file().exists()
    # one JSON object per line
    lines = ledger.ledger_file().read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(rows)
    for line in lines:
        json.loads(line)  # must not raise


def test_sync_is_idempotent_on_row_count(lab):
    d1 = lab / "deckA"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t1", "text": "one comment", "round": 1}]}},
                 [])
    ledger.register(d1)
    rows1 = ledger.sync()
    rows2 = ledger.sync()
    assert len(rows1) == len(rows2) == 1


def test_resync_preserves_notes(lab):
    d1 = lab / "deckA"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 2,
                              "comments": [{"ts": "t1", "text": "too dense", "round": 1}]}},
                 [])
    ledger.register(d1)
    ledger.sync()
    ledger.note("deckA:s1.html:0", category="density", fix="tightened the layout")

    ledger.sync()  # a plain re-sync must not wipe the note just made
    rows = ledger.show()
    row = next(r for r in rows if r["id"] == "deckA:s1.html:0")
    assert row["category"] == "density"
    assert row["fix"] == "tightened the layout"
    assert row["fix_ts"] is not None


def test_sync_keeps_rows_for_a_deck_that_disappeared(lab):
    d1 = lab / "deckA"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t1", "text": "keep me", "round": 1}]}},
                 [])
    ledger.register(d1)
    ledger.sync()
    assert len(ledger.show()) == 1

    import shutil
    shutil.rmtree(d1)   # the deck directory itself vanished
    rows = ledger.sync()
    assert len(rows) == 1
    assert rows[0]["comment"] == "keep me"


# ---------------------------------------------------------------------------
# pinned comments (view / anchor / target) - Features 1 and 2 of workroom.py
# ---------------------------------------------------------------------------

def test_sync_carries_view_anchor_target(lab):
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 1,
                      "comments": [
                          {"ts": "t1", "text": "plain comment", "round": 1},
                          {"ts": "t2", "text": "pinned comment", "round": 1, "view": "ppt",
                           "anchor": {"x": 440, "y": 160, "w": 400, "h": 396},
                           "target": {"tag": "div", "classes": "card", "id": "",
                                      "text": "Lab demo-deck revenue trend",
                                      "box": {"x": 440, "y": 160, "w": 400, "h": 396}}},
                      ]}},
        [])
    ledger.register(d1)
    rows = ledger.sync()

    plain = next(r for r in rows if r["id"] == "deckA:s1.html:0")
    assert plain["view"] == "html"      # old-style comment with no `view` field defaults to html
    assert plain["anchor"] is None
    assert plain["target"] is None

    pinned = next(r for r in rows if r["id"] == "deckA:s1.html:1")
    assert pinned["view"] == "ppt"
    assert pinned["anchor"] == {"x": 440, "y": 160, "w": 400, "h": 396}
    assert pinned["target"]["tag"] == "div"
    assert pinned["target"]["classes"] == "card"


def test_show_prints_pin_line(lab, capsys):
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 1,
                      "comments": [
                          {"ts": "t1", "text": "too dense", "round": 1, "view": "ppt",
                           "anchor": {"x": 440, "y": 160, "w": 400, "h": 396},
                           "target": {"tag": "div", "classes": "card", "id": "",
                                      "text": "Lab demo-deck revenue trend",
                                      "box": {"x": 440, "y": 160, "w": 400, "h": 396}}},
                      ]}},
        [])
    ledger.register(d1)
    ledger.sync()

    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["ledger.py", "show"]
        ledger.main()
    finally:
        _sys.argv = old_argv

    out = capsys.readouterr().out
    assert "deckA:s1.html:0" in out
    assert "[ppt] @(440,160 400x396) div.card" in out
    assert "too dense" in out


def test_format_pin_line_returns_none_without_anchor(lab):
    row = {"comment": "no pin here", "view": "html", "anchor": None, "target": None}
    assert ledger._format_pin_line(row) is None


def test_row_id_uses_cid_when_present(lab):
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 1,
                      "comments": [{"ts": "t1", "text": "has a cid", "round": 1, "cid": "abc12345"}]}},
        [])
    ledger.register(d1)
    rows = ledger.sync()
    assert rows[0]["id"] == "deckA:s1.html:abc12345"


def test_row_id_falls_back_to_index_without_cid(lab):
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 1,
                      "comments": [{"ts": "t1", "text": "no cid yet", "round": 1}]}},
        [])
    ledger.register(d1)
    rows = ledger.sync()
    assert rows[0]["id"] == "deckA:s1.html:0"


def test_category_survives_deleting_an_earlier_comment_on_the_same_slide(lab):
    """The whole point of cid-based row ids (workroom.py Feature 3): deleting comment A must not
    disturb comment C's ledger row just because C's list index shifted down."""
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 1,
                      "comments": [
                          {"ts": "t1", "text": "comment A", "round": 1, "cid": "aaaaaaaa"},
                          {"ts": "t2", "text": "comment B", "round": 1, "cid": "bbbbbbbb"},
                          {"ts": "t3", "text": "comment C", "round": 1, "cid": "cccccccc"},
                      ]}},
        [])
    ledger.register(d1)
    ledger.sync()
    ledger.note("deckA:s1.html:cccccccc", category="content", fix="tightened the wording")

    # the reviewer deletes comment A (the earliest one) - B and C shift down to indices 0 and 1
    _write_state(
        d1, "deckA", ["s1.html"],
        {"s1.html": {"status": "active", "rounds": 1,
                      "comments": [
                          {"ts": "t2", "text": "comment B", "round": 1, "cid": "bbbbbbbb"},
                          {"ts": "t3", "text": "comment C", "round": 1, "cid": "cccccccc"},
                      ]}},
        [])
    rows = ledger.sync()

    ids = {r["id"] for r in rows}
    assert "deckA:s1.html:aaaaaaaa" not in ids   # comment A's row dropped out - it was deleted
    assert "deckA:s1.html:bbbbbbbb" in ids
    assert "deckA:s1.html:cccccccc" in ids

    row_c = next(r for r in rows if r["id"] == "deckA:s1.html:cccccccc")
    assert row_c["category"] == "content"
    assert row_c["fix"] == "tightened the wording"
    assert len(rows) == 2   # comment A's row was really dropped, not just uncategorised


def test_deleted_comment_row_not_kept_as_leftover_for_a_still_present_deck(lab):
    """Contrast with test_sync_keeps_rows_for_a_deck_that_disappeared: a deck/slide that is
    still present is trusted to report its own comment list completely, so a comment missing
    from it was deleted, not lost - unlike a deck whose directory vanished entirely."""
    d1 = lab / "deckA"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t1", "text": "will be deleted", "round": 1,
                                            "cid": "deadbeef"}]}},
                 [])
    ledger.register(d1)
    ledger.sync()
    assert len(ledger.show()) == 1

    _write_state(d1, "deckA", ["s1.html"], {"s1.html": {"status": "active", "rounds": 1, "comments": []}}, [])
    rows = ledger.sync()
    assert rows == []


# ---------------------------------------------------------------------------
# note
# ---------------------------------------------------------------------------

def test_note_sets_fields_and_validates(lab):
    d1 = lab / "deckA"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t1", "text": "wrong colour", "round": 1}]}},
                 [])
    ledger.register(d1)
    ledger.sync()

    row = ledger.note("deckA:s1.html:0", category="colour", fix="switched to sand")
    assert row["category"] == "colour"
    assert row["fix"] == "switched to sand"
    assert row["fix_ts"]

    with pytest.raises(ValueError):
        ledger.note("deckA:s1.html:0", category="not-a-real-category")

    with pytest.raises(KeyError):
        ledger.note("deckA:missing.html:0", category="other")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def test_show_filters_by_deck_and_uncategorised(lab):
    d1, d2 = lab / "deckA", lab / "deckB"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t1", "text": "a comment", "round": 1}]}},
                 [])
    _write_state(d2, "deckB", ["s2.html"],
                 {"s2.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t2", "text": "b comment", "round": 1}]}},
                 [])
    ledger.register(d1)
    ledger.register(d2)
    ledger.sync()
    ledger.note("deckA:s1.html:0", category="content", fix="rewrote it")

    assert {r["deck"] for r in ledger.show(deck="deckA")} == {"deckA"}
    assert {r["deck"] for r in ledger.show(deck=str(d2))} == {"deckB"}  # resolves a dir too
    uncategorised = ledger.show(uncategorised=True)
    assert all(not r.get("category") for r in uncategorised)
    assert "deckB:s2.html:0" in {r["id"] for r in uncategorised}
    assert "deckA:s1.html:0" not in {r["id"] for r in uncategorised}


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------

def test_summary_contains_deck_and_uncategorised_list(lab):
    d1 = lab / "deckA"
    _write_state(d1, "deckA", ["s1.html"],
                 {"s1.html": {"status": "active", "rounds": 1,
                              "comments": [{"ts": "t1", "text": "needs a source line", "round": 1}]}},
                 [])
    ledger.register(d1)
    ledger.sync()

    text = ledger.summary_file().read_text(encoding="utf-8")
    assert "deckA" in text
    assert "Uncategorised comments" in text
    assert "deckA:s1.html:0" in text
    assert "needs a source line" in text


def test_summary_reports_mean_rounds_to_build(lab):
    d1 = lab / "deckA"
    _write_state(
        d1, "deckA", ["s1.html", "s2.html"],
        {"s1.html": {"status": "active", "rounds": 2,
                      "comments": [{"ts": "t1", "text": "c1", "round": 1}],
                      "built_version": 1},
         "s2.html": {"status": "active", "rounds": 4,
                      "comments": [{"ts": "t2", "text": "c2", "round": 1}],
                      "built_version": 1}},
        [{"version": 1, "ok": True, "slides": ["s1.html", "s2.html"]}])
    ledger.register(d1)
    ledger.sync()

    text = ledger.summary_file().read_text(encoding="utf-8")
    assert "mean rounds to build: 3.0 over 2 built slides" in text
