"""Export every slide of a .pptx to PNG, one slideNN.png per slide, for the render-QA loop.

Usage: python scripts/render_slides.py <deck.pptx> <out_dir> [--width N]   (default N=1920)

Dispatches by platform:
  Windows - PowerPoint COM (pywin32, falling back to comtypes) if importable, else shells
            out to the existing render_slides.ps1 so nothing regresses. Always renders a
            TEMP COPY - a deck you have open is never touched - and only quits a PowerPoint
            instance this script itself started.
  macOS   - PowerPoint for Mac via AppleScript (osascript) if installed, else LibreOffice.
  Linux   - LibreOffice.

LibreOffice path: `soffice --headless --convert-to pdf`, then PDF -> PNG via pypdfium2 (an
optional dependency - see requirements.txt; falls back to `pdftoppm` if that is on PATH but
pypdfium2 is not). Prints "approximate render: fonts and spacing may differ from PowerPoint"
since LibreOffice does not use the real Office rendering engine.

Exits 1 with a clear message if no renderer is available on this machine.
"""
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _cli  # noqa: E402 - shared --help / arg-count handling

DEFAULT_WIDTH = 1920


def _opt_width(argv):
    """Pull --width N out of argv (in place) before _cli.usage counts positionals."""
    if "--width" in argv:
        i = argv.index("--width")
        w = int(argv[i + 1])
        del argv[i:i + 2]
        return w
    return DEFAULT_WIDTH


def _clear_old(out_dir):
    for old in out_dir.glob("slide*.png"):
        old.unlink()


# ---------------------------------------------------------------- Windows: PowerPoint COM
def _render_windows_com_pywin32(pptx_path, out_dir, width):
    import win32com.client

    tmp = Path(tempfile.gettempdir()) / f"deck_studio_render_{uuid.uuid4().hex}.pptx"
    shutil.copyfile(pptx_path, tmp)
    try:
        win32com.client.GetActiveObject("PowerPoint.Application")
        pre_running = True
    except Exception:
        pre_running = False

    ppt = win32com.client.Dispatch("PowerPoint.Application")
    count = 0
    try:
        # Open(FileName, ReadOnly, Untitled, WithWindow): msoTrue=-1, msoFalse=0 (no window)
        pres = ppt.Presentations.Open(str(tmp), -1, 0, 0)
        try:
            height = int(width * pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth)
            for slide in pres.Slides:
                count += 1
                slide.Export(str(out_dir / f"slide{count:02d}.png"), "PNG", width, height)
        finally:
            pres.Close()
    finally:
        if not pre_running:
            try:
                ppt.Quit()
            except Exception:
                pass
        tmp.unlink(missing_ok=True)
    return count, "PowerPoint COM (pywin32)"


def _render_windows_com_comtypes(pptx_path, out_dir, width):
    import comtypes.client

    tmp = Path(tempfile.gettempdir()) / f"deck_studio_render_{uuid.uuid4().hex}.pptx"
    shutil.copyfile(pptx_path, tmp)
    try:
        comtypes.client.GetActiveObject("PowerPoint.Application")
        pre_running = True
    except Exception:
        pre_running = False

    ppt = comtypes.client.CreateObject("PowerPoint.Application")
    count = 0
    try:
        pres = ppt.Presentations.Open(str(tmp), -1, 0, 0)
        try:
            height = int(width * pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth)
            for i in range(1, pres.Slides.Count + 1):
                count += 1
                pres.Slides.Item(i).Export(str(out_dir / f"slide{count:02d}.png"), "PNG", width, height)
        finally:
            pres.Close()
    finally:
        if not pre_running:
            try:
                ppt.Quit()
            except Exception:
                pass
        tmp.unlink(missing_ok=True)
    return count, "PowerPoint COM (comtypes)"


def _render_windows_ps1_fallback(pptx_path, out_dir, width):
    ps1 = HERE / "render_slides.ps1"
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
                        "-PptxPath", str(pptx_path), "-OutDir", str(out_dir), "-Width", str(width)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        if r.stderr:
            print(r.stderr, file=sys.stderr)
        return None, "PowerPoint COM (render_slides.ps1)"
    count = len(list(out_dir.glob("slide*.png")))
    return count, "PowerPoint COM (render_slides.ps1)"


def _windows(pptx_path, out_dir, width):
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        pass
    else:
        try:
            return _render_windows_com_pywin32(pptx_path, out_dir, width)
        except Exception as e:
            print(f"PowerPoint COM (pywin32) failed: {e}", file=sys.stderr)

    try:
        import comtypes.client  # noqa: F401
    except ImportError:
        pass
    else:
        try:
            return _render_windows_com_comtypes(pptx_path, out_dir, width)
        except Exception as e:
            print(f"PowerPoint COM (comtypes) failed: {e}", file=sys.stderr)

    return _render_windows_ps1_fallback(pptx_path, out_dir, width)


# ---------------------------------------------------------------- macOS: PowerPoint / LibreOffice
def _render_macos_applescript(pptx_path, out_dir):
    """UNTESTED on real macOS - see the WP5 report for the assumptions this makes."""
    work = Path(tempfile.mkdtemp(prefix="deck_studio_render_"))
    tmp = work / pptx_path.name
    shutil.copyfile(pptx_path, tmp)
    export_dir = work / "export"
    export_dir.mkdir()

    script = (
        'tell application "Microsoft PowerPoint"\n'
        '  set wasRunning to running\n'
        f'  open POSIX file "{tmp}"\n'
        '  set thePres to active presentation\n'
        f'  save thePres in POSIX file "{export_dir}" as save as PNG\n'
        '  close thePres saving no\n'
        '  if not wasRunning then quit\n'
        'end tell\n'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        if r.stderr:
            print(r.stderr, file=sys.stderr)
        shutil.rmtree(work, ignore_errors=True)
        return None, "PowerPoint for Mac (AppleScript)"

    exported = sorted(export_dir.glob("*.PNG")) + sorted(export_dir.glob("*.png"))
    count = 0
    for i, p in enumerate(exported, start=1):
        count += 1
        shutil.copyfile(p, out_dir / f"slide{count:02d}.png")
    shutil.rmtree(work, ignore_errors=True)
    return count, "PowerPoint for Mac (AppleScript)"


def _macos(pptx_path, out_dir, width):
    if Path("/Applications/Microsoft PowerPoint.app").exists():
        count, how = _render_macos_applescript(pptx_path, out_dir)
        if count:
            return count, how
        print(f"{how} failed - falling back to LibreOffice", file=sys.stderr)
    return _libreoffice(pptx_path, out_dir, width)


# ---------------------------------------------------------------- Linux + shared LibreOffice path
def _find_soffice():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for c in (Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
              Path("/usr/bin/soffice"), Path("/usr/local/bin/soffice"),
              Path("/opt/libreoffice/program/soffice")):
        if c.exists():
            return str(c)
    return None


def _pdf_to_png(pdf_path, out_dir, width):
    try:
        import pypdfium2 as pdfium
        import PIL  # noqa: F401  - pypdfium2's to_pil() needs pillow; both are optional, LibreOffice path only
    except ImportError:
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            print("FAILED: no PDF -> PNG converter available")
            print("  fix: pip install pypdfium2 pillow   (or install poppler so pdftoppm is on PATH)")
            sys.exit(1)
        prefix = out_dir / "slide"
        subprocess.run([pdftoppm, "-png", "-r", "150", str(pdf_path), str(prefix)], check=True)
        made = sorted(out_dir.glob("slide-*.png"))
        for i, p in enumerate(made, start=1):
            p.rename(out_dir / f"slide{i:02d}.png")
        return len(made)

    doc = pdfium.PdfDocument(str(pdf_path))
    count = 0
    for i, page in enumerate(doc, start=1):
        pw = page.get_size()[0]     # PDF points (72/in)
        scale = width / pw if pw else 2.0
        bitmap = page.render(scale=scale)
        bitmap.to_pil().save(out_dir / f"slide{i:02d}.png")
        count += 1
    return count


def _libreoffice(pptx_path, out_dir, width):
    soffice = _find_soffice()
    if not soffice:
        return None, None

    work = Path(tempfile.mkdtemp(prefix="deck_studio_render_"))
    try:
        r = subprocess.run([soffice, "--headless", "--norestore", "--convert-to", "pdf",
                            "--outdir", str(work), str(pptx_path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        if r.returncode != 0:
            print((r.stdout or "") + (r.stderr or ""), file=sys.stderr)
            return None, "LibreOffice"
        pdf = work / (pptx_path.stem + ".pdf")
        if not pdf.exists():
            print(f"LibreOffice did not produce {pdf}", file=sys.stderr)
            return None, "LibreOffice"
        count = _pdf_to_png(pdf, out_dir, width)
        return count, "LibreOffice (approximate)"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _linux(pptx_path, out_dir, width):
    return _libreoffice(pptx_path, out_dir, width)


def main():
    argv = sys.argv[1:]
    width = _opt_width(argv)
    _cli.usage(__doc__, argv, 2, 2)
    pptx_path = Path(argv[0]).resolve()
    out_dir = Path(argv[1]).resolve()
    if not pptx_path.exists():
        print(f"FAILED: not found: {pptx_path}")
        sys.exit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_old(out_dir)

    system = platform.system()
    if system == "Windows":
        count, how = _windows(pptx_path, out_dir, width)
    elif system == "Darwin":
        count, how = _macos(pptx_path, out_dir, width)
    else:
        count, how = _linux(pptx_path, out_dir, width)

    if not count:
        print("FAILED: no slide renderer available on this machine")
        if system == "Windows":
            print("  fix: install desktop PowerPoint (no LibreOffice fallback is configured on Windows)")
        elif system == "Darwin":
            print("  fix: install PowerPoint for Mac, or LibreOffice (https://www.libreoffice.org)")
        else:
            print("  fix: install LibreOffice, e.g. apt install libreoffice")
        sys.exit(1)

    print(f"Exported {count} slides to {out_dir} via {how}")
    if "approximate" in how.lower():
        print("approximate render: fonts and spacing may differ from PowerPoint")


if __name__ == "__main__":
    main()
