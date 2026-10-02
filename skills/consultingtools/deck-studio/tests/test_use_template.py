"""scripts/use_template.py: theme reading, palette derivation, chrome/layout detection, the
deck-studio.json switch/--plain round trip, and the per-deck record (--deck / --resume).

The read-only helpers are exercised against the shipped plain template and a synthetic
'user's own' template (conftest.make_custom_template). Anything that WRITES deck-studio.json
runs against the `skill_copy` fixture (a full temp copy of the skill folder) - never the real one.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import use_template as U  # noqa: E402

from conftest import CUSTOM_ACCENT1, CUSTOM_FONT, SKILL_ROOT, run_py  # noqa: E402

PLAIN_TPL = SKILL_ROOT / "template" / "plain_template.pptx"


# ---------------------------------------------------------------------------
# read-only introspection
# ---------------------------------------------------------------------------

def test_plain_template_no_chrome_and_blank_default_layout():
    theme = U.read_theme(PLAIN_TPL)
    palette = U.derive_palette(theme["scheme"])
    assert isinstance(palette, dict) and palette.get("canvas")
    assert U.master_draws_chrome(PLAIN_TPL) is False
    assert U.pick_default_layout(PLAIN_TPL) == "Blank"


def test_custom_template_chrome_font_and_accent_are_detected(custom_template):
    theme = U.read_theme(custom_template)
    assert theme["fonts"]["minor"] == CUSTOM_FONT
    assert U.master_draws_chrome(custom_template) is True
    palette = U.derive_palette(theme["scheme"])
    assert palette["mid_fill"] == "#" + CUSTOM_ACCENT1


def test_derive_palette_keeps_text_in_dark_grey_family(custom_template):
    """House rule: text is black/white/grey regardless of brand - see STYLE.md section 3."""
    for tpl in (PLAIN_TPL, custom_template):
        palette = U.derive_palette(U.read_theme(tpl)["scheme"])
        for key in ("text_primary", "text_primary_alt", "text_secondary", "text_secondary_alt", "text_caption"):
            hexv = palette[key].lstrip("#")
            r, g, b = int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16)
            assert max(r, g, b) - min(r, g, b) <= 20, f"{tpl.name}: {key}={palette[key]} is not grey-ish"


# ---------------------------------------------------------------------------
# switch() / --plain round trip - destructive, always on skill_copy
# ---------------------------------------------------------------------------

def test_switch_writes_deck_studio_json_and_plain_removes_it(skill_copy, custom_template):
    script = skill_copy / "scripts" / "use_template.py"
    machine_json = skill_copy / "deck-studio.json"
    assert not machine_json.exists()

    r = run_py([str(script), str(custom_template), "--name", "Acme"], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    written = json.loads(machine_json.read_text(encoding="utf-8"))
    assert written["template"] == "template/Acme_template.pptx"
    assert (skill_copy / "template" / "Acme_template.pptx").exists()
    assert written["template_supplies_chrome"] is True
    assert written["font"]["name"] == CUSTOM_FONT
    assert written["_client_template"]["client"] == "Acme"
    assert "Switched to template" in r.stdout

    r2 = run_py([str(script), "--plain"], cwd=skill_copy)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert not machine_json.exists()
    assert "Back on the plain built-in template" in r2.stdout


def test_switch_config_then_resolves_custom_template_and_palette(skill_copy, custom_template):
    """After switching, scripts/config.py (a fresh subprocess import) must pick up the user's
    template, font and derived palette from deck-studio.json, not house.json's plain defaults."""
    run_py([str(skill_copy / "scripts" / "use_template.py"), str(custom_template)], cwd=skill_copy)
    r = run_py(["-c", "import sys; sys.path.insert(0,'scripts'); import config; "
                      "print('TEMPLATE=' + str(config.TEMPLATE)); "
                      "print('CHROME=' + str(config.TEMPLATE_SUPPLIES_CHROME)); "
                      "print('FONT=' + config.FONT_NAME); "
                      "print('MID=' + config.PALETTE['mid_fill'])"],
               cwd=skill_copy)
    assert r.returncode == 0, r.stderr
    assert "Acme_template.pptx" in r.stdout
    assert "CHROME=True" in r.stdout
    assert "FONT=" + CUSTOM_FONT in r.stdout
    assert "MID=#" + CUSTOM_ACCENT1 in r.stdout


def test_show_names_the_active_template_and_modifies_nothing(skill_copy):
    script = skill_copy / "scripts" / "use_template.py"
    house_json = skill_copy / "house.json"
    before = house_json.read_text(encoding="utf-8")
    r = run_py([str(script), "--show"], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "active template: plain built-in template" in r.stdout
    assert not (skill_copy / "deck-studio.json").exists()
    assert house_json.read_text(encoding="utf-8") == before


def test_plain_on_defaults_is_a_no_op(skill_copy):
    r = run_py([str(skill_copy / "scripts" / "use_template.py"), "--plain"], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Already on the plain built-in template" in r.stdout


# ---------------------------------------------------------------------------
# per-deck record: --deck writes deck_template.json, --resume re-applies it
# ---------------------------------------------------------------------------

def test_deck_record_and_resume_round_trip(skill_copy, custom_template, tmp_path):
    script = skill_copy / "scripts" / "use_template.py"
    deck_a, deck_b = tmp_path / "deck_a", tmp_path / "deck_b"

    r = run_py([str(script), str(custom_template), "--name", "Acme", "--deck", str(deck_a)], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((deck_a / "deck_template.json").read_text(encoding="utf-8"))
    assert rec["kind"] == "custom" and rec["template"] == "template/Acme_template.pptx" and rec["name"] == "Acme"

    r = run_py([str(script), "--plain", "--deck", str(deck_b)], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((deck_b / "deck_template.json").read_text(encoding="utf-8")) == {"kind": "plain"}
    assert not (skill_copy / "deck-studio.json").exists()

    # back to deck A: the recorded template is re-applied from the copy in template/, no new copy
    r = run_py([str(script), "--resume", str(deck_a)], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    written = json.loads((skill_copy / "deck-studio.json").read_text(encoding="utf-8"))
    assert written["template"] == "template/Acme_template.pptx"
    assert not (skill_copy / "template" / "Acme_template_2.pptx").exists()

    r = run_py([str(script), "--resume", str(deck_b)], cwd=skill_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (skill_copy / "deck-studio.json").exists()


def test_resume_without_a_record_tells_the_agent_to_ask(skill_copy, tmp_path):
    r = run_py([str(skill_copy / "scripts" / "use_template.py"), "--resume", str(tmp_path / "new_deck")],
               cwd=skill_copy)
    assert r.returncode != 0
    assert "Ask the user which template to use" in (r.stdout + r.stderr)
