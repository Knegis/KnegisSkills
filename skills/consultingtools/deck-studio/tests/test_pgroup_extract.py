"""Extractor tests for .pgroup paragraphs, run through extract_geometry.py in a real browser.

Regression: a paragraph whose text sits only in inline children (<div><b>Heading</b></div>)
was dropped - neither the div (no direct text) nor the inline <b> qualified as a paragraph.
Found on three reference exhibits (a pillar heading, a callout lead, a function name).
"""
import json

import pytest

from conftest import SKILL_ROOT, run_py  # noqa: E402


def _extract(tmp_path, body):
    html = tmp_path / "slide.html"
    html.write_text(
        "<!DOCTYPE html><html><head><meta charset='UTF-8'></head>"
        "<body style=\"margin:0;padding:0;width:1280px;height:720px\">"
        "<div class=\"slide\" style=\"width:1280px;height:720px;position:relative;background:#fff\">"
        + body + "</div></body></html>", encoding="utf-8")
    out = tmp_path / "geom.json"
    r = run_py([str(SKILL_ROOT / "scripts" / "extract_geometry.py"), str(html), str(out)],
               cwd=SKILL_ROOT, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    groups = [t for t in data["texts"] if t.get("grouped")]
    assert len(groups) == 1, groups
    return ["".join(run["t"] for run in p["runs"]) for p in groups[0]["gparas"]]


@pytest.mark.browser
def test_pgroup_keeps_paragraph_made_only_of_bold(tmp_path):
    pytest.importorskip("playwright")
    paras = _extract(tmp_path,
        "<div class=\"pgroup\" style=\"position:absolute;left:20px;top:20px;width:400px\">"
        "<div><b>Consistency</b></div><div>The same scorecard in every market.</div></div>")
    assert paras == ["Consistency", "The same scorecard in every market."]


@pytest.mark.browser
def test_pgroup_bold_plus_block_child_emits_each_text_once(tmp_path):
    pytest.importorskip("playwright")
    paras = _extract(tmp_path,
        "<div class=\"pgroup\" style=\"position:absolute;left:20px;top:20px;width:400px\">"
        "<div><b>Buying</b><span style=\"display:block\">Noor Al-Sayed</span></div></div>")
    assert paras == ["Buying", "Noor Al-Sayed"]


@pytest.mark.browser
def test_pgroup_inline_bold_lead_in_stays_one_paragraph(tmp_path):
    pytest.importorskip("playwright")
    paras = _extract(tmp_path,
        "<div class=\"pgroup\" style=\"position:absolute;left:20px;top:20px;width:400px\">"
        "<div><b>Read for the reader:</b> growth is broad-based.</div><div>Second line.</div></div>")
    assert paras == ["Read for the reader: growth is broad-based.", "Second line."]
