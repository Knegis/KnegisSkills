"""Check that this machine can build decks with the deck-studio skill. Run this first on a new laptop.

Usage: python scripts/doctor.py

Reports what resolved, what is missing, and how to fix each gap. Exit code 1 if anything
essential is missing. Nothing is written or changed.
"""
import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli  # noqa: E402 - shared --help / arg-count handling
import config as C  # noqa: E402

OK, WARN, BAD = "  OK  ", " WARN ", " MISS "
problems, warnings = [], []


def line(state, label, detail=""):
    print(f"[{state}] {label:<34} {detail}")


def check_essential(cond, label, detail, fix):
    line(OK if cond else BAD, label, detail)
    if not cond:
        problems.append((label, fix))


def check_optional(cond, label, detail, fix):
    line(OK if cond else WARN, label, detail)
    if not cond:
        warnings.append((label, fix))


def system_font_present(name):
    """Best-effort: look for a font file whose name starts with the family name."""
    stem = name.lower().replace(" ", "")
    roots = [Path("C:/Windows/Fonts"), C.HOME / "AppData/Local/Microsoft/Windows/Fonts",
             Path("/Library/Fonts"), C.HOME / "Library/Fonts", Path("/usr/share/fonts")]
    for r in roots:
        if r.exists():
            for p in r.rglob("*"):
                if p.suffix.lower() in (".ttf", ".otf", ".ttc") and p.stem.lower().replace(" ", "").startswith(stem):
                    return True
    return False


def _user_font_install_dirs():
    """Where setup.py installs the bundled brand faces for the current user, per OS."""
    system = platform.system()
    if system == "Windows":
        return [C.HOME / "AppData/Local/Microsoft/Windows/Fonts", Path("C:/Windows/Fonts")]
    elif system == "Darwin":
        return [C.HOME / "Library/Fonts", Path("/Library/Fonts")]
    else:
        return [C.HOME / ".local/share/fonts"]


def faces_installed_for_user():
    """True if every bundled face (house.json font.faces) is present in a user font dir -
    i.e. PowerPoint will actually use the house font, not just the pipeline's own scripts."""
    if not C.FONT_FACES:
        return True   # system font - nothing to install
    names = {Path(f).stem.lower() for f in C.FONT_FACES.values()}
    for d in _user_font_install_dirs():
        if not d.exists():
            continue
        found = {p.stem.lower() for p in d.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc")}
        if names <= found:
            return True
    return False


def _browser_paths():
    """OS-appropriate places to look for an installed Edge/Chrome. Returns the first hit, or None."""
    system = platform.system()
    if system == "Windows":
        return next((p for p in [
            Path(r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path(r"C:/Program Files/Microsoft/Edge/Application/msedge.exe")] if p.exists()), None) \
            or shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    elif system == "Darwin":
        return next((p for p in [
            Path("/Applications/Microsoft Edge.app"),
            Path("/Applications/Google Chrome.app")] if p.exists()), None) \
            or shutil.which("chromium")
    else:
        return shutil.which("msedge") or shutil.which("google-chrome") or shutil.which("chromium")


def _bundled_chromium_present():
    """Best-effort check for a Playwright-installed Chromium, without actually launching it."""
    roots = [C.HOME / "AppData/Local/ms-playwright", C.HOME / ".cache/ms-playwright",
             C.HOME / "Library/Caches/ms-playwright"]
    return any(r.exists() and any(r.glob("chromium-*")) for r in roots)


def main():
    _cli.usage(__doc__, sys.argv[1:], 0, 0)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print(f"\ndeck-studio doctor  v{C.VERSION}   (skill at {C.SKILL_ROOT})\n" + "-" * 78)

    # --- python + libraries ---
    v = sys.version_info
    check_essential(v >= (3, 9), "Python >= 3.9", f"{v.major}.{v.minor}.{v.micro}", "install a newer Python")
    for mod, pkg, why in [("pptx", "python-pptx", "packing, validation, native charts")]:
        found = importlib.util.find_spec(mod) is not None
        check_essential(found, f"python module: {pkg}", why, f"pip install {pkg}")
    check_optional(importlib.util.find_spec("playwright") is not None,
                   "python module: playwright", "geometry extraction",
                   "pip install playwright  (extract_geometry uses system Edge/Chrome, not bundled browsers)")

    # --- house settings ---
    line(OK, "house.json", f"brand '{C.BRAND}', font '{C.FONT_NAME}'"
         + (" (system font)" if C.IS_SYSTEM_FONT else f" ({len(C.FONT_FACES)} brand faces)")
         + (f", wordmark '{C.WORDMARK_TEXT}'" if C.WORDMARK_TEXT else ", no wordmark"))

    # --- template ---
    check_essential(bool(C.TEMPLATE and C.TEMPLATE.exists()), "template .pptx",
                    str(C.TEMPLATE) if C.TEMPLATE else "not found",
                    "run  python scripts/make_template.py  to generate the neutral one, or set "
                    "DECK_STUDIO_TEMPLATE / house.json 'template' to your own 16:9 .pptx")
    if C.TEMPLATE and C.TEMPLATE.exists():
        try:
            from pptx import Presentation
            prs = Presentation(str(C.TEMPLATE))
            ratio = prs.slide_width / prs.slide_height
            check_essential(abs(ratio - 16 / 9) < 0.02, "template is 16:9",
                            f"{prs.slide_width / 914400:.2f} x {prs.slide_height / 914400:.2f} in, "
                            f"{len(prs.slide_layouts)} layouts",
                            "the pipeline maps a 1280x720 canvas onto a 13.33 x 7.5 in slide; use a 16:9 template")
        except Exception as e:  # noqa: BLE001
            check_essential(False, "template opens", str(e)[:80], "the template file is not a valid .pptx")

    # --- font ---
    if C.IS_SYSTEM_FONT:
        check_optional(system_font_present(C.FONT_NAME), f"font '{C.FONT_NAME}' installed",
                       "system font" if system_font_present(C.FONT_NAME) else "no font file found by that name",
                       f"install {C.FONT_NAME}, or change font.name in house.json")
    elif C.FONT_DIR:
        missing = [f for f in C.FONT_FACES.values() if not (C.FONT_DIR / f).exists()]
        check_essential(not missing, f"font '{C.FONT_NAME}' files",
                        f"{C.FONT_DIR}" + (f"  missing: {missing}" if missing else f"  all {len(C.FONT_FACES)} faces"),
                        "install the font files for the current user")
        installed = faces_installed_for_user()
        check_optional(installed, f"font '{C.FONT_NAME}' installed for user",
                       "installed" if installed else "bundled only - run setup.py",
                       "run: python scripts/setup.py  (installs the bundled faces for your user; "
                       "PowerPoint substitutes another font until then)")
    else:
        check_essential(False, f"font '{C.FONT_NAME}' files", "not found",
                        "install the brand font for the current user, or set DECK_STUDIO_FONTDIR to the folder "
                        "holding the files named in house.json")

    # --- bundled fonts (skill-shipped fonts/ folder) ---
    fonts_dir = C.SKILL_ROOT / "fonts"
    bundled = [p for p in fonts_dir.glob("*") if p.suffix.lower() in (".otf", ".ttf", ".ttc")] \
        if fonts_dir.exists() else []
    if not C.IS_SYSTEM_FONT:
        check_optional(bool(bundled), "bundled fonts",
                       f"{len(bundled)} faces in fonts/" if bundled else "fonts/ is missing or empty",
                       "add the brand font faces to fonts/ at the skill root")

    # --- browser for rendering / extraction ---
    named_browser = _browser_paths()
    bundled_chromium = _bundled_chromium_present()
    check_essential(bool(named_browser or bundled_chromium), "headless browser (Edge/Chrome)",
                    str(named_browser) if named_browser
                    else ("bundled Playwright Chromium" if bundled_chromium else "not found"),
                    "install Microsoft Edge or Chrome, or run: python -m playwright install chromium")

    # --- slide renderer (render_slides.py's dispatch target for the render-back QA gate) ---
    system = platform.system()
    ppt = False
    if system == "Windows":
        try:
            # HKCR merges machine and per-user registrations (Click-to-Run Office registers per user);
            # direct and instant, unlike a PowerShell start on a machine with slow endpoint scanning.
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CLSID"))
            ppt = True
        except OSError:
            ppt = False
        if not ppt:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "if (Get-ItemProperty HKLM:\\SOFTWARE\\Classes\\PowerPoint.Application "
                     "-ErrorAction SilentlyContinue) {'yes'} else {'no'}"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
                ppt = "yes" in (r.stdout or "").lower()
            except Exception:
                ppt = False
        if ppt:
            renderer_ok, renderer_label = True, "PowerPoint COM"
        else:
            renderer_ok, renderer_label = False, "not found"
        renderer_fix = "install desktop PowerPoint (no LibreOffice fallback is configured on Windows)"
    elif system == "Darwin":
        if Path("/Applications/Microsoft PowerPoint.app").exists():
            renderer_ok, renderer_label = True, "PowerPoint for Mac (AppleScript)"
        elif shutil.which("soffice") or Path("/Applications/LibreOffice.app").exists():
            renderer_ok, renderer_label = True, "LibreOffice (approximate)"
        else:
            renderer_ok, renderer_label = False, "not found"
        renderer_fix = "install PowerPoint for Mac, or LibreOffice (https://www.libreoffice.org)"
    else:
        if shutil.which("soffice") or shutil.which("libreoffice"):
            renderer_ok, renderer_label = True, "LibreOffice (approximate)"
        else:
            renderer_ok, renderer_label = False, "not found"
        renderer_fix = "install LibreOffice, e.g. apt install libreoffice"
    check_essential(renderer_ok, "slide renderer", renderer_label, renderer_fix)

    # --- corpus present ---
    refs = sorted((C.SKILL_ROOT / "reference").glob("T*_*.png"))
    check_optional(len(refs) >= 2, "reference corpus",
                   f"{len(refs)} tiered exhibits",
                   "the reference/ folder is thin - add your own house exhibits per reference/MANIFEST.md")

    print("-" * 78)
    if problems:
        print(f"\n{len(problems)} blocking problem(s):")
        for label, fix in problems:
            print(f"  - {label}\n      fix: {fix}")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for label, fix in warnings:
            print(f"  - {label}\n      {fix}")
    if not problems and not warnings:
        print("\nAll good - you can build decks on this machine.\n")
    elif not problems:
        print("\nUsable, with the warnings above.\n")
    else:
        print()
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
