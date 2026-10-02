"""Render an HTML slide to PNG via a headless browser, at 2x device scale.

Usage: python scripts/render_html.py <slide.html> <out.png>

Use this in the design/self-critique loop BEFORE extracting geometry: you cannot see a
browser, so this PNG is how you look at your own work. Renders the 1280x720 slide canvas
at device scale factor 2 (2560x1440 PNG). Cross-platform (Windows/macOS/Linux) via Playwright.

Browser selection order: installed Microsoft Edge, then installed Google Chrome, then the
Playwright-bundled Chromium. Each launch gets its own fresh, isolated profile (Playwright
manages this automatically per launched instance) - a shared profile intermittently lands
on a first-run / privacy interstitial and screenshots that instead of the slide, which looks
like a broken slide and wastes a debugging cycle. If no browser can be launched at all, exits
1 with the one-line fix:  python -m playwright install chromium

Also strips a UTF-8 BOM from the source HTML, which otherwise leaks a stray glyph into the
rendered page.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli  # noqa: E402 - shared --help / arg-count handling

from playwright.sync_api import sync_playwright  # noqa: E402

TIMEOUT_MS = 90_000


def _strip_bom(path):
    b = path.read_bytes()
    if b[:3] == b"\xef\xbb\xbf":
        path.write_bytes(b[3:])
        print(f"stripped BOM from {path}")


def _launch(p):
    """Try Edge, then Chrome, then the Playwright-bundled Chromium. Returns (browser, label)."""
    for channel, label in (("msedge", "Microsoft Edge"), ("chrome", "Google Chrome")):
        try:
            return p.chromium.launch(channel=channel), label
        except Exception:
            continue
    try:
        return p.chromium.launch(), "bundled Chromium"
    except Exception as e:
        print("FAILED: no usable browser found (tried Edge, Chrome, bundled Chromium)")
        print("  fix: python -m playwright install chromium")
        print(f"  ({e})")
        sys.exit(1)


def main():
    _cli.usage(__doc__, sys.argv[1:], 2, 2)
    src = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()   # so a stale PNG can't look like success

    if src.suffix.lower() == ".html":
        _strip_bom(src)

    with sync_playwright() as p:
        browser, how = _launch(p)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=2)
            # headless browsers occasionally hang on a slow local asset - don't wait forever
            page.goto(src.as_uri(), wait_until="networkidle", timeout=TIMEOUT_MS)
            # .ppt-chart boxes are empty in a browser; paint the preview so this PNG shows the
            # chart rather than a blank rectangle. Preview only - see chart_preview.js.
            shim = Path(__file__).resolve().parent / "chart_preview.js"
            if shim.exists():
                page.add_script_tag(path=str(shim))
            page.wait_for_timeout(300)
            page.screenshot(path=str(out), timeout=TIMEOUT_MS)
        finally:
            browser.close()

    if out.exists():
        kb = out.stat().st_size / 1024
        note = "" if kb >= 20 else " - SUSPICIOUS: too small to be a real slide, open and check it"
        print(f"rendered {out} via {how} ({kb:.0f} KB){note}")
    else:
        print(f"FAILED to render {out}")
        sys.exit(1)


if __name__ == "__main__":
    main()
