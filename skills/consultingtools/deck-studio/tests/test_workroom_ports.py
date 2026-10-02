"""workroom.py --serve port handling: a second deck gets its own port, the same deck reuses its server.

Offline: real sockets on 127.0.0.1 in a high port range, no browser.
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import workroom  # noqa: E402

SLIDE = '<!DOCTYPE html><html><body><div class="slide"><div class="title">A</div></div></body></html>'
BASE_PORT = 18765


def _deck(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    (d / "slide_a.html").write_text(SLIDE, encoding="utf-8")
    return d


@pytest.fixture
def servers(tmp_path, monkeypatch):
    monkeypatch.setattr(workroom.ledger, "LAB_ROOT", tmp_path / "_ledger_root")
    started = []

    def start(d):
        Handler, _ = workroom.make_handler(d, d.name)
        httpd, port = workroom.bind_free(Handler, BASE_PORT, 10)
        workroom.write_server_file(d, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return port

    yield start
    for h in started:
        h.shutdown()
        h.server_close()


def test_second_deck_moves_to_next_free_port(tmp_path, servers):
    a, b = _deck(tmp_path, "deck_a"), _deck(tmp_path, "deck_b")
    pa, pb = servers(a), servers(b)
    assert pa != pb, "a busy port must never be shared (Windows SO_REUSEADDR allows it silently)"
    for port, d in ((pa, a), (pb, b)):
        info = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/whoami", timeout=5).read())
        assert info["app"] == workroom.WHOAMI_APP
        assert workroom._same_dir(info["dir"], d)


def test_find_running_returns_the_decks_own_server(tmp_path, servers):
    a, b, c = _deck(tmp_path, "deck_a"), _deck(tmp_path, "deck_b"), _deck(tmp_path, "deck_c")
    pa, pb = servers(a), servers(b)
    assert workroom.find_running(a) == pa
    assert workroom.find_running(b) == pb
    assert workroom.find_running(c) is None


def test_stale_server_file_is_ignored(tmp_path):
    d = _deck(tmp_path, "deck_a")
    workroom.write_server_file(d, BASE_PORT + 20)      # nothing listens there: a killed server
    t = time.time()
    assert workroom.find_running(d) is None
    assert time.time() - t < 5
    workroom.clear_server_file(d, BASE_PORT + 20)
    assert not (d / workroom.SERVER_FILE).exists()


def test_serve_reuses_a_running_server_instead_of_starting_another(tmp_path, servers, capsys):
    a = _deck(tmp_path, "deck_a")
    pa = servers(a)
    workroom.serve(a, "deck_a", BASE_PORT, open_browser=False)   # returns at once when reusing
    assert f"already running for this deck at http://127.0.0.1:{pa}/" in capsys.readouterr().out
