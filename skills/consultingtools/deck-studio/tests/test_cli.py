"""Every scripts/*.py with a __main__ block must print usage and exit 2 on --help.

This is the contract implemented by scripts/_cli.py's usage() helper (or, for
use_template.py, an equivalent hand-rolled check) - see SKILL.md "Tools that check
your work". Exercised via subprocess so it holds regardless of internal refactors.
"""
import re
from pathlib import Path

import pytest

from conftest import SKILL_ROOT, SCRIPTS, run_py

_MAIN_RE = re.compile(r'^if __name__ == ["\']__main__["\']:', re.M)


def _scripts_with_main():
    out = []
    for p in sorted(SCRIPTS.glob("*.py")):
        if _MAIN_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
            out.append(p)
    return out


SCRIPTS_WITH_MAIN = _scripts_with_main()


def test_found_the_expected_scripts():
    # Sanity check on the discovery mechanism itself: fail loudly if scripts/ is
    # ever emptied or the __main__ convention silently dropped everywhere.
    names = {p.name for p in SCRIPTS_WITH_MAIN}
    expected = {
        "build_deck.py", "chrome_slide.py", "clone_slide.py", "doctor.py",
        "extract_geometry.py", "fontcheck.py", "html_to_pptx.py", "list_layouts.py",
        "make_template.py", "office_io.py", "patch_fonts.py", "typecheck.py",
        "use_template.py", "workroom.py",
    }
    assert expected <= names, f"missing: {expected - names}"


@pytest.mark.parametrize("script", SCRIPTS_WITH_MAIN, ids=lambda p: p.name)
def test_help_prints_usage_and_exits_2(script):
    r = run_py([str(script), "--help"], cwd=SKILL_ROOT)
    assert r.returncode == 2, (
        f"{script.name} --help exited {r.returncode}, expected 2\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
    # Usage text is the module docstring; require *some* non-trivial output so a
    # script that exits 2 with nothing printed (silent usage) still fails here.
    assert len(r.stdout.strip()) > 20, f"{script.name} --help printed almost nothing: {r.stdout!r}"


@pytest.mark.parametrize("script", SCRIPTS_WITH_MAIN, ids=lambda p: p.name)
def test_dash_h_also_triggers_usage(script):
    r = run_py([str(script), "-h"], cwd=SKILL_ROOT)
    assert r.returncode == 2, f"{script.name} -h exited {r.returncode}, expected 2"
