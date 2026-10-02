"""scripts/workroom.py --serve: the live review server (state file, JSON API, build job).

Runs fully offline - no Playwright, no PowerPoint. The build endpoints exercise the real
version-numbering / exclusion / failure-handling logic in workroom.py, but the actual
build_deck.py / render_slides.py subprocess calls are replaced with a fake via
monkeypatch.setattr(workroom.subprocess, "run", ...) so no browser or Office install is
needed to run this file. Static mode (workroom.write_static) is exercised directly too, to
confirm --serve did not change its behaviour.
"""
import base64
import http.server
import json
import os
import re
import shutil
import subprocess as _subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import workroom  # noqa: E402

from conftest import SKILL_ROOT  # noqa: E402


SLIDE_A = '<!DOCTYPE html><html><body><div class="slide"><div class="title">Slide A</div></div></body></html>'
SLIDE_B = '<!DOCTYPE html><html><body><div class="slide"><div class="title">Slide B</div></div></body></html>'

# a real, minimal 1x1 transparent PNG - enough to round-trip through the /file route
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def post_json(url, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_for_build(base_url, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_json(base_url + "api/build/status")
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("build did not finish within %ss" % timeout)


def make_fake_run(build_ok=True, render_ok=True):
    """A stand-in for subprocess.run that never touches build_deck.py / render_slides.py for
    real: it writes an empty .pptx at the requested path (build step) and a placeholder PNG
    at the requested dir (render step), matching the argv shape workroom._run_build sends."""
    def fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name
        if script == "build_deck.py":
            out_path = Path(cmd[2])
            if build_ok:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(b"")
                return _subprocess.CompletedProcess(cmd, 0, "built ok\n", "")
            return _subprocess.CompletedProcess(cmd, 1, "", "fake build failure\n")
        if script == "render_slides.py":
            # render_slides.py usage: <deck.pptx> <out_dir> - out_dir is argv[3], not argv[2]
            out_dir = Path(cmd[3])
            if render_ok:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "slide01.png").write_bytes(b"\x89PNG\r\n")
                return _subprocess.CompletedProcess(cmd, 0, "rendered ok\n", "")
            return _subprocess.CompletedProcess(cmd, 1, "", "fake render failure\n")
        raise AssertionError("unexpected subprocess call: %r" % (cmd,))
    return fake_run


@pytest.fixture
def wr_server(tmp_path, monkeypatch):
    # comment/build endpoints call ledger.sync() in-process - never let that touch the real
    # lab's feedback/ directory from a test.
    monkeypatch.setattr(workroom.ledger, "LAB_ROOT", tmp_path / "_ledger_root")
    (tmp_path / "slide_a.html").write_text(SLIDE_A, encoding="utf-8")
    (tmp_path / "slide_b.html").write_text(SLIDE_B, encoding="utf-8")

    Handler, build_status = workroom.make_handler(tmp_path, "test-deck")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = "http://127.0.0.1:%d/" % port
    try:
        yield tmp_path, base_url, build_status
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# state creation / order
# ---------------------------------------------------------------------------

def test_state_creation_and_order(wr_server):
    d, base_url, _ = wr_server
    state = get_json(base_url + "api/state")
    assert state["deck"] == "test-deck"
    assert set(state["order"]) == {"slide_a.html", "slide_b.html"}
    for f in state["order"]:
        s = state["slides"][f]
        assert s["status"] == "active"
        assert s["rounds"] == 1
        assert s["comments"] == []
        assert s["missing"] is False
    assert (d / "workroom_state.json").exists()


def test_api_order(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/order", {"order": ["slide_b.html", "slide_a.html"]})
    assert out["order"] == ["slide_b.html", "slide_a.html"]
    state = get_json(base_url + "api/state")
    assert state["order"] == ["slide_b.html", "slide_a.html"]


# ---------------------------------------------------------------------------
# archive / restore / comment
# ---------------------------------------------------------------------------

def test_archive_and_restore(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/archive")
    assert out["slides"]["slide_a.html"]["status"] == "archived"
    state = get_json(base_url + "api/state")
    assert state["slides"]["slide_a.html"]["status"] == "archived"

    out2 = post_json(base_url + "api/slide/slide_a.html/restore")
    assert out2["slides"]["slide_a.html"]["status"] == "active"


def test_comment_appends_with_round(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment", {"text": "looks good"})
    comments = out["slides"]["slide_a.html"]["comments"]
    assert len(comments) == 1
    assert comments[0]["text"] == "looks good"
    assert comments[0]["round"] == 1
    assert "ts" in comments[0]


# ---------------------------------------------------------------------------
# comment view toggle (Feature 1) and pinned comments (Feature 2)
# ---------------------------------------------------------------------------

def test_comment_with_no_view_defaults_to_html(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment", {"text": "no view given"})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["view"] == "html"
    assert "anchor" not in comment
    assert "target" not in comment


def test_comment_view_ppt_is_stored(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "check the render", "view": "ppt"})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["view"] == "ppt"


def test_comment_invalid_view_defaults_to_html(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "bogus view", "view": "powerpoint-ish"})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["view"] == "html"


def test_comment_anchor_point_stored(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "point pin", "anchor": {"x": 440, "y": 160, "w": 0, "h": 0}})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["anchor"] == {"x": 440, "y": 160, "w": 0, "h": 0}


def test_comment_anchor_box_stored(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "box pin", "anchor": {"x": 40, "y": 60, "w": 400, "h": 396}})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["anchor"] == {"x": 40, "y": 60, "w": 400, "h": 396}


def test_comment_anchor_clamped_into_slide_bounds(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "out of bounds", "anchor": {"x": -50, "y": 9000, "w": 5000, "h": -10}})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["anchor"] == {"x": 0, "y": 720, "w": 1280, "h": 0}


def test_comment_anchor_invalid_shape_is_dropped(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "not a dict", "anchor": "nope"})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert "anchor" not in comment


def test_comment_target_stored(wr_server):
    d, base_url, _ = wr_server
    target = {"tag": "DIV", "classes": "card  highlight", "id": "kpi-1",
              "text": "  Lab   demo-deck   revenue trend  ",
              "box": {"x": 40, "y": 60, "w": 400, "h": 396}}
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "pinned to this box",
                      "anchor": {"x": 240, "y": 258, "w": 400, "h": 396},
                      "target": target})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["target"]["tag"] == "div"
    assert comment["target"]["classes"] == "card highlight"   # server collapses internal whitespace
    assert comment["target"]["id"] == "kpi-1"
    assert comment["target"]["text"] == "Lab demo-deck revenue trend"
    assert comment["target"]["box"] == {"x": 40, "y": 60, "w": 400, "h": 396}


def test_comment_target_empty_dict_is_dropped(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment",
                     {"text": "nothing meaningful here",
                      "anchor": {"x": 10, "y": 10, "w": 0, "h": 0},
                      "target": {"tag": "", "classes": "", "id": "", "text": ""}})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert "target" not in comment
    assert comment["anchor"] == {"x": 10, "y": 10, "w": 0, "h": 0}   # anchor is independent of target


def test_state_for_api_returns_view_anchor_target(wr_server):
    d, base_url, _ = wr_server
    post_json(base_url + "api/slide/slide_a.html/comment",
              {"text": "full pin", "view": "ppt",
               "anchor": {"x": 100, "y": 100, "w": 50, "h": 50},
               "target": {"tag": "span", "classes": "x", "id": "", "text": "hi"}})
    state = get_json(base_url + "api/state")
    comment = state["slides"]["slide_a.html"]["comments"][0]
    assert comment["view"] == "ppt"
    assert comment["anchor"] == {"x": 100, "y": 100, "w": 50, "h": 50}
    assert comment["target"]["tag"] == "span"


# ---------------------------------------------------------------------------
# comment ids (cid), edit and delete (Feature 3)
# ---------------------------------------------------------------------------

def test_comment_gets_cid_on_create(wr_server):
    d, base_url, _ = wr_server
    out = post_json(base_url + "api/slide/slide_a.html/comment", {"text": "first"})
    cid = out["slides"]["slide_a.html"]["comments"][0]["cid"]
    assert isinstance(cid, str) and len(cid) == 8

    out2 = post_json(base_url + "api/slide/slide_a.html/comment", {"text": "second"})
    comments = out2["slides"]["slide_a.html"]["comments"]
    assert comments[0]["cid"] != comments[1]["cid"]   # unique within the slide


def test_legacy_comment_gets_cid_on_load(wr_server):
    d, base_url, _ = wr_server
    get_json(base_url + "api/state")   # trigger the first load_state()/save_state() round trip
                                        # so workroom_state.json actually exists on disk
    state_path = d / "workroom_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["slides"]["slide_a.html"]["comments"] = [
        {"ts": "2020-01-01T00:00:00", "text": "legacy comment", "round": 1}
    ]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    out = get_json(base_url + "api/state")
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment.get("cid")
    assert len(comment["cid"]) == 8

    # deterministic and idempotent: loading again yields the exact same cid, and it's persisted
    out2 = get_json(base_url + "api/state")
    assert out2["slides"]["slide_a.html"]["comments"][0]["cid"] == comment["cid"]
    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk["slides"]["slide_a.html"]["comments"][0]["cid"] == comment["cid"]


def test_comment_edit_updates_text_sets_edited_ts_keeps_anchor(wr_server):
    d, base_url, _ = wr_server
    created = post_json(base_url + "api/slide/slide_a.html/comment",
                         {"text": "original text", "view": "html",
                          "anchor": {"x": 10, "y": 20, "w": 30, "h": 40}})
    cid = created["slides"]["slide_a.html"]["comments"][0]["cid"]

    out = post_json(base_url + "api/slide/slide_a.html/comment/%s/edit" % cid,
                     {"text": "corrected text"})
    comment = out["slides"]["slide_a.html"]["comments"][0]
    assert comment["text"] == "corrected text"
    assert comment["view"] == "html"          # unchanged when not provided
    assert "edited_ts" in comment
    assert comment["anchor"] == {"x": 10, "y": 20, "w": 30, "h": 40}   # untouched


def test_comment_edit_can_change_view(wr_server):
    d, base_url, _ = wr_server
    created = post_json(base_url + "api/slide/slide_a.html/comment",
                         {"text": "hello", "view": "html"})
    cid = created["slides"]["slide_a.html"]["comments"][0]["cid"]
    out = post_json(base_url + "api/slide/slide_a.html/comment/%s/edit" % cid,
                     {"text": "hello", "view": "ppt"})
    assert out["slides"]["slide_a.html"]["comments"][0]["view"] == "ppt"


def test_comment_edit_rejects_empty_text(wr_server):
    d, base_url, _ = wr_server
    created = post_json(base_url + "api/slide/slide_a.html/comment", {"text": "hello"})
    cid = created["slides"]["slide_a.html"]["comments"][0]["cid"]
    req = urllib.request.Request(
        base_url + "api/slide/slide_a.html/comment/%s/edit" % cid,
        data=json.dumps({"text": "   "}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected an empty edit to be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_comment_edit_unknown_cid_404(wr_server):
    d, base_url, _ = wr_server
    post_json(base_url + "api/slide/slide_a.html/comment", {"text": "hello"})
    req = urllib.request.Request(
        base_url + "api/slide/slide_a.html/comment/deadbeef/edit",
        data=json.dumps({"text": "x"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected an unknown cid to 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_comment_delete_unknown_cid_404(wr_server):
    d, base_url, _ = wr_server
    post_json(base_url + "api/slide/slide_a.html/comment", {"text": "hello"})
    req = urllib.request.Request(
        base_url + "api/slide/slide_a.html/comment/deadbeef/delete",
        data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected an unknown cid to 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_comment_delete_removes_and_renumbers_pins(wr_server):
    d, base_url, _ = wr_server
    c1 = post_json(base_url + "api/slide/slide_a.html/comment",
                    {"text": "pin one", "anchor": {"x": 10, "y": 10, "w": 0, "h": 0}})
    cid1 = c1["slides"]["slide_a.html"]["comments"][0]["cid"]
    c2 = post_json(base_url + "api/slide/slide_a.html/comment",
                    {"text": "pin two", "anchor": {"x": 20, "y": 20, "w": 0, "h": 0}})
    comments_before = c2["slides"]["slide_a.html"]["comments"]
    cid2 = comments_before[1]["cid"]
    assert len(comments_before) == 2

    out = post_json(base_url + "api/slide/slide_a.html/comment/%s/delete" % cid1)
    comments_after = out["slides"]["slide_a.html"]["comments"]
    assert len(comments_after) == 1
    assert comments_after[0]["cid"] == cid2

    # pin numbering is just this array's position among anchored comments (see workroom.py's
    # client-side pinsForFile) - with cid1 gone, cid2 is now number 1
    anchored = [c for c in comments_after if c.get("anchor")]
    assert len(anchored) == 1
    assert anchored[0]["cid"] == cid2

    state = get_json(base_url + "api/state")
    assert len(state["slides"]["slide_a.html"]["comments"]) == 1


def test_rounds_increment_on_mtime_change(wr_server):
    d, base_url, _ = wr_server
    state = get_json(base_url + "api/state")
    assert state["slides"]["slide_a.html"]["rounds"] == 1

    p = d / "slide_a.html"
    new_mtime = time.time() + 5
    os.utime(p, (new_mtime, new_mtime))

    state2 = get_json(base_url + "api/state")
    assert state2["slides"]["slide_a.html"]["rounds"] == 2

    # a second read with no further file change must not bump it again
    state3 = get_json(base_url + "api/state")
    assert state3["slides"]["slide_a.html"]["rounds"] == 2


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def test_build_success_versioning_and_exclusions(wr_server, monkeypatch):
    d, base_url, _ = wr_server
    monkeypatch.setattr(workroom.subprocess, "run", make_fake_run())

    post_json(base_url + "api/order", {"order": ["slide_b.html", "slide_a.html"]})
    post_json(base_url + "api/slide/slide_b.html/archive")   # excluded from the build set

    started = post_json(base_url + "api/build")
    assert started["ok"] is True
    assert started["version"] == 1

    status = wait_for_build(base_url)
    assert status["status"] == "done"
    result = status["result"]
    assert result["ok"] is True
    assert result["version"] == 1
    assert result["slides"] == ["slide_a.html"]          # archived slide_b excluded, order respected
    assert (d / "build" / "test-deck_v01.pptx").exists()
    assert (d / "build" / "v01_png" / "slide01.png").exists()

    state = get_json(base_url + "api/state")
    assert state["slides"]["slide_a.html"]["built_version"] == 1
    assert "built_version" not in state["slides"]["slide_b.html"]

    # a second build never overwrites the first - version bumps to 2
    post_json(base_url + "api/slide/slide_b.html/restore")
    started2 = post_json(base_url + "api/build")
    assert started2["version"] == 2
    status2 = wait_for_build(base_url)
    assert status2["result"]["version"] == 2
    assert (d / "build" / "test-deck_v01.pptx").exists()   # v01 still there
    assert (d / "build" / "test-deck_v02.pptx").exists()


def test_page_shows_persisted_build_status_after_restart(wr_server, monkeypatch):
    """A server restart must not forget a build that already happened: the header's initial
    status comes from the latest entry in workroom_state.json's `builds`, not just the
    in-memory (freshly "idle") build_status of the new process."""
    d, base_url, _ = wr_server
    monkeypatch.setattr(workroom.subprocess, "run", make_fake_run())
    post_json(base_url + "api/build")
    wait_for_build(base_url)

    fresh_handler, _fresh_build_status = workroom.make_handler(d, "test-deck")
    fresh_httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), fresh_handler)
    fresh_port = fresh_httpd.server_address[1]
    fresh_thread = threading.Thread(target=fresh_httpd.serve_forever, daemon=True)
    fresh_thread.start()
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/" % fresh_port, timeout=10) as r:
            page = r.read().decode("utf-8")
        m = re.search(r'id="initial-build" type="application/json">(.*?)</script>', page, re.S)
        assert m
        initial_build = json.loads(m.group(1))
        assert initial_build["status"] == "done"
        assert initial_build["result"]["version"] == 1
    finally:
        fresh_httpd.shutdown()
        fresh_httpd.server_close()
        fresh_thread.join(timeout=5)


def test_build_failure_leaves_built_version_unset(wr_server, monkeypatch):
    d, base_url, _ = wr_server
    monkeypatch.setattr(workroom.subprocess, "run", make_fake_run(build_ok=False))

    post_json(base_url + "api/build")
    status = wait_for_build(base_url)
    assert status["status"] == "error"
    assert status["result"]["ok"] is False

    state = get_json(base_url + "api/state")
    assert "built_version" not in state["slides"]["slide_a.html"]
    assert "built_version" not in state["slides"]["slide_b.html"]
    assert not (d / "build" / "test-deck_v01.pptx").exists()


def test_build_already_running_is_rejected(wr_server, monkeypatch):
    d, base_url, build_status = wr_server

    started_render = threading.Event()
    release_render = threading.Event()

    def slow_fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name
        if script == "build_deck.py":
            out_path = Path(cmd[2])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"")
            started_render.set()
            release_render.wait(timeout=10)
            return _subprocess.CompletedProcess(cmd, 0, "", "")
        out_dir = Path(cmd[3])  # render_slides.py usage: <deck.pptx> <out_dir>
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "slide01.png").write_bytes(b"\x89PNG\r\n")
        return _subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(workroom.subprocess, "run", slow_fake_run)

    post_json(base_url + "api/build")
    assert started_render.wait(timeout=10)

    req = urllib.request.Request(base_url + "api/build", data=b"{}",
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected the second concurrent build to be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 409

    release_render.set()
    wait_for_build(base_url)


# ---------------------------------------------------------------------------
# static mode unchanged
# ---------------------------------------------------------------------------

def test_static_mode_still_writes_workroom_html(tmp_path):
    (tmp_path / "slide_a.html").write_text(SLIDE_A, encoding="utf-8")
    (tmp_path / "slide_b.html").write_text(SLIDE_B, encoding="utf-8")

    workroom.write_static(tmp_path, "static-deck", open_browser=False)

    out = tmp_path / "workroom.html"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "static-deck" in text
    assert "Slide A" in text and "Slide B" in text
    assert not (tmp_path / "workroom_state.json").exists()


# ---------------------------------------------------------------------------
# grid (contact-sheet) zoom: a fixed-width .pane so panes actually sit side by
# side instead of each stretching to fill the row (see WORKROOM.md "grid" zoom)
# ---------------------------------------------------------------------------

def test_server_page_has_fixed_width_grid_pane_rule(wr_server):
    """Cheap regression guard: the served page's CSS must pin `.pane`'s width in z33 (grid)
    mode, not just its .frame - otherwise a pane with its comment list open (or, before the
    Analysis tab, its action buttons) stretches wide and the contact sheet stops being a grid."""
    d, base_url, _ = wr_server
    with urllib.request.urlopen(base_url, timeout=10) as r:
        page = r.read().decode("utf-8")
    m = re.search(r"body\.z33\s+\.pane\{width:\s*(\d+)px", page)
    assert m, "expected a body.z33 .pane{width:...px} rule in the served page's CSS"
    assert int(m.group(1)) > 0


def test_static_mode_page_has_fixed_width_grid_pane_rule(tmp_path):
    (tmp_path / "slide_a.html").write_text(SLIDE_A, encoding="utf-8")
    workroom.write_static(tmp_path, "static-deck", open_browser=False)
    text = (tmp_path / "workroom.html").read_text(encoding="utf-8")
    m = re.search(r"body\.z33\s+\.pane\{width:\s*(\d+)px", text)
    assert m, "expected a body.z33 .pane{width:...px} rule in the static workroom.html CSS"
    assert int(m.group(1)) > 0


# ---------------------------------------------------------------------------
# image reference rewriting (file:///, bare absolute, and relative src=/url(...))
# ---------------------------------------------------------------------------

def _start_bare_server(tmp_path, deck="img-deck"):
    """A server not wired through the wr_server fixture, for tests that need to control the
    slide files written into tmp_path before the server ever starts."""
    Handler, build_status = workroom.make_handler(tmp_path, deck)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, "http://127.0.0.1:%d/" % port


def _stop_bare_server(httpd, thread):
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def test_serve_mode_rewrites_file_and_relative_image_refs(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    abs_png = assets / "photo.png"
    abs_png.write_bytes(TINY_PNG)
    rel_png = tmp_path / "logo.png"
    rel_png.write_bytes(TINY_PNG)

    file_uri = abs_png.resolve().as_uri()  # file:///...
    (tmp_path / "slide_img.html").write_text(
        '<!DOCTYPE html><html><body><div class="slide">'
        '<img src="%s">'
        '<div style="background-image:url(logo.png)"></div>'
        '</div></body></html>' % file_uri,
        encoding="utf-8")

    httpd, thread, base_url = _start_bare_server(tmp_path)
    try:
        with urllib.request.urlopen(base_url, timeout=10) as r:   # GET / regenerates _workroom copies
            r.read()

        wrapped = (tmp_path / "_workroom" / "slide_img.html").read_text(encoding="utf-8")
        # in serve mode nothing loads over file:// any more - neither the slide's own images
        # nor WRAP's @font-face block (see test_serve_mode_rewrites_font_face_urls below)
        assert "file:///" not in wrapped
        # derive the expected URLs the same way workroom.py itself does (a file:/// URI keeps
        # forward slashes; a relative path resolves through slide_dir and keeps native ones -
        # both work against Path() on Windows, but only one matches byte-for-byte)
        _, abs_value = workroom._classify_ref(file_uri)
        abs_url = workroom._file_route_url(abs_value)
        rel_url = workroom._file_route_url(str((tmp_path / "logo.png").resolve()))
        assert abs_url in wrapped
        assert rel_url in wrapped

        for u in (abs_url, rel_url):
            with urllib.request.urlopen(base_url.rstrip("/") + u, timeout=10) as r:
                assert r.headers.get("Content-Type") == "image/png"
                assert r.read() == TINY_PNG
    finally:
        _stop_bare_server(httpd, thread)


def test_file_route_rejects_bad_extension_and_missing_file(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello", encoding="utf-8")
    missing_png = tmp_path / "missing.png"
    (tmp_path / "slide_a.html").write_text(SLIDE_A, encoding="utf-8")

    httpd, thread, base_url = _start_bare_server(tmp_path)
    try:
        bad_ext = base_url + "file?p=" + urllib.parse.quote(str(other), safe="")
        try:
            urllib.request.urlopen(bad_ext, timeout=10)
            raise AssertionError("expected a .txt file to be rejected")
        except urllib.error.HTTPError as e:
            assert e.code == 400

        missing = base_url + "file?p=" + urllib.parse.quote(str(missing_png), safe="")
        try:
            urllib.request.urlopen(missing, timeout=10)
            raise AssertionError("expected a missing file to 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        _stop_bare_server(httpd, thread)


# ---------------------------------------------------------------------------
# @font-face rewriting (same file:/// problem as images, fixed the same way)
# ---------------------------------------------------------------------------

def test_serve_mode_rewrites_font_face_urls(wr_server):
    d, base_url, _ = wr_server
    if workroom._cfg.IS_SYSTEM_FONT or not workroom._cfg.FONT_DIR:
        pytest.skip("no bundled brand font resolved on this machine")

    with urllib.request.urlopen(base_url, timeout=10) as r:   # GET / regenerates _workroom copies
        r.read()

    wrapped = (d / "_workroom" / "slide_a.html").read_text(encoding="utf-8")
    assert "@font-face" in wrapped
    assert "file:///" not in wrapped
    assert "/file?p=" in wrapped

    font_file = next(iter(workroom._cfg.FONT_FACES.values()))
    font_path = Path(workroom._cfg.FONT_DIR) / font_file
    font_url = base_url.rstrip("/") + "/file?p=" + urllib.parse.quote(str(font_path), safe="")
    with urllib.request.urlopen(font_url, timeout=10) as r:
        assert r.headers.get("Content-Type", "").startswith("font/")
        assert len(r.read()) > 0


def test_static_mode_rewrites_relative_image_paths_only(tmp_path):
    rel_img = tmp_path / "pic.png"
    rel_img.write_bytes(TINY_PNG)
    file_uri = rel_img.resolve().as_uri()

    (tmp_path / "slide_rel.html").write_text(
        '<!DOCTYPE html><html><body><div class="slide"><img src="pic.png"></div></body></html>',
        encoding="utf-8")
    (tmp_path / "slide_abs.html").write_text(
        '<!DOCTYPE html><html><body><div class="slide"><img src="%s"></div></body></html>' % file_uri,
        encoding="utf-8")

    workroom.write_static(tmp_path, "img-static-deck", open_browser=False)

    wrapped_rel = (tmp_path / "_workroom" / "slide_rel.html").read_text(encoding="utf-8")
    assert 'src="../pic.png"' in wrapped_rel

    wrapped_abs = (tmp_path / "_workroom" / "slide_abs.html").read_text(encoding="utf-8")
    assert file_uri in wrapped_abs
    assert "/file?p=" not in wrapped_abs


# ---------------------------------------------------------------------------
# promote to reference (roadmap 2.3) - always against a throwaway copy of reference/,
# monkeypatching workroom.REFERENCE_DIR so the real corpus is never touched
# ---------------------------------------------------------------------------

@pytest.fixture
def ref_copy(tmp_path, monkeypatch):
    dest = tmp_path / "_reference_copy"
    shutil.copytree(SKILL_ROOT / "reference", dest)
    monkeypatch.setattr(workroom, "REFERENCE_DIR", dest)
    return dest


def _build_slide_a_only(base_url):
    """Archive slide_b and build, so the build's `slides` list is exactly ["slide_a.html"] -
    slide01.png (from make_fake_run's render step) then matches slide_a's position."""
    post_json(base_url + "api/slide/slide_b.html/archive")
    post_json(base_url + "api/build")
    return wait_for_build(base_url)


def test_promote_happy_path(wr_server, monkeypatch, ref_copy):
    d, base_url, _ = wr_server
    monkeypatch.setattr(workroom.subprocess, "run", make_fake_run())
    status = _build_slide_a_only(base_url)
    assert status["result"]["ok"] is True

    out = post_json(base_url + "api/slide/slide_a.html/promote",
                     {"tier": "2", "msgtype": "statement", "slug": "smoke test slug!!",
                      "learn": "keep it simple"})
    assert "error" not in out, out

    name = "T2_statement_smoke_test_slug"
    assert (ref_copy / (name + ".html")).exists()
    assert (ref_copy / (name + ".png")).exists()
    assert (ref_copy / (name + ".html")).read_bytes() == (d / "slide_a.html").read_bytes()

    manifest = (ref_copy / "MANIFEST.md").read_text(encoding="utf-8")
    assert ("`%s`" % name) in manifest
    assert "keep it simple" in manifest
    assert "Slide A" in manifest   # "What it is" = the slide title

    corpus = (ref_copy / "CORPUS_SHA256.txt").read_text(encoding="utf-8")
    assert ("*%s.html" % name) in corpus
    assert ("*%s.png" % name) in corpus

    assert out["slides"]["slide_a.html"]["promoted"]["as"] == name
    assert out["slides"]["slide_a.html"]["promoted"]["version"] == 1
    assert out["promote"] == {"html": "reference/%s.html" % name, "png": "reference/%s.png" % name}

    # the pane's badge draws straight from state - confirm a fresh GET /api/state agrees
    state = get_json(base_url + "api/state")
    assert state["slides"]["slide_a.html"]["promoted"]["as"] == name


def test_promote_duplicate_name_refused_409(wr_server, monkeypatch, ref_copy):
    d, base_url, _ = wr_server
    monkeypatch.setattr(workroom.subprocess, "run", make_fake_run())
    _build_slide_a_only(base_url)

    payload = {"tier": "2", "msgtype": "statement", "slug": "dup_test", "learn": "x"}
    first = post_json(base_url + "api/slide/slide_a.html/promote", payload)
    assert "error" not in first

    req = urllib.request.Request(
        base_url + "api/slide/slide_a.html/promote",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected a duplicate reference name to be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 409


def test_promote_refused_without_a_build(wr_server, ref_copy):
    d, base_url, _ = wr_server
    payload = {"tier": "1", "msgtype": "statement", "slug": "no_build_test", "learn": "x"}
    req = urllib.request.Request(
        base_url + "api/slide/slide_a.html/promote",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected a promote with no build to be rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 400
    assert not (ref_copy / "T1_statement_no_build_test.html").exists()


def test_analysis_view_hidden_rule():
    """The Analysis panel has an explicit display rule, so [hidden] needs its own display:none or the
    panel shows under the Slides tab (seen live 2026-09-19)."""
    import workroom
    css = workroom.SERVE_CSS if hasattr(workroom, "SERVE_CSS") else open(workroom.__file__, encoding="utf-8").read()
    assert "#analysisView[hidden]{display:none;}" in css


def test_server_page_keeps_pin_button_in_grid_zoom(wr_server):
    """v0.3.4: grid (z33) hides the action buttons but must keep the Pin button and the pin note
    popover, plus Archive/Restore, otherwise nothing can be pinned or archived from the contact sheet."""
    d, base_url, _ = wr_server
    with urllib.request.urlopen(base_url, timeout=10) as r:
        page = r.read().decode("utf-8")
    hide = re.search(r"body\.z33 \.cap \.actbtn:not\(\.pinbtn\):not\(\.archbtn\)\{display:none;\}", page)
    assert hide, "grid mode must hide .actbtn except .pinbtn and .archbtn"
    assert re.search(r"body\.z33 \.cap \.archbtn,body\.z33 \.cap \.pinbtn\{display:inline-block;", page)
    assert 'class="actbtn archbtn"' in page, "the Archive/Restore button needs the archbtn class"
    assert not re.search(r"body\.z33[^\n]*\.pinpop\{display:none", page), "pin popover must stay usable in grid"
