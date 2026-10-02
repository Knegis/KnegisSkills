"""patch_fonts.py + fontcheck.py against a temp unpacked copy of the neutral template.

Never mutates the real template/plain_template.pptx: office_io.unpack() writes into a
tmp_path directory, and packing produces a new file there too.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import office_io  # noqa: E402
import patch_fonts  # noqa: E402
import fontcheck  # noqa: E402
import config as C  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
NEUTRAL_TPL = SKILL_ROOT / "template" / "plain_template.pptx"

SYMBOL_FONTS = {"Wingdings", "Wingdings 2", "Wingdings 3", "Symbol", "Webdings",
                "MT Extra", "Segoe UI Symbol", "Segoe UI Emoji"}


def _typefaces_in(unp_dir):
    seen = set()
    for p in unp_dir.rglob("*.xml"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        seen.update(patch_fonts.TYPEFACE_RE.findall(text))
    return seen


def test_raw_neutral_template_has_offbrand_fonts(tmp_path):
    """Sanity check the fixture actually needs patching (else the rest is vacuous)."""
    unp = tmp_path / "unpacked"
    office_io.unpack(NEUTRAL_TPL, unp)
    faces = _typefaces_in(unp)
    offbrand = {f for f in faces if f and not f.startswith("+") and f not in SYMBOL_FONTS
                and f != C.FONT_NAME}
    assert offbrand, "expected the raw template to carry non-house typefaces before patching"


def test_patch_fonts_leaves_only_house_font_theme_refs_and_symbol_fonts(tmp_path):
    unp = tmp_path / "unpacked"
    office_io.unpack(NEUTRAL_TPL, unp)
    patch_fonts.patch(str(unp))
    faces = _typefaces_in(unp)
    for f in faces:
        assert (
            f == "" or f.startswith("+") or f in SYMBOL_FONTS or f == C.FONT_NAME
        ), f"unexpected typeface survived patching: {f!r}"
    assert C.FONT_NAME in faces


def test_patch_fonts_is_idempotent(tmp_path):
    unp = tmp_path / "unpacked"
    office_io.unpack(NEUTRAL_TPL, unp)
    patch_fonts.patch(str(unp))
    before = _typefaces_in(unp)
    patch_fonts.patch(str(unp))  # second pass should touch nothing
    after = _typefaces_in(unp)
    assert before == after


def test_fontcheck_clean_on_patched_deck(tmp_path):
    unp = tmp_path / "unpacked"
    office_io.unpack(NEUTRAL_TPL, unp)
    patch_fonts.patch(str(unp))
    out = tmp_path / "patched.pptx"
    office_io.pack(unp, out)
    target, seen, offenders = fontcheck.scan(out)
    assert offenders == []
    assert target == C.FONT_NAME


def test_fontcheck_fails_on_raw_template(tmp_path):
    # fontcheck.scan works directly on the shipped .pptx - no unpack needed here.
    target, seen, offenders = fontcheck.scan(NEUTRAL_TPL)
    assert offenders, "expected the raw (unpatched) template to have off-brand typefaces"
