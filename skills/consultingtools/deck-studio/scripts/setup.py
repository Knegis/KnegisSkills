"""Set up this machine to build decks with the deck-studio skill. The one command a
user's agent runs after unzipping the skill anywhere.

Usage: python scripts/setup.py [--no-fonts] [--no-copy] [--quick]

Idempotent - safe to re-run; each step is skipped if it is already satisfied. Prints one
line per step (OK/SKIP/FAIL) and a final PASS/FAIL line, and writes setup_report.txt next
to this script with the same output plus platform details.

  --no-fonts   don't install bundled font faces (only relevant if fonts/ holds a brand font)
  --no-copy    don't place this folder under ~/.claude/skills/
  --quick      skip the smoke-build step (typecheck + build + fontcheck + render one exhibit)

Never requires admin/root rights - fonts are installed per-user (HKCU on Windows, the
user's own Fonts folder on macOS/Linux), never machine-wide.
"""
import hashlib
import importlib.metadata
import importlib.util
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import _cli  # noqa: E402 - shared --help / arg-count handling
import config as C  # noqa: E402

FACE_LABELS = {"regular": "Regular", "bold": "Bold", "italic": "Regular Italic", "bolditalic": "Bold Italic"}

LINES = []   # every line printed, mirrored into setup_report.txt


def out(msg=""):
    print(msg)
    LINES.append(msg)


def step(label, ok, detail="", fail=False):
    tag = "FAIL" if fail else ("OK" if ok else "SKIP")
    out(f"[{tag:<4}] {label:<38} {detail}")
    return ok


# --------------------------------------------------------------------- (a)/(b) python + deps
def _check_python():
    v = sys.version_info
    ok = v >= (3, 9)
    step("Python >= 3.9", ok, f"{v.major}.{v.minor}.{v.micro}", fail=not ok)
    return ok


def _pinned_versions():
    """{distribution: version} for every `name==version` line in requirements.txt."""
    pins = {}
    for line in (SKILL_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, _, ver = line.partition("==")
            pins[name.strip()] = ver.strip()
    return pins


def _install_deps():
    # Importability is not enough: a pinned dependency that is present at the WRONG version must
    # still be installed, or the pin silently does nothing on exactly the machines it protects.
    need = [("pptx", "python-pptx"), ("playwright", "playwright")]
    pins = _pinned_versions()
    missing, wrong = [], []
    for mod, dist in need:
        if importlib.util.find_spec(mod) is None:
            missing.append(dist)
            continue
        want = pins.get(dist)
        if not want:
            continue
        try:
            have = importlib.metadata.version(dist)
        except Exception:
            have = None
        if have and have != want:
            wrong.append("%s %s (pinned %s)" % (dist, have, want))
    if not missing and not wrong:
        return step("python dependencies", True, "already correct (python-pptx, playwright)")
    why = ", ".join(["missing: " + ", ".join(missing)] if missing else []
                    + (["version mismatch: " + "; ".join(wrong)] if wrong else []))
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(SKILL_ROOT / "requirements.txt")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    return step("pip install -r requirements.txt (%s)" % why, ok,
                "" if ok else (r.stderr or r.stdout)[-300:], fail=not ok)


# --------------------------------------------------------------------- (c) browser
def _have_named_browser():
    system = platform.system()
    if system == "Windows":
        return any(Path(p).exists() for p in [
            r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            r"C:/Program Files/Microsoft/Edge/Application/msedge.exe"]) \
            or bool(shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium"))
    elif system == "Darwin":
        return Path("/Applications/Microsoft Edge.app").exists() \
            or Path("/Applications/Google Chrome.app").exists() \
            or bool(shutil.which("chromium"))
    else:
        return bool(shutil.which("msedge") or shutil.which("google-chrome") or shutil.which("chromium"))


def _install_browser():
    if _have_named_browser():
        return step("browser (Edge/Chrome)", True, "found on system")
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    return step("playwright install chromium", ok, "" if ok else (r.stderr or r.stdout)[-300:], fail=not ok)


# --------------------------------------------------------------------- (d) fonts
def _user_font_dir():
    system = platform.system()
    if system == "Windows":
        return C.HOME / "AppData/Local/Microsoft/Windows/Fonts"
    elif system == "Darwin":
        return C.HOME / "Library/Fonts"
    else:
        return C.HOME / ".local/share/fonts"


def _faces_present(d):
    if not d.exists():
        return False
    names = {Path(f).stem.lower() for f in C.FONT_FACES.values()}
    found = {p.stem.lower() for p in d.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc")}
    return names <= found


def _register_windows_fonts(faces, dest):
    """HKCU (per-user, no admin needed), matching how Windows itself registers a face
    a user installs via right-click 'Install'."""
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
                          0, winreg.KEY_SET_VALUE)
    try:
        for face_key, filename in faces.items():
            label = FACE_LABELS.get(face_key, face_key.title())
            winreg.SetValueEx(key, f"{C.FONT_NAME} {label} (TrueType)", 0, winreg.REG_SZ, str(dest / filename))
    finally:
        winreg.CloseKey(key)


def _install_fonts(no_fonts):
    if no_fonts:
        return step("install fonts", True, "skipped (--no-fonts)")
    if C.IS_SYSTEM_FONT:
        return step("install fonts", True, f"'{C.FONT_NAME}' is a system font - nothing to install")

    src_dir = SKILL_ROOT / "fonts"
    missing_src = [f for f in C.FONT_FACES.values() if not (src_dir / f).exists()]
    if missing_src:
        return step("install fonts", False, f"bundled files missing from fonts/: {missing_src}", fail=True)

    dest = _user_font_dir()
    if _faces_present(dest):
        return step("install fonts", True, f"'{C.FONT_NAME}' already installed for user - {dest}")

    dest.mkdir(parents=True, exist_ok=True)
    for filename in C.FONT_FACES.values():
        shutil.copyfile(src_dir / filename, dest / filename)

    system = platform.system()
    if system == "Windows":
        try:
            _register_windows_fonts(C.FONT_FACES, dest)
        except Exception as e:
            return step("install fonts", False, f"copied but registry write failed: {e}", fail=True)
    elif system == "Linux":
        try:
            subprocess.run(["fc-cache", "-f", str(dest)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        except Exception:
            pass   # fc-cache is a nicety; the files are already in the right place either way
    return step("install fonts", True, f"installed {len(C.FONT_FACES)} face(s) to {dest}")


# --------------------------------------------------------------------- (e) place the skill
def _dir_signature(path):
    """Cheap 'is this the same skill content' signature - avoids hashing template/font/media
    binaries just to decide whether to skip a copy."""
    sig = hashlib.sha256()
    for rel in ("SKILL.md", "house.json"):
        p = path / rel
        if p.exists():
            sig.update(p.read_bytes())
    return sig.hexdigest()


def _place_skill(no_copy):
    label = "place skill under ~/.claude/skills/"
    if no_copy:
        return step(label, True, "skipped (--no-copy)")

    skills_root = Path.home() / ".claude" / "skills"
    try:
        SKILL_ROOT.relative_to(skills_root)
        return step(label, True, f"already there ({SKILL_ROOT})")
    except ValueError:
        pass

    target = skills_root / "deck-studio"
    if not target.exists():
        shutil.copytree(SKILL_ROOT, target, ignore=shutil.ignore_patterns("__pycache__", "setup_report.txt"))
        return step(label, True, f"copied to {target}")

    if _dir_signature(target) == _dir_signature(SKILL_ROOT):
        return step(label, True, f"{target} already has this content")

    return step(label, False,
                f"{target} exists with DIFFERENT content - not overwritten. Move it aside, or install "
                f"under a different name: cp -r \"{SKILL_ROOT}\" \"{skills_root / 'deck-studio-2'}\"")


# --------------------------------------------------------------------- (f) doctor
def _run_doctor():
    out("-" * 78)
    out("doctor.py:")
    r = subprocess.run([sys.executable, str(HERE / "doctor.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    for ln in (r.stdout + r.stderr).splitlines():
        out("  " + ln)
    ok = r.returncode == 0
    return step("doctor.py", ok, "" if ok else "reported blocking problem(s) above", fail=not ok)


# --------------------------------------------------------------------- (g) smoke build
def _have_any_renderer():
    system = platform.system()
    if system == "Windows":
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "if (Get-ItemProperty HKLM:\\SOFTWARE\\Classes\\PowerPoint.Application "
                 "-ErrorAction SilentlyContinue) {'yes'} else {'no'}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
            return "yes" in (r.stdout or "").lower()
        except Exception:
            return False
    elif system == "Darwin":
        return Path("/Applications/Microsoft PowerPoint.app").exists() or bool(shutil.which("soffice"))
    else:
        return bool(shutil.which("soffice") or shutil.which("libreoffice"))


def _smoke_build():
    corpus = sorted((SKILL_ROOT / "reference").glob("T*_*.html"))
    if not corpus:
        return step("smoke build", False, "no reference/*.html exhibits found", fail=True)
    exhibit = corpus[0]

    with tempfile.TemporaryDirectory(prefix="deck_studio_smoke_") as td:
        td = Path(td)
        deck = td / "smoke.pptx"

        r = subprocess.run([sys.executable, str(HERE / "typecheck.py"), str(exhibit), "--quiet"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return step("smoke build", False, f"typecheck failed on {exhibit.name}: {r.stdout[-300:]}", fail=True)

        r = subprocess.run([sys.executable, str(HERE / "build_deck.py"), str(deck), str(exhibit)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not deck.exists():
            return step("smoke build", False, f"build_deck failed: {(r.stdout + r.stderr)[-300:]}", fail=True)

        r = subprocess.run([sys.executable, str(HERE / "fontcheck.py"), str(deck)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return step("smoke build", False, f"fontcheck failed: {r.stdout[-300:]}", fail=True)

        if _have_any_renderer():
            png_dir = td / "png"
            r = subprocess.run([sys.executable, str(HERE / "render_slides.py"), str(deck), str(png_dir)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                return step("smoke build", False, f"render_slides failed: {(r.stdout + r.stderr)[-300:]}", fail=True)
            render_note = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "rendered"
        else:
            render_note = "no renderer available - render step skipped"

    return step("smoke build", True,
                 f"{exhibit.name} -> typecheck PASS, built, fontcheck CLEAN, {render_note}")


def main():
    argv = sys.argv[1:]
    no_fonts = "--no-fonts" in argv
    no_copy = "--no-copy" in argv
    quick = "--quick" in argv
    argv = [a for a in argv if a not in ("--no-fonts", "--no-copy", "--quick")]
    _cli.usage(__doc__, argv, 0, 0)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    out(f"deck-studio setup  v{C.VERSION}   ({platform.system()} {platform.release()}, "
        f"Python {sys.version.split()[0]})")
    out(f"skill root: {SKILL_ROOT}")
    out("-" * 78)

    failed = False
    failed |= not _check_python()
    failed |= not _install_deps()
    failed |= not _install_browser()
    failed |= not _install_fonts(no_fonts)
    _place_skill(no_copy)              # never fails the run - it only ever SKIPs with instructions
    failed |= not _run_doctor()
    if quick:
        step("smoke build", True, "skipped (--quick)")
    else:
        failed |= not _smoke_build()

    out("-" * 78)
    report_path = HERE / "setup_report.txt"
    report_path.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    out(f"\n{'FAIL' if failed else 'PASS'}  -  report written to {report_path}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
