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
import sys, json
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as _cfg

# Chrome the template master already provides (a logo, a page number) must not be translated
# twice. When house.json says template_supplies_chrome, the .wordmark / .pg elements are kept
# in the HTML preview but skipped in translation; otherwise they become ordinary text boxes.
CHROME_SELECTOR = ".ppt-skip, .wordmark, .pg" if _cfg.TEMPLATE_SUPPLIES_CHROME else ".ppt-skip"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as _cfg

# Chrome the template master already provides (a logo, a page number) must not be translated
# twice. When house.json says template_supplies_chrome, the .wordmark / .pg elements are kept
# in the HTML preview but skipped in translation; otherwise they become ordinary text boxes.
CHROME_SELECTOR = ".ppt-skip, .wordmark, .pg" if _cfg.TEMPLATE_SUPPLIES_CHROME else ".ppt-skip"

JS = r"""
() => {
  const all = Array.from(document.querySelectorAll('body *'));
  const rects = [], texts = [], charts = [];
  const consumed = new Set();
  const directText = (el) => Array.from(el.childNodes).some(n => n.nodeType===3 && n.textContent.trim());

  // ---- native-chart regions: a .ppt-chart element becomes a real PPT chart;
  //      its box + data attributes are captured, and it + its subtree are skipped from rects/texts.
  const chartEls = Array.from(document.querySelectorAll('.ppt-chart'));
  const chartSet = new Set(chartEls);
  const inChart = (el) => { let n = el; while (n) { if (chartSet.has(n)) return true; n = n.parentElement; } return false; };

  // ---- elements to leave out of translation: anything marked .ppt-skip, plus (only when the
  //      template master already draws them) the .wordmark / .pg chrome. See CHROME_SELECTOR.
  const skipSet = new Set(Array.from(document.querySelectorAll('__CHROME_SELECTOR__')));
  const inSkip = (el) => { let n = el; while (n) { if (skipSet.has(n)) return true; n = n.parentElement; } return false; };

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
      catlabelRotation: el.dataset.catlabelRotation || '' });
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
    const blocks = Array.from(g.querySelectorAll('*'))
      .filter(el => directText(el) && !getComputedStyle(el).display.startsWith('inline'));
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
          const txt = n.textContent.replace(/\s+/g,' ').trim(); if (!txt) continue;
          runs.push(Object.assign({t:txt}, runStyle(getComputedStyle(n))));
        }
      }
      if (!runs.length) continue;
      const spcBef = (prevBottom === null) ? 0 : Math.max(0, r.top - prevBottom);
      prevBottom = r.bottom;
      const fs = parseFloat(cs.fontSize) || 12;
      const lh = parseFloat(cs.lineHeight) || fs * 1.2;
      gparas.push({ runs, align: cs.textAlign, spcBef, lhpct: Math.round(lh / fs * 100000) });
    }
    if (!gparas.length) continue;
    texts.push({ x:gr.x, y:gr.y, w:gr.width, h:gr.height, align:gcs.textAlign, anchor:'t',
      pl:parseFloat(gcs.paddingLeft)||0, pr:parseFloat(gcs.paddingRight)||0,
      pt:parseFloat(gcs.paddingTop)||0, pb:parseFloat(gcs.paddingBottom)||0,
      grouped:true, gparas, cls:g.className||'' });
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
        radius: radiusPx,
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
        const inl = ccs.display.startsWith('inline');
        const txt = n.textContent.replace(/\s+/g,' ').trim();
        if (!txt) continue;
        const run = Object.assign({t:txt}, runStyle(ccs));
        if (inl) { paras[paras.length-1].push(run); consumed.add(n); }
        else { paras.push([run]); paras.push([]); consumed.add(n); }
      }
    }
    const cleaned = paras.filter(p => p.length);
    if (!cleaned.length) continue;
    texts.push({x:r.x,y:r.y,w:r.width,h:r.height,
      align: cs.textAlign,
      anchor: (cs.display.includes('flex') && (cs.alignItems==='center')) ? 'ctr'
              : (cs.display.includes('flex') && cs.alignItems==='flex-end') ? 'b' : 't',
      pl:parseFloat(cs.paddingLeft)||0, pr:parseFloat(cs.paddingRight)||0,
      pt:parseFloat(cs.paddingTop)||0, pb:parseFloat(cs.paddingBottom)||0,
      paras: cleaned, cls: el.className||''});
  }
  return {w: Math.round(document.body.getBoundingClientRect().width),
          h: Math.round(document.body.getBoundingClientRect().height),
          layout: document.body.dataset.pptLayout || null,
          bodyBg: getComputedStyle(document.body).backgroundColor,
          rects, texts, charts};
}
"""

def main():
    src, out = Path(sys.argv[1]).resolve(), sys.argv[2]
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge")
        except Exception:
            b = p.chromium.launch()
        pg = b.new_page(viewport={"width":1280,"height":720}, device_scale_factor=1)
        pg.goto(src.as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(300)
        data = pg.evaluate(JS.replace("__CHROME_SELECTOR__", CHROME_SELECTOR))
        b.close()
    with open(out,"w",encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    print("canvas %dx%d | %d rects | %d text boxes | %d native chart(s)" %
          (data["w"], data["h"], len(data["rects"]), len(data["texts"]), len(data.get("charts", []))))

if __name__ == "__main__":
    main()
