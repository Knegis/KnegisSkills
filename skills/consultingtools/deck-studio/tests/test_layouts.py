"""scripts/html_to_pptx.layout_target: name/alias resolution against a real unpacked template.

Uses the shipped plain template and a synthetic custom one (conftest.make_custom_template),
read-only: unpack() writes to a temp dir. config.DEFAULT_LAYOUT is a process-global read from
the real house.json at import time (default_layout "Blank") - layout_target consults it
regardless of which unpacked template dir is passed in.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import make_custom_template  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import office_io  # noqa: E402
import html_to_pptx as H  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
NEUTRAL_TPL = SKILL_ROOT / "template" / "plain_template.pptx"


@pytest.fixture
def neutral_unp(tmp_path):
    unp = tmp_path / "unpacked_neutral"
    office_io.unpack(NEUTRAL_TPL, unp)
    return unp


@pytest.fixture
def custom_unp(tmp_path):
    unp = tmp_path / "unpacked_custom"
    office_io.unpack(make_custom_template(tmp_path / "custom.pptx"), unp)
    return unp


def test_blank_alias_resolves_to_blank_on_neutral_template(neutral_unp):
    assert H.layout_target({"layout": "blank"}, neutral_unp) == "slideLayout7.xml"


def test_slideLayoutN_xml_is_a_direct_passthrough(neutral_unp):
    assert H.layout_target({"layout": "slideLayout7.xml"}, neutral_unp) == "slideLayout7.xml"


def test_unknown_layout_name_falls_back_and_prints_a_note(neutral_unp, capsys):
    result = H.layout_target({"layout": "totally_unknown_xyz"}, neutral_unp)
    out = capsys.readouterr().out
    assert "not found in template" in out
    # falls back to the default layout ("Blank"), the blankest layout on the plain template
    assert result == "slideLayout7.xml"


def test_default_layout_prefers_light_of_three_matches(custom_unp):
    """house.json's default_layout is "Blank"; the custom template has three matches
    (Blank / Blank - Dark / Blank - Light) and the picker prefers the one named Light."""
    result = H.layout_target({}, custom_unp)
    layouts = dict((f, name) for f, name, _ in H._layouts(custom_unp))
    assert layouts[result] == "Blank - Light"


def test_custom_template_has_exactly_three_blank_layouts(custom_unp):
    hits = [name for _, name, _ in H._layouts(custom_unp) if "Blank" in name]
    assert sorted(hits) == ["Blank", "Blank - Dark", "Blank - Light"], hits
