"""Extract an HTML slide into rects + rich text boxes for PPT translation.

Usage: python extract_geometry.py <input.html> <output.json>

Loads the file in a 1280x720 viewport (system Edge via Playwright) and emits:
  rects:  every element with a fill / gradient / border  -> becomes a PPT shape
  texts:  every element with direct text -> becomes ONE PPT text box, with inline
          emphasis (<b>, coloured <span>) folded into runs and block children
          split into paragraphs. Inline children are marked consumed so they are
          not double-emitted.
All geometry in CSS px against a 1280x720 canvas (px * 9525 = EMU).
"""
import sys, json, hashlib, platform
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli                                 # noqa: E402 - shared --help / arg-count handling
import config as _cfg

# Chrome the template master already provides (a logo, a page number) must not be translated
# twice. When house.json says template_supplies_chrome, the .wordmark / .pg elements are kept
# in the HTML preview but skipped in translation; otherwise they become ordinary text boxes.
CHROME_SELECTOR = ".ppt-skip, .wordmark, .pg" if _cfg.TEMPLATE_SUPPLIES_CHROME else ".ppt-skip"

JS = r"""
async () => {
  const all = Array.from(document.querySelectorAll('body *'));
  const zOf = new Map();
  all.forEach((el, i) => zOf.set(el, i));
  const rects = [], texts = [], images = [], charts = [], warnings = [];
  const consumed = new Set();
  const directText = (el) => Array.from(el.childNodes).some(n => n.nodeType===3 && n.textContent.trim());

  // ---- selector label for a warning: "<tag.class#id>" ----
  const selOf = (el) => {
    let s = el.tagName.toLowerCase();
    if (typeof el.className === 'string' && el.className.trim()) {
      s += '.' + el.className.trim().split(/\s+/).join('.');
    }
    if (el.id) s += '#' + el.id;
    return s;
  };
  const addWarn = (el, why, fix) => {
    warnings.push({ sel: selOf(el), text: (el.textContent || '').trim().slice(0, 40), why, fix });
  };

  // ---- native-chart regions: a .ppt-chart element becomes a real PPT chart;
  //      its box + data attributes are captured, and it + its subtree are skipped from rects/texts.
  const chartEls = Array.from(document.querySelectorAll('.ppt-chart'));
  const chartSet = new Set(chartEls);
  const inChart = (el) => { let n = el; while (n) { if (chartSet.has(n)) return true; n = n.parentElement; } return false; };

  // ---- elements to leave out of translation: anything marked .ppt-skip, plus (only when the
  //      template master already draws them) the .wordmark / .pg chrome. See CHROME_SELECTOR.
  const skipSet = new Set(Array.from(document.querySelectorAll('__CHROME_SELECTOR__')));
  const inSkip = (el) => { let n = el; while (n) { if (skipSet.has(n)) return true; n = n.parentElement; } return false; };

  // ---- warnings: things the translator cannot reproduce, flagged so the author sees them
  //      before they only show up as a surprise in the rendered PowerPoint. ----
  for (const el of all) {
    if (inChart(el) || inSkip(el)) continue;
    const cs = getComputedStyle(el);

    if (cs.transform && cs.transform !== 'none') {
      addWarn(el, 'CSS transform (rotation/skew) - not reproduced in PPT',
              'bake the transform into static geometry, or drop it');
    }

    for (const pseudo of ['::before', '::after']) {
      const pcs = getComputedStyle(el, pseudo);
      const content = pcs.content;
      if (content && content !== 'none' && content !== 'normal' && content !== '""' && content !== "''") {
        addWarn(el, `${pseudo} pseudo-element with content - dropped in translation`,
                'use a real sibling <div> instead (see PIPELINE.md)');
      }
    }

    if (el.tagName === 'DIV') {
      const bw = { t: parseFloat(cs.borderTopWidth)||0, l: parseFloat(cs.borderLeftWidth)||0,
                   r: parseFloat(cs.borderRightWidth)||0, b: parseFloat(cs.borderBottomWidth)||0 };
      const bs = { t: cs.borderTopStyle, l: cs.borderLeftStyle, r: cs.borderRightStyle, b: cs.borderBottomStyle };
      const anyVisible = Object.keys(bw).some(k => bw[k] > 0 && bs[k] !== 'none');
      if (anyVisible) {
        const r = el.getBoundingClientRect();
        const maxW = Math.max(bw.t, bw.l, bw.r, bw.b);
        // a thin (<=2px) hairline div with no text of its own, smaller than 4px in both
        // dimensions, IS the intended construction (a rule) - don't warn on that.
        const isIntendedHairline = maxW <= 2 && !directText(el) && r.width <= 4 && r.height <= 4;
        if (!isIntendedHairline) {
          addWarn(el, 'visible CSS border on a div - only a hairline rule is auto-handled',
                  'confirm the translator reproduces this border, or convert it to a filled rect');
        }
      }
    }

    if (el.tagName === 'TABLE') {
      addWarn(el, '<table> element - not translated to PPT',
              'rebuild the grid with positioned divs (see PIPELINE.md)');
    }

    const ls = parseFloat(cs.letterSpacing) || 0;
    if (ls !== 0 && directText(el)) {
      addWarn(el, `non-zero letter-spacing (${cs.letterSpacing}) - house style is normal tracking`,
              'remove letter-spacing');
    }

    if (directText(el) && cs.display.includes('flex') && cs.justifyContent === 'center' && cs.textAlign !== 'center') {
      addWarn(el, 'display:flex + justify-content:center but text-align is not center - PPT centres ' +
              'text by text-align, not flex', 'set text-align:center to match the visual centring');
    }

    if (directText(el)) {
      for (const child of el.children) {
        if (child.tagName === 'SPAN') {
          const ccs = getComputedStyle(child);
          const bg = ccs.backgroundColor;
          if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
            addWarn(child, 'inline <span> with its own background colour inside text - not ' +
                    'reproduced as a swatch', 'pull the swatch out as a sibling rect, or drop the background');
          }
        }
      }
    }
  }
  for (const el of document.querySelectorAll('svg')) {
    if (inChart(el) || inSkip(el)) continue;
    addWarn(el, 'inline <svg> - dropped entirely in translation',
            'rebuild with divs, or rasterise to <img> (see PIPELINE.md)');
  }

  for (const el of chartEls) {
    const r = el.getBoundingClientRect();
    let series = [], highlight = null;
    try { series = JSON.parse(el.dataset.series || '[]'); } catch (e) {}
    try { highlight = el.dataset.highlight ? JSON.parse(el.dataset.highlight) : null; } catch (e) {}
    charts.push({ x:r.x, y:r.y, w:r.width, h:r.height,
      type: el.dataset.chart || 'stacked-column',
      categories: (el.dataset.categories || '').split('|').filter(s => s.length),
      series, highlight,
      legend: el.dataset.legend || 'top',
      valueaxis: el.dataset.valueaxis || 'show',
      cataxis: el.dataset.cataxis || 'show',
      gridlines: el.dataset.gridlines || '',
      valuemax: el.dataset.valuemax || '',
      catlabelsize: el.dataset.catlabelsize || '',
      catlabelRotation: el.dataset.catlabelRotation || '',
      catlabelbold: el.dataset.catlabelbold === 'true' });
  }

  const runStyle = (cs) => ({
    size: parseFloat(cs.fontSize),
    weight: (parseInt(cs.fontWeight) || (cs.fontWeight==='bold'?700:400)),
    color: cs.color, italic: cs.fontStyle==='italic',
    upper: cs.textTransform==='uppercase', ls: parseFloat(cs.letterSpacing)||0
  });

  // ---- paragraph groups: a .pgroup element -> ONE text box, whose direct-text
  //      block descendants each become a PARAGRAPH. Vertical gaps are measured
  //      from the rendered layout and emitted as paragraph space-before (pt),
  //      so PPT recreates the exact spacing without stacked text boxes.
  const pgEls = Array.from(document.querySelectorAll('.pgroup'));
  for (const g of pgEls) {
    if (inSkip(g)) continue;
    const gr = g.getBoundingClientRect();
    const gcs = getComputedStyle(g);
    // Only block-level descendants become paragraphs; inline emphasis (<b>/<span>/<a>)
    // is folded into the parent block's runs below, so excluding inline here prevents
    // duplicate standalone paragraphs for every emphasised word.
    // A block whose text sits only in inline children (<div><b>Heading</b></div>) is a
    // paragraph too - requiring direct text dropped it entirely (neither it nor the inline
    // <b> qualified). A block child that is its own paragraph is skipped as a run below,
    // so its text is not emitted twice.
    const isInl = (el) => getComputedStyle(el).display.startsWith('inline');
    const ownText = (el) => directText(el) ||
      Array.from(el.children).some(c => isInl(c) && c.textContent.trim());
    const blocks = Array.from(g.querySelectorAll('*')).filter(el => ownText(el) && !isInl(el));
    const blockSet = new Set(blocks);
    const gparas = [];
    let prevBottom = null;
    for (const el of blocks) {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const base = runStyle(cs);
      const runs = [];
      for (const n of el.childNodes) {
        if (n.nodeType === 3) { const t = n.textContent.replace(/\s+/g,' '); if (t.trim()) runs.push(Object.assign({t}, base)); }
        else if (n.nodeType === 1) {
          if (n.tagName === 'BR') { runs.push(Object.assign({t:' '}, base)); continue; }
          if (blockSet.has(n)) continue;   // its own paragraph
          const txt = n.textContent.replace(/\s+/g,' ').trim(); if (!txt) continue;
          runs.push(Object.assign({t:txt}, runStyle(getComputedStyle(n))));
        }
      }
      if (!runs.length) continue;
      const spcBef = (prevBottom === null) ? 0 : Math.max(0, r.top - prevBottom);
      prevBottom = r.bottom;
      const fs = parseFloat(cs.fontSize) || 12;
      const lh = parseFloat(cs.lineHeight) || fs * 1.2;
      gparas.push({ runs, align: cs.textAlign, spcBef, lhpct: Math.round(lh / fs * 100000), lhpx: lh });
    }
    if (!gparas.length) continue;
    texts.push({ x:gr.x, y:gr.y, w:gr.width, h:gr.height, align:gcs.textAlign, anchor:'t',
      pl:parseFloat(gcs.paddingLeft)||0, pr:parseFloat(gcs.paddingRight)||0,
      pt:parseFloat(gcs.paddingTop)||0, pb:parseFloat(gcs.paddingBottom)||0,
      grouped:true, gparas, cls:g.className||'', z: zOf.get(g) });
    for (const el of g.querySelectorAll('*')) consumed.add(el);
    consumed.add(g);
  }

  // ---- rects (fills / gradients / borders), in document (paint) order ----
  for (const el of all) {
    if (inChart(el) || inSkip(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0.5 || r.height <= 0.5) continue;
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    const hasFill = bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
    const grad = (cs.backgroundImage || '').includes('gradient') ? cs.backgroundImage : '';
    const bt=parseFloat(cs.borderTopWidth)||0, bl=parseFloat(cs.borderLeftWidth)||0,
          brr=parseFloat(cs.borderRightWidth)||0, bb=parseFloat(cs.borderBottomWidth)||0;
    const anyB = (bt||bl||brr||bb) > 0 && cs.borderTopStyle !== 'none';
    if (hasFill || grad || anyB) {
      // Resolve border-radius to px. Edge returns a percentage radius (e.g. border-radius:50%)
      // as the literal string "50%", which parseFloat would read as 50px - turning circles into
      // squircles downstream. Convert % against the shorter side so 50% => a true circle/ellipse.
      const rrRaw = cs.borderTopLeftRadius || '0';
      const radiusPx = rrRaw.indexOf('%') >= 0
        ? (parseFloat(rrRaw)/100) * Math.min(r.width, r.height)
        : (parseFloat(rrRaw) || 0);
      rects.push({x:r.x,y:r.y,w:r.width,h:r.height, fill:hasFill?bg:'', grad,
        border: anyB ? {t:bt,l:bl,r:brr,b:bb,
          colT:cs.borderTopColor,colL:cs.borderLeftColor,colR:cs.borderRightColor,colB:cs.borderBottomColor,
          radius:radiusPx} : null,
        radius: radiusPx, z: zOf.get(el),
        cls:el.className||'', tag:el.tagName.toLowerCase()});
    }
  }

  // ---- text boxes with runs/paragraphs ----
  for (const el of all) {
    if (consumed.has(el)) continue;
    if (inChart(el) || inSkip(el)) continue;
    if (!directText(el)) continue;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const base = runStyle(cs);
    const paras = [[]];
    for (const n of el.childNodes) {
      if (n.nodeType === 3) {
        const t = n.textContent.replace(/\s+/g,' ');
        if (t.trim()) paras[paras.length-1].push(Object.assign({t}, base));
      } else if (n.nodeType === 1) {
        if (n.tagName === 'BR') { paras.push([]); continue; }   // line break -> new paragraph (don't jam runs)
        const ccs = getComputedStyle(n);
        // A row-direction flex parent blockifies its children (<b>, <span> report display:block) but
        // lays them out side by side on one line - so they are runs of one paragraph, not new paragraphs.
        const rowFlex = cs.display.includes('flex') && !(cs.flexDirection || '').startsWith('column');
        const inl = ccs.display.startsWith('inline') || rowFlex;
        const txt = n.textContent.replace(/\s+/g,' ').trim();
        if (!txt) continue;
        const run = Object.assign({t:txt}, runStyle(ccs));
        if (inl) { paras[paras.length-1].push(run); consumed.add(n); }
        else { paras.push([run]); paras.push([]); consumed.add(n); }
      }
    }
    const cleaned = paras.filter(p => p.length);
    if (!cleaned.length) continue;
    // How many lines the browser actually laid out (from rendered height / line-height).
    // The translator only sets wrap="none" when this is 1 - a short label that the
    // browser broke onto two lines must stay wrapped in PPT too.
    const fsT = parseFloat(cs.fontSize) || 12;
    const lhT = parseFloat(cs.lineHeight) || fsT * 1.2;
    const padV = (parseFloat(cs.paddingTop)||0) + (parseFloat(cs.paddingBottom)||0);
    const nlines = Math.max(1, Math.round((r.height - padV) / lhT));
    texts.push({x:r.x,y:r.y,w:r.width,h:r.height, lines: nlines, lhpx: lhT,
      align: cs.textAlign,
      anchor: (cs.display.includes('flex') && (cs.alignItems==='center')) ? 'ctr'
              : (cs.display.includes('flex') && cs.alignItems==='flex-end') ? 'b' : 't',
      pl:parseFloat(cs.paddingLeft)||0, pr:parseFloat(cs.paddingRight)||0,
      pt:parseFloat(cs.paddingTop)||0, pb:parseFloat(cs.paddingBottom)||0,
      paras: cleaned, cls: el.className||'', z: zOf.get(el)});
  }

  // ---- images: every visible <img>, and every element whose computed background-image is a
  //      non-gradient url(...). Path resolution / existence / format validation happens in
  //      Python (see extract_geometry.py main()); here we just capture geometry + the raw
  //      (browser-resolved, absolute) source URL. ----
  const loadNatural = (url) => new Promise((resolve) => {
    const probe = new Image();
    probe.onload = () => resolve({w: probe.naturalWidth, h: probe.naturalHeight});
    probe.onerror = () => resolve({w: 0, h: 0});
    probe.src = url;
  });
  const parseBgUrl = (bgImg) => {
    const m = /url\(["']?([^"')]+)["']?\)/.exec(bgImg || '');
    return m ? m[1] : null;
  };
  const parsePosFrac = (val) => {
    if (!val) return 0.5;
    val = val.trim();
    if (val === 'center') return 0.5;
    if (val === 'left' || val === 'top') return 0;
    if (val === 'right' || val === 'bottom') return 1;
    if (val.endsWith('%')) return parseFloat(val) / 100;
    return 0.5;   // px/other units - not worth precise mapping here
  };
  for (const el of all) {
    if (inChart(el) || inSkip(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0.5 || r.height <= 0.5) continue;
    const cs = getComputedStyle(el);

    let src = null, isImgTag = false, fit = 'fill', natW = 0, natH = 0;
    if (el.tagName === 'IMG') {
      isImgTag = true;
      src = el.currentSrc || el.src;
      fit = cs.objectFit || 'fill';
      natW = el.naturalWidth; natH = el.naturalHeight;
    } else {
      const bgImg = cs.backgroundImage || '';
      if (bgImg && bgImg !== 'none' && !bgImg.includes('gradient')) {
        src = parseBgUrl(bgImg);
        const bs = (cs.backgroundSize || '').trim();
        fit = (bs === 'cover') ? 'cover' : (bs === 'contain') ? 'contain'
              : (bs === 'auto' || bs === 'auto auto' || bs === '') ? 'none' : 'fill';
      }
    }
    if (!src) continue;
    if (!natW || !natH) {
      const nat = await loadNatural(src);
      natW = nat.w || natW; natH = nat.h || natH;
    }

    const posSrc = isImgTag ? cs.objectPosition : cs.backgroundPosition;
    const posParts = (posSrc || '').split(/\s+/);
    const pos_x = parsePosFrac(posParts[0]);
    const pos_y = parsePosFrac(posParts[1]);

    const rrRaw = cs.borderTopLeftRadius || '0';
    const radiusPx = rrRaw.indexOf('%') >= 0
      ? (parseFloat(rrRaw)/100) * Math.min(r.width, r.height)
      : (parseFloat(rrRaw) || 0);

    images.push({ sel: selOf(el), x:r.x, y:r.y, w:r.width, h:r.height,
      src, natural_w: natW, natural_h: natH,
      fit, pos_x, pos_y, radius: radiusPx,
      opacity: parseFloat(cs.opacity), z: zOf.get(el) });
  }
  return {w: Math.round(document.body.getBoundingClientRect().width),
          h: Math.round(document.body.getBoundingClientRect().height),
          layout: document.body.dataset.pptLayout || null,
          bodyBg: getComputedStyle(document.body).backgroundColor,
          rects, texts, images, charts, warnings};
}
"""

def _launch_browser(p):
    """Edge, then Chrome, then the Playwright-bundled Chromium. Exits 1 if none launch."""
    for channel in ("msedge", "chrome"):
        try:
            return p.chromium.launch(channel=channel)
        except Exception:
            continue
    try:
        return p.chromium.launch()
    except Exception as e:
        print("FAILED: no usable browser found (tried Edge, Chrome, bundled Chromium)")
        print("  fix: python -m playwright install chromium")
        print(f"  ({e})")
        sys.exit(1)


SUPPORTED_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}


def _url_to_path(url, base_dir):
    """A browser-resolved absolute URL (file:// URL, or - rarely - a bare path) -> an
    absolute filesystem Path. Returns None for http(s)/data URLs (not local files)."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https", "data"):
        return None
    if parsed.scheme == "file":
        p = unquote(parsed.path)
        if platform.system() == "Windows" and p.startswith("/") and len(p) > 2 and p[2] == ":":
            p = p[1:]                       # "/C:/..." -> "C:/..."
        return Path(p)
    p = Path(unquote(url))                  # no scheme - treat as a path
    if not p.is_absolute():
        p = base_dir / p
    return p


def _rasterize_svg(browser, svg_path, out_path, w_px, h_px):
    """Rasterise an SVG file to a PNG at 2x the target box size, via the same Playwright
    browser used for the slide itself. Renders the SVG as an <img> in a blank page sized
    exactly to the target so the screenshot needs no further cropping/scaling."""
    target_w = max(1, int(round(w_px * 2)))
    target_h = max(1, int(round(h_px * 2)))
    svg_uri = Path(svg_path).resolve().as_uri()
    cache_name = "_svg_%s.png" % hashlib.sha1(str(svg_path).encode("utf-8")).hexdigest()[:12]
    out_png = Path(out_path).parent / cache_name
    page = browser.new_page(viewport={"width": target_w, "height": target_h}, device_scale_factor=1)
    try:
        html = ('<!doctype html><html><body style="margin:0;padding:0;background:transparent">'
                '<img src="%s" style="display:block;width:%dpx;height:%dpx"></body></html>'
                % (svg_uri, target_w, target_h))
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(out_png), omit_background=True)
    finally:
        page.close()
    return out_png


def _finalize_images(data, html_path, out_path, browser):
    """Resolve each image's browser-reported src URL to a filesystem path, drop (with a
    warning) anything the translator cannot embed, and rasterise SVGs to PNG in place."""
    base_dir = html_path.parent
    kept = []
    for im in data.get("images", []):
        raw = im.get("src")
        if urlparse(raw or "").scheme in ("http", "https"):
            data["warnings"].append({"sel": im["sel"], "text": "",
                "why": "http(s) image URL - not supported",
                "fix": "download the image locally and reference it with a file path"})
            continue
        p = _url_to_path(raw, base_dir)
        if p is None or not p.exists():
            data["warnings"].append({"sel": im["sel"], "text": "",
                "why": "image source not found: %s" % raw,
                "fix": "check the file path/spelling"})
            continue
        ext = p.suffix.lower()
        if ext not in SUPPORTED_IMG_EXTS:
            data["warnings"].append({"sel": im["sel"], "text": "",
                "why": "unsupported image format '%s' - only png/jpg/jpeg/gif/bmp/svg/webp" % ext,
                "fix": "convert the image to a supported format"})
            continue
        if ext == ".svg":
            try:
                p = _rasterize_svg(browser, p, out_path, im["w"], im["h"])
                im["natural_w"] = im["w"] * 2
                im["natural_h"] = im["h"] * 2
            except Exception as e:                                  # noqa: BLE001
                data["warnings"].append({"sel": im["sel"], "text": "",
                    "why": "SVG rasterisation failed: %s" % e,
                    "fix": "convert the SVG to PNG manually"})
                continue
        im["src"] = str(p)
        kept.append(im)
    data["images"] = kept


def main():
    _cli.usage(__doc__, sys.argv[1:], 2, 2)
    src, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    with sync_playwright() as p:
        b = _launch_browser(p)
        pg = b.new_page(viewport={"width":1280,"height":720}, device_scale_factor=1)
        pg.goto(src.as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(300)
        data = pg.evaluate(JS.replace("__CHROME_SELECTOR__", CHROME_SELECTOR))
        _finalize_images(data, src, out, b)
        b.close()
    with open(out,"w",encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    print("canvas %dx%d | %d rects | %d text boxes | %d image(s) | %d native chart(s)" %
          (data["w"], data["h"], len(data["rects"]), len(data["texts"]), len(data.get("images", [])),
           len(data.get("charts", []))))
    for w in data.get("warnings", []):
        print("WARN  %s: %s - %s" % (w["sel"], w["why"], w["fix"]))

if __name__ == "__main__":
    main()
