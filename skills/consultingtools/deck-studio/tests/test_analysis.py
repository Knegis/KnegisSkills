"""Tests for scripts/analysis.py (the Analysis tab's sidecar + Excel-range reads) and the
workroom server's /api/analysis and /api/analysis/sheet endpoints.

Every workbook here is a tiny one built fresh with openpyxl in the test itself - nothing reads
a real deal databook. Server tests reuse the same offline pattern as
tests/test_workroom_server.py (a bare-bones http.server.ThreadingHTTPServer around
workroom.make_handler, no Playwright, no PowerPoint).
"""
import http.server
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analysis  # noqa: E402
import workroom  # noqa: E402


SLIDE_A = '<!DOCTYPE html><html><body><div class="slide"><div class="title">Slide A</div></div></body></html>'


# ---------------------------------------------------------------------------
# a tiny workbook: "Main" (labels + values, one typed number, one cross-sheet
# link, one same-sheet SUM, one bold label) and "Other" (feeds the link)
# ---------------------------------------------------------------------------

def _make_wb(tmp_path, name="book.xlsx"):
    wb = Workbook()
    main = wb.active
    main.title = "Main"
    main["A1"] = "Item"
    main["B1"] = "Value"
    main["A2"] = "Revenue"
    main["B2"] = 100
    main["A3"] = "Cost"
    main["B3"] = "=-'Other'!B2"
    main["A4"] = "Total"
    main["A4"].font = Font(bold=True)
    main["B4"] = "=SUM(B2:B3)"
    for r in range(5, 11):
        main["A%d" % r] = "Row%d" % r
        main["B%d" % r] = r

    other = wb.create_sheet("Other")
    other["B2"] = 40

    path = tmp_path / name
    wb.save(path)
    return path


# ---------------------------------------------------------------------------
# read_range: values, formulas, kinds, bold
# ---------------------------------------------------------------------------

def test_read_range_values_formulas_kinds_bold(tmp_path):
    path = _make_wb(tmp_path)
    grid = analysis.read_range(path, "Main", "A2:B4", context_rows=0)

    assert grid["min_row"] == 2 and grid["max_row"] == 4
    assert grid["cols"] == ["A", "B"]
    rows = {r["row"]: {c["ref"]: c for c in r["cells"]} for r in grid["rows"]}

    b2 = rows[2]["B2"]
    assert b2["kind"] == "input"
    assert b2["value"] == 100
    assert b2["formula"] is None
    assert b2["bold"] is False

    a2 = rows[2]["A2"]
    assert a2["kind"] == "text"
    assert a2["value"] == "Revenue"

    b3 = rows[3]["B3"]
    assert b3["kind"] == "link"
    assert b3["formula"] == "=-'Other'!B2"

    b4 = rows[4]["B4"]
    assert b4["kind"] == "formula"
    assert b4["formula"] == "=SUM(B2:B3)"

    a4 = rows[4]["A4"]
    assert a4["kind"] == "text"
    assert a4["value"] == "Total"
    assert a4["bold"] is True


def test_read_range_missing_file_and_sheet(tmp_path):
    path = _make_wb(tmp_path)
    missing = analysis.read_range(tmp_path / "nope.xlsx", "Main", "A1:A1")
    assert "error" in missing and "not found" in missing["error"]

    bad_sheet = analysis.read_range(path, "NoSuchSheet", "A1:A1")
    assert "error" in bad_sheet and "sheet not found" in bad_sheet["error"]


# ---------------------------------------------------------------------------
# context rows and clamping
# ---------------------------------------------------------------------------

def test_context_rows_expand_and_clamp(tmp_path):
    path = _make_wb(tmp_path)

    mid = analysis.read_range(path, "Main", "B5:B5", context_rows=2)
    assert mid["min_row"] == 3 and mid["max_row"] == 7
    assert len(mid["rows"]) == 5
    assert mid["sheet_used"] == {"max_row": 10, "max_col": 2}

    top = analysis.read_range(path, "Main", "B1:B1", context_rows=5)
    assert top["min_row"] == 1        # clamped, never negative
    assert top["max_row"] == 6

    bottom = analysis.read_range(path, "Main", "B10:B10", context_rows=5)
    assert bottom["min_row"] == 5
    assert bottom["max_row"] == 10    # clamped to the sheet's last row


# ---------------------------------------------------------------------------
# whole_sheet cap
# ---------------------------------------------------------------------------

def test_whole_sheet_cap(tmp_path, monkeypatch):
    path = _make_wb(tmp_path)
    monkeypatch.setattr(analysis, "WHOLE_SHEET_MAX_ROWS", 3)
    monkeypatch.setattr(analysis, "WHOLE_SHEET_MAX_COLS", 1)

    grid = analysis.whole_sheet(path, "Main")
    assert len(grid["rows"]) == 3
    assert grid["cols"] == ["A"]
    assert grid["sheet_used"] == {"max_row": 10, "max_col": 2}   # the real, uncapped size


def test_whole_sheet_missing_sheet(tmp_path):
    path = _make_wb(tmp_path)
    out = analysis.whole_sheet(path, "Nope")
    assert "error" in out


# ---------------------------------------------------------------------------
# precedents
# ---------------------------------------------------------------------------

def test_precedents_sum_range():
    out = analysis.precedents("=SUM(D6:D8)")
    assert out["refs"] == ["D6", "D7", "D8"]
    assert out["links"] == []


def test_precedents_sum_list():
    out = analysis.precedents("=+SUM(D9,D12,D16)")
    assert out["refs"] == ["D9", "D12", "D16"]
    assert out["links"] == []


def test_precedents_plain_ref():
    out = analysis.precedents("=+D23")
    assert out["refs"] == ["D23"]
    assert out["links"] == []


def test_precedents_cross_sheet_is_a_link_not_a_ref():
    out = analysis.precedents("=-'Net working capital'!F66", sheet="Net debt")
    assert out["refs"] == []
    assert out["links"] == [{"sheet": "Net working capital", "ref": "F66"}]


def test_precedents_same_sheet_qualified_ref_counts_as_ref():
    out = analysis.precedents("='Net debt'!D9", sheet="Net debt")
    assert out["refs"] == ["D9"]
    assert out["links"] == []


def test_precedents_dollar_signs_stripped():
    out = analysis.precedents("=+$D$6")
    assert out["refs"] == ["D6"]
    assert out["links"] == []


def test_precedents_empty_formula():
    assert analysis.precedents(None) == {"refs": [], "links": []}
    assert analysis.precedents("") == {"refs": [], "links": []}


# ---------------------------------------------------------------------------
# load_sidecar
# ---------------------------------------------------------------------------

def test_load_sidecar_missing_returns_none(tmp_path):
    assert analysis.load_sidecar(tmp_path, "s01_net_debt.html") is None


def test_load_sidecar_loads_json(tmp_path):
    payload = {"sources": [{"id": "S1", "file": "x.xlsx", "sheet": "Sheet1", "range": "A1:A1"}],
               "figures": [], "notes": ["a note"]}
    (tmp_path / "s01_net_debt.analysis.json").write_text(json.dumps(payload), encoding="utf-8")
    out = analysis.load_sidecar(tmp_path, "s01_net_debt.html")
    assert out == payload


def test_load_sidecar_bad_json_returns_none(tmp_path):
    (tmp_path / "s01_net_debt.analysis.json").write_text("{not json", encoding="utf-8")
    assert analysis.load_sidecar(tmp_path, "s01_net_debt.html") is None


# ---------------------------------------------------------------------------
# server: /api/analysis and /api/analysis/sheet
# ---------------------------------------------------------------------------

def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _start_server(tmp_path, deck="analysis-deck"):
    Handler, build_status = workroom.make_handler(tmp_path, deck)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, "http://127.0.0.1:%d/" % port


def _stop_server(httpd, thread):
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture
def analysis_deck(tmp_path):
    """A deck with three slides: one with a working sidecar, one with no sidecar, and one
    whose sidecar points at a sheet that doesn't exist (to exercise the error path)."""
    wb_path = _make_wb(tmp_path)
    other_path = _make_wb(tmp_path, name="unreferenced.xlsx")   # never named by any sidecar

    (tmp_path / "slide_a.html").write_text(SLIDE_A, encoding="utf-8")
    (tmp_path / "slide_a.analysis.json").write_text(json.dumps({
        "sources": [{"id": "S1", "file": str(wb_path), "sheet": "Main", "range": "B2:B4"}],
        "figures": [{"marker": 1, "source": "S1", "cell": "B2", "shown": "100",
                     "label": "Revenue", "box": {"x": 10, "y": 10, "w": 20, "h": 20}}],
        "notes": ["a note about slide a"],
    }), encoding="utf-8")

    (tmp_path / "slide_b.html").write_text(
        SLIDE_A.replace("Slide A", "Slide B"), encoding="utf-8")   # no sidecar

    (tmp_path / "slide_c.html").write_text(
        SLIDE_A.replace("Slide A", "Slide C"), encoding="utf-8")
    (tmp_path / "slide_c.analysis.json").write_text(json.dumps({
        "sources": [{"id": "S1", "file": str(wb_path), "sheet": "NoSuchSheet", "range": "A1:A1"}],
        "figures": [], "notes": [],
    }), encoding="utf-8")

    return tmp_path, wb_path, other_path


def test_api_analysis_shape(analysis_deck):
    tmp_path, wb_path, other_path = analysis_deck
    httpd, thread, base_url = _start_server(tmp_path)
    try:
        out = get_json(base_url + "api/analysis")
        assert out["deck"] == "analysis-deck"
        by_file = {s["file"]: s for s in out["slides"]}
        assert set(by_file) == {"slide_a.html", "slide_b.html", "slide_c.html"}

        a = by_file["slide_a.html"]
        assert a["has_sidecar"] is True
        assert a["status"] == "active"
        assert a["sidecar"]["notes"] == ["a note about slide a"]
        assert "S1" in a["grids"]
        assert a["grids"]["S1"]["rows"]
        assert a["errors"] == []

        b = by_file["slide_b.html"]
        assert b["has_sidecar"] is False
        assert b["sidecar"] is None
        assert b["grids"] == {}
        assert b["errors"] == []

        c = by_file["slide_c.html"]
        assert c["has_sidecar"] is True
        assert "S1" in c["grids"]
        assert "error" in c["grids"]["S1"]
        assert "sheet not found" in c["grids"]["S1"]["error"]
        assert len(c["errors"]) == 1
    finally:
        _stop_server(httpd, thread)


def test_api_analysis_active_then_archived_order(analysis_deck):
    tmp_path, wb_path, other_path = analysis_deck
    httpd, thread, base_url = _start_server(tmp_path)
    try:
        req = urllib.request.Request(
            base_url + "api/slide/slide_a.html/archive", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()

        out = get_json(base_url + "api/analysis")
        statuses = [s["status"] for s in out["slides"]]
        # active slides (b, c) come first, archived (a) last
        assert statuses == ["active", "active", "archived"]
        assert out["slides"][-1]["file"] == "slide_a.html"
    finally:
        _stop_server(httpd, thread)


def test_api_analysis_sheet_whole_toggle(analysis_deck):
    tmp_path, wb_path, other_path = analysis_deck
    httpd, thread, base_url = _start_server(tmp_path)
    try:
        get_json(base_url + "api/analysis")   # loads sidecars once so the allowlist is populated
        url = (base_url + "api/analysis/sheet?whole=1&sheet=Main&p="
               + urllib.parse.quote(str(wb_path), safe=""))
        grid = get_json(url)
        assert grid["sheet_used"] == {"max_row": 10, "max_col": 2}
        assert len(grid["rows"]) == 10
    finally:
        _stop_server(httpd, thread)


def test_api_analysis_sheet_refuses_unreferenced_file(analysis_deck):
    tmp_path, wb_path, other_path = analysis_deck
    httpd, thread, base_url = _start_server(tmp_path)
    try:
        get_json(base_url + "api/analysis")
        url = (base_url + "api/analysis/sheet?whole=1&sheet=Main&p="
               + urllib.parse.quote(str(other_path), safe=""))
        try:
            urllib.request.urlopen(url, timeout=10)
            raise AssertionError("expected an unreferenced file to be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        _stop_server(httpd, thread)


def test_api_analysis_sheet_missing_params(analysis_deck):
    tmp_path, wb_path, other_path = analysis_deck
    httpd, thread, base_url = _start_server(tmp_path)
    try:
        try:
            urllib.request.urlopen(base_url + "api/analysis/sheet?sheet=Main", timeout=10)
            raise AssertionError("expected a missing p to 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        _stop_server(httpd, thread)
