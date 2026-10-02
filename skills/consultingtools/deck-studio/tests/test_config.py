"""scripts/config.py: house.json / deck-studio.json / env-var precedence and error handling.

Never mutates the real skill's house.json / deck-studio.json - every test builds a minimal
fixture tree (scripts/config.py + house.json [+ deck-studio.json] + template/*.pptx) under
tmp_path and imports config fresh via subprocess, because config.py resolves everything
relative to its own on-disk location (SKILL_ROOT = Path(__file__).resolve().parent.parent)
at import time - there is no way to re-resolve it in-process without reloading the module,
and a subprocess is the cleanest way to get a truly fresh import per scenario.
"""
import json
import textwrap
from pathlib import Path

import pytest

from conftest import SKILL_ROOT, run_py

CONFIG_SRC = (SKILL_ROOT / "scripts" / "config.py").read_text(encoding="utf-8")
CLI_SRC = (SKILL_ROOT / "scripts" / "_cli.py").read_text(encoding="utf-8")


def _fixture(tmp_path, house_json=None, house_json_text=None, machine_json=None,
             templates=("a.pptx", "b.pptx")):
    """A minimal on-disk tree config.py can resolve against: scripts/{config.py,_cli.py},
    house.json (or raw text, to test invalid JSON), deck-studio.json (optional), and dummy
    template files (existence is all config.TEMPLATE resolution checks)."""
    root = tmp_path / "skill"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "config.py").write_text(CONFIG_SRC, encoding="utf-8")
    (root / "scripts" / "_cli.py").write_text(CLI_SRC, encoding="utf-8")
    (root / "template").mkdir()
    for t in templates:
        (root / "template" / t).write_bytes(b"PK\x03\x04")  # just needs to exist + .pptx suffix

    if house_json_text is not None:
        (root / "house.json").write_text(house_json_text, encoding="utf-8")
    elif house_json is not None:
        (root / "house.json").write_text(json.dumps(house_json), encoding="utf-8")

    if machine_json is not None:
        (root / "deck-studio.json").write_text(json.dumps(machine_json), encoding="utf-8")

    return root


def _read_config_template(root, env=None):
    r = run_py(["-c", "import sys; sys.path.insert(0,'scripts'); import config; "
                      "print('TEMPLATE=' + str(config.TEMPLATE))"],
               cwd=root, env=env)
    return r


def test_defaults_when_house_json_missing(tmp_path):
    root = _fixture(tmp_path, house_json=None, templates=("plain_template.pptx",))
    r = _read_config_template(root)
    assert r.returncode == 0, r.stderr
    assert "deck-studio: WARNING" in r.stderr
    assert "not found; using built-in defaults" in r.stderr
    # falls back to the alphabetically-first *.pptx found under template/
    assert "TEMPLATE=" in r.stdout and "plain_template.pptx" in r.stdout


def test_invalid_house_json_is_fatal_with_path_in_message(tmp_path):
    root = _fixture(tmp_path, house_json_text="{not valid json", templates=("x.pptx",))
    r = _read_config_template(root)
    assert r.returncode != 0
    assert "is not valid JSON" in r.stderr
    assert str(root / "house.json") in r.stderr or "house.json" in r.stderr


def test_house_json_template_value_used_by_default(tmp_path):
    root = _fixture(tmp_path, house_json={"template": "template/b.pptx"},
                     templates=("a.pptx", "b.pptx"))
    r = _read_config_template(root)
    assert r.returncode == 0, r.stderr
    assert "b.pptx" in r.stdout and "a.pptx" not in r.stdout


def test_machine_json_overrides_house_json(tmp_path):
    root = _fixture(tmp_path, house_json={"template": "template/a.pptx"},
                     machine_json={"template": "template/b.pptx"},
                     templates=("a.pptx", "b.pptx"))
    r = _read_config_template(root)
    assert r.returncode == 0, r.stderr
    assert "b.pptx" in r.stdout


def test_env_var_overrides_machine_json(tmp_path):
    root = _fixture(tmp_path, house_json={"template": "template/a.pptx"},
                     machine_json={"template": "template/b.pptx"},
                     templates=("a.pptx", "b.pptx"))
    # the env-var template need not live under template/ at all
    env_tpl = tmp_path / "elsewhere.pptx"
    env_tpl.write_bytes(b"PK\x03\x04")
    r = _read_config_template(root, env={"DECK_STUDIO_TEMPLATE": str(env_tpl)})
    assert r.returncode == 0, r.stderr
    assert "elsewhere.pptx" in r.stdout


def test_full_precedence_chain_env_wins_over_everything(tmp_path):
    """One scenario with all four levels present and different: env wins."""
    root = _fixture(tmp_path, house_json={"template": "template/a.pptx"},
                     machine_json={"template": "template/b.pptx"},
                     templates=("a.pptx", "b.pptx", "c.pptx"))
    env_tpl = root / "template" / "c.pptx"
    r = _read_config_template(root, env={"DECK_STUDIO_TEMPLATE": str(env_tpl)})
    assert r.returncode == 0, r.stderr
    assert "c.pptx" in r.stdout


def test_missing_machine_json_is_not_fatal(tmp_path):
    """deck-studio.json is a convenience override; if it's unparsable it is ignored, not fatal."""
    root = _fixture(tmp_path, house_json={"template": "template/a.pptx"}, templates=("a.pptx",))
    (root / "deck-studio.json").write_text("{broken", encoding="utf-8")
    r = _read_config_template(root)
    assert r.returncode == 0, r.stderr
    assert "a.pptx" in r.stdout
