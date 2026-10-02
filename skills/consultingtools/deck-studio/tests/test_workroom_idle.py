"""workroom.py --serve idle shutdown: a forgotten review server stops by itself.

Offline, like test_workroom_server.py: a ThreadingHTTPServer around workroom.make_handler, with
the watchdog run at sub-second timings instead of hours.
"""
import http.server
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import workroom  # noqa: E402

SLIDE = '<!DOCTYPE html><html><body><div class="slide"><div class="title">A</div></div></body></html>'


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(workroom.ledger, "LAB_ROOT", tmp_path / "_ledger_root")
    (tmp_path / "slide_a.html").write_text(SLIDE, encoding="utf-8")
    Handler, build_status = workroom.make_handler(tmp_path, "idle-deck")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = "http://127.0.0.1:%d/" % httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd, Handler, build_status, base, t
    httpd.server_close()


def _watch(httpd, Handler, build_status, idle_s):
    w = threading.Thread(target=workroom.idle_watchdog,
                         args=(httpd, Handler, build_status, idle_s, 0.05), daemon=True)
    w.start()
    return w


def test_idle_server_stops_by_itself(served):
    httpd, Handler, build_status, base, t = served
    _watch(httpd, Handler, build_status, 0.3)
    t.join(timeout=5)
    assert not t.is_alive(), "serve_forever should have returned after the idle limit"


def test_requests_keep_the_server_alive(served):
    httpd, Handler, build_status, base, t = served
    w = _watch(httpd, Handler, build_status, 0.5)
    for _ in range(8):                      # 8 x 0.15 s = 1.2 s, well past the 0.5 s limit
        urllib.request.urlopen(base + "api/state", timeout=5).read()
        time.sleep(0.15)
    assert t.is_alive(), "a server that keeps getting requests must not stop"
    t.join(timeout=5)                       # then it goes quiet and stops
    assert not t.is_alive()
    assert not w.is_alive()


def test_running_build_blocks_idle_shutdown(served):
    httpd, Handler, build_status, base, t = served
    build_status["status"] = "running"
    _watch(httpd, Handler, build_status, 0.2)
    time.sleep(0.8)
    assert t.is_alive(), "never stop mid-build"
    build_status["status"] = "done"
    t.join(timeout=5)
    assert not t.is_alive()


def test_idle_hours_flag_is_not_taken_as_the_deck_dir(tmp_path, monkeypatch):
    (tmp_path / "slide_a.html").write_text(SLIDE, encoding="utf-8")
    seen = {}
    monkeypatch.setattr(workroom, "serve",
                        lambda d, deck, port, open_browser, idle_hours: seen.update(d=d, idle=idle_hours))
    monkeypatch.setattr(sys, "argv", ["workroom.py", str(tmp_path), "--serve", "--idle-hours", "0.5"])
    workroom.main()
    assert seen == {"d": tmp_path.resolve(), "idle": 0.5}
