"""Shared pytest fixtures and the `browser` marker for deck-studio tests.

Tests run offline by default. Anything requiring Playwright + a real Edge/Chrome
(geometry extraction, end-to-end deck builds) is marked `@pytest.mark.browser` and
excluded unless explicitly selected (see pytest.ini / -m browser).

Destructive tests (anything that writes deck-studio.json, patches fonts in place, or
otherwise mutates skill state) must never touch the real skill folder. Use the
`skill_copy` fixture, which copies the whole skill into a fresh temp directory and
returns its path; the copy is removed automatically at teardown.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"

# Directories/files not needed by most tests and expensive to copy repeatedly.
# We still copy `template/` because config.py / use_template.py / patch_fonts.py all resolve
# paths relative to a copied SKILL_ROOT. The plain template is the only shipped template;
# tests that need a user's own template build one with make_custom_template() below.
_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", "tests", ".git"
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "browser: requires Playwright + a real Edge/Chrome install (slow, not offline)"
    )


@pytest.fixture
def run_env():
    """A subprocess env forced to UTF-8 I/O, so docstrings/typefaces with non-ASCII
    characters (em dashes, CJK font names) never crash a Windows cp1252 console -
    the same reason SKILL.md-adjacent scripts reconfigure stdout themselves."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@pytest.fixture
def skill_copy(tmp_path):
    """A full copy of the skill folder under a temp dir, for tests that must write
    deck-studio.json, patch fonts in place, or otherwise mutate skill state. Never touches
    the real skill folder. Returns the copy's root Path."""
    dest = tmp_path / "deck-studio"
    shutil.copytree(SKILL_ROOT, dest, ignore=_COPY_IGNORE)
    return dest


def run_py(args, cwd=None, env=None, timeout=120):
    """Run `python <args>` and return the CompletedProcess (text mode, output captured)."""
    full_env = dict(os.environ)
    full_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd) if cwd else None,
        env=full_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


CUSTOM_ACCENT1 = "2A7F62"
CUSTOM_FONT = "Georgia"


def make_custom_template(dest):
    """Write a stand-in for a user's own template, derived from the plain one: a logo box in the
    master's top-right corner (chrome), a non-Arial theme font, a distinct accent1, and three
    'Blank' layouts (Blank, Blank - Dark, Blank - Light) so the white/light preference is testable."""
    import re
    import zipfile
    src = SKILL_ROOT / "template" / "plain_template.pptx"
    logo = ('<p:sp><p:nvSpPr><p:cNvPr id="99" name="Logo"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="10800000" y="200000"/><a:ext cx="1100000" cy="400000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>'
            '<a:p><a:r><a:rPr lang="en-US"/><a:t>Logo</a:t></a:r></a:p></p:txBody></p:sp>')
    renames = {"Title Only": "Blank - Dark", "Content with Caption": "Blank - Light"}
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slideMasters/slideMaster1.xml":
                data = data.decode("utf-8").replace("</p:spTree>", logo + "</p:spTree>", 1).encode("utf-8")
            elif item.filename == "ppt/theme/theme1.xml":
                x = data.decode("utf-8")
                x = re.sub(r'(<a:accent1><a:srgbClr val=")[0-9A-Fa-f]{6}', r"\g<1>" + CUSTOM_ACCENT1, x)
                x = re.sub(r'(<a:minorFont><a:latin typeface=")[^"]*', r"\g<1>" + CUSTOM_FONT, x)
                data = x.encode("utf-8")
            elif item.filename.startswith("ppt/slideLayouts/slideLayout") and item.filename.endswith(".xml"):
                x = data.decode("utf-8")
                for a, b in renames.items():
                    x = x.replace('<p:cSld name="%s"' % a, '<p:cSld name="%s"' % b)
                data = x.encode("utf-8")
            zout.writestr(item, data)
    return dest


@pytest.fixture
def custom_template(tmp_path):
    """Path to a synthetic 'user's own' template (see make_custom_template)."""
    return make_custom_template(tmp_path / "Acme template.pptx")
