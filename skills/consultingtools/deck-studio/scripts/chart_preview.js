/* chart_preview.js - draw an approximate picture of every .ppt-chart, for human review only.

   A .ppt-chart div carries the data for a native PowerPoint chart in data- attributes; a browser
   cannot draw it, so without this the workroom shows an empty box where the chart belongs and the
   reviewer has to take the chart on trust. This script reads those same attributes and paints a
   close-enough SVG in the box.

   Injected at view time by workroom.py and render_html.py. It is never in the authored HTML, so
   typecheck.py never sees it; and the geometry extractor skips every descendant of .ppt-chart, so
   it cannot reach the .pptx. The PowerPoint render-back remains the only evidence of the real chart.
*/
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var GREY = '#8C8C8C';

  function el(name, attrs) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) { if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]); }
    return n;
  }
  function hex(c) { return (c && String(c).charAt(0) === '#') ? c : '#' + (c || '888888'); }
  function text(x, y, s, size, color, bold, anchor) {
    var t = el('text', {x: x, y: y, 'font-size': size, fill: color, 'text-anchor': anchor || 'middle',
                        'font-weight': bold ? '700' : '400', 'dominant-baseline': 'middle'});
    t.textContent = s;
    return t;
  }
  function fmt(v) { return (Math.round(v * 10) / 10).toString(); }

  function draw(box) {
    var W = box.clientWidth, H = box.clientHeight;
    if (!W || !H) { return; }
    var type = box.dataset.chart || 'stacked-column';
    var cats = (box.dataset.categories || '').split('|').filter(function (s) { return s !== ''; });
    var series;
    try { series = JSON.parse(box.dataset.series || '[]'); } catch (e) { return; }
    if (!series.length) { return; }
    if (!cats.length) { cats = series[0].values.map(function (_, i) { return String(i + 1); }); }

    var horiz = type.indexOf('bar') === 0 || type === 'stacked-bar';
    var stacked = type.indexOf('stacked') === 0;
    var line = type.indexOf('line') === 0;
    var highlight = null;
    try { highlight = JSON.parse(box.dataset.highlight || 'null'); } catch (e) { highlight = null; }

    var catBold = box.dataset.catlabelbold === 'true';
    var catFs = Number(box.dataset.catlabelsize || '') > 0 ? Number(box.dataset.catlabelsize) * 4 / 3 : 11;   // pt -> px
    var legendPos = box.dataset.legend || 'none';
    var showLegend = legendPos !== 'none' && legendPos !== 'hide' && series.length > 1;
    var showAxis = (box.dataset.valueaxis || '') !== 'hide';
    // mirror html_to_pptx.py: hiding the value axis kills its gridlines too, so the preview
    // must not show rules the real chart will not have
    var showGrid = (box.dataset.gridlines || '') !== 'hide' && showAxis;

    var padTop = showLegend ? 24 : 8;
    var padBottom = horiz ? 8 : 20;
    var padLeft = horiz ? 74 : (showAxis ? 36 : 4);
    var padRight = 6;
    var pw = W - padLeft - padRight, ph = H - padTop - padBottom;
    if (pw <= 0 || ph <= 0) { return; }

    var top = 0, i, j;
    for (i = 0; i < cats.length; i++) {
      var s = 0;
      for (j = 0; j < series.length; j++) {
        var v = Number((series[j].values || [])[i]) || 0;
        if (stacked) { s += v; } else { s = Math.max(s, v); }
      }
      top = Math.max(top, s);
    }
    if (top <= 0) { return; }
    top = top * 1.04;
    var vmax = Number(box.dataset.valuemax || '');
    if (vmax > 0) { top = vmax; }   // shared scale, same as the translator's maximum_scale

    var svg = el('svg', {width: W, height: H, viewBox: '0 0 ' + W + ' ' + H});
    svg.setAttribute('font-family', getComputedStyle(box).fontFamily);

    if (showGrid || showAxis) {
      for (i = 0; i <= 4; i++) {
        var gv = top * i / 4;
        var gp = horiz ? padLeft + pw * i / 4 : padTop + ph - ph * i / 4;
        if (showGrid) {
          svg.appendChild(horiz
            ? el('line', {x1: gp, y1: padTop, x2: gp, y2: padTop + ph, stroke: '#E4E4E4', 'stroke-width': 1})
            : el('line', {x1: padLeft, y1: gp, x2: padLeft + pw, y2: gp, stroke: '#E4E4E4', 'stroke-width': 1}));
        }
        if (showAxis && !horiz) { svg.appendChild(text(padLeft - 6, gp, fmt(gv), 10, GREY, false, 'end')); }
      }
    }

    var n = cats.length;
    var slot = (horiz ? ph : pw) / n;
    var bandPad = slot * 0.22;
    var band = slot - bandPad * 2;

    function segLabel(sr, idx, val, x0, y0, x1, y1) {
      var lab = sr.labels;
      if (!lab) { return; }
      var str = (lab === true) ? fmt(val) : lab[idx];
      if (str === undefined || str === null || str === '') { return; }
      var pos = sr.labelpos || (stacked ? 'center' : 'outside_end');
      var size = Number(sr.labelsize) || 11;
      var color = hex(sr.labelcolor || '1E1E1E');
      var cx, cy, anchor = 'middle';
      if (horiz) {
        cy = (y0 + y1) / 2;
        if (pos === 'inside_end') { cx = x1 - 5; anchor = 'end'; }
        else if (pos === 'inside_base') { cx = x0 + 5; anchor = 'start'; }
        else if (pos === 'outside_end') { cx = x1 + 5; anchor = 'start'; }
        else { cx = (x0 + x1) / 2; }
      } else {
        cx = (x0 + x1) / 2;
        if (pos === 'inside_end') { cy = y0 + size * 0.85; }
        else if (pos === 'inside_base') { cy = y1 - size * 0.85; }
        else if (pos === 'outside_end' || pos === 'above') { cy = y0 - size * 0.7; }
        else { cy = (y0 + y1) / 2; }
      }
      svg.appendChild(text(cx, cy, str, size, color, sr.labelbold, anchor));
    }

    if (line) {
      for (j = 0; j < series.length; j++) {
        var pts = [], col = hex(series[j].color || '1E1E1E');
        for (i = 0; i < n; i++) {
          var lv = Number((series[j].values || [])[i]) || 0;
          var lx = padLeft + slot * i + slot / 2;
          var ly = padTop + ph - (lv / top) * ph;
          pts.push(lx + ',' + ly);
          if (type === 'line-markers') { svg.appendChild(el('circle', {cx: lx, cy: ly, r: 3.5, fill: col})); }
          segLabel(series[j], i, lv, lx - 12, ly - 10, lx + 12, ly);
        }
        svg.appendChild(el('polyline', {points: pts.join(' '), fill: 'none', stroke: col, 'stroke-width': 2}));
      }
    } else {
      for (i = 0; i < n; i++) {
        var base = 0;
        var sub = stacked ? band : band / series.length;
        for (j = 0; j < series.length; j++) {
          var val = Number((series[j].values || [])[i]) || 0;
          var fill = hex(series[j].color || '888888');
          if (highlight && highlight.series === j && highlight.point === i) { fill = hex(highlight.color); }
          var len = (val / top) * (horiz ? pw : ph);
          var off = stacked ? 0 : sub * j;
          var x0, y0, x1, y1;
          if (horiz) {
            y0 = padTop + slot * i + bandPad + off;
            y1 = y0 + sub;
            x0 = padLeft + (stacked ? (base / top) * pw : 0);
            x1 = x0 + len;
          } else {
            x0 = padLeft + slot * i + bandPad + off;
            x1 = x0 + sub;
            y1 = padTop + ph - (stacked ? (base / top) * ph : 0);
            y0 = y1 - len;
          }
          svg.appendChild(el('rect', {x: Math.min(x0, x1), y: Math.min(y0, y1),
                                      width: Math.abs(x1 - x0), height: Math.abs(y1 - y0), fill: fill}));
          segLabel(series[j], i, val, x0, y0, x1, y1);
          if (stacked) { base += val; }
        }
      }
    }

    for (i = 0; i < n; i++) {
      if (horiz) {
        svg.appendChild(text(padLeft - 8, padTop + slot * i + slot / 2, cats[i], catFs, '#595959', catBold, 'end'));
      } else {
        svg.appendChild(text(padLeft + slot * i + slot / 2, padTop + ph + 11, cats[i], catFs, '#595959', catBold));
      }
    }

    if (showLegend) {
      var lx2 = padLeft;
      for (j = 0; j < series.length; j++) {
        svg.appendChild(el('rect', {x: lx2, y: 3, width: 10, height: 10, fill: hex(series[j].color || '888888')}));
        var nm = series[j].name || ('Series ' + (j + 1));
        svg.appendChild(text(lx2 + 15, 8, nm, 11, '#595959', false, 'start'));
        lx2 += 15 + nm.length * 6 + 18;
      }
    }

    box.textContent = '';
    box.appendChild(svg);
  }

  function run() {
    var boxes = document.querySelectorAll('.ppt-chart');
    for (var i = 0; i < boxes.length; i++) {
      try { draw(boxes[i]); } catch (e) { /* leave the box as authored rather than break the page */ }
    }
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', run); } else { run(); }
})();
