# HTML-first slide pipeline (the way house slides are built)

**This is the primary method for building any house slide.** Do NOT hand-author OOXML shape geometry - agents cannot lay out a slide blind in XML, and it produces thin, broken slides (proven repeatedly). Instead: **design in HTML where you can see and iterate, then translate the rendered layout into native PowerPoint shapes.** The output is a real, editable .pptx (not an image), faithful to the HTML.

Validated 2026-06-14. Canvas identity: **1280x720 px (HTML) == 12192000 x 6858000 EMU == 960 x 540 pt (slide). px x 9525 = EMU. px x 0.75 = pt.**

## The build loop - two phases, with a STOP between them

> ### STOP: Do not build the .pptx until the human has seen the mockups and said go.
>
> **Almost all of the work happens in phase 1, in HTML, with the user in the loop.** Expect several rounds of
> comments and revisions on the mockups before PowerPoint is mentioned at all. Phase 2 is a mechanical
> translation that should be fast and uneventful.
>
> **Handing over a finished .pptx the user has never seen is a FAILED run, even if every gate passed and the
> deck is good.** It removes the only step where they can change the thinking cheaply. Passing typecheck and
> the render-back gate is not the same as approval - those check that you built it correctly, not that you
> built the right thing.
>
> The one exception is an explicit instruction to go straight through ("just build it", "no need to review").

### Phase 1 - design and iterate in HTML (where the time goes)

**0. Settle the brief.** `00_intake.md` - message, audience, density tier, evidence, constraints. Ask if
   uncertain. A thin brief produces a thin slide no matter how good the rest of this loop is.

**1. Brainstorm the format from the message**, then design it in constrained HTML (`<name>.html`).
   Use `visual-formats.md` as thinking vocabulary. **Do not pick a format by finding the nearest thing in
   `reference/` and refilling it.** Load 2+ references at your declared tier to calibrate *depth and colour*,
   never to choose the format. Boilerplate below.

**2. Check mechanically, then look, then fix.**
   - `python scripts/typecheck.py <name>.html` - delivered pt sizes, colour, caps, tracking, dashes, canvas
     usage, **text collisions, chrome-zone intrusions and panel overflow**.
   - `powershell -File scripts/render_html.ps1 -HtmlPath <name>.html -OutPath <name>.png` - then **view the
     PNG**. You cannot see a browser; this is how you see your own work.
   - Iterate until clean. This loop is cheap and is where quality is won.

**3. STOP: SHOW THE HUMAN AND STOP.** `python scripts/workroom.py <dir> --open` regenerates the deck's
   `workroom.html` - every slide full size in its own iframe, with zoom and a contact-sheet grid. Give them the
   path, say what you built and what you were unsure about, and **wait**. Take their comments back to step 1.
   Repeat as many times as it takes. Mark slides `approved` in `workroom.json` as they land.

   Show mockups **early and half-finished** rather than late and polished - a format that is wrong is cheaper
   to discover at round one than after four slides are built to it.

### Phase 2 - translate (only after approval)

**4. Extract geometry.** `python scripts/extract_geometry.py <name>.html geom.json` (Playwright via system Edge).

**5. Translate.** `python scripts/html_to_pptx.py geom.json "<out>.pptx"` - native shapes with exact hex onto
   the configured template, packed via `scripts/office_io.py`. Or `build_deck.py` for several slides at once.

**6. Render back and verify (mandatory gate).**
   `powershell -File scripts/render_slides.ps1 -PptxPath "<out>.pptx" -OutDir <dir>` (PowerPoint COM; no
   LibreOffice fallback is configured). **View the render and compare it to the HTML.** Never ship without this: the
   browser mockup is not evidence. Several translator gaps below looked perfect in the browser and were only
   caught here.

**7. If you change anything after this, change the HTML and regenerate** - never hand-patch the .pptx, and tell
   the user their manual .pptx edits will be overwritten by the next rebuild.

## Adding a slide to an existing deck

The loop above builds a standalone .pptx. Most real work instead inserts one new slide into a deck that already
exists. That flow, as run repeatedly on real decks:

```bash
# 1. wrap the fragment and build it as a single-slide deck
python scripts/build_deck.py _new_standalone.pptx slide_VXX.html

# 2. copy the target deck to its next version, unpack it
cp "<deck> v0.8.pptx" "<deck> v0.9.pptx"
python scripts/office_io.py unpack "<deck> v0.9.pptx" _unpacked/

# 3. clone the new slide in, then MOVE its <p:sldId> to the right position in ppt/presentation.xml
python scripts/clone_slide.py _new_standalone.pptx 1 _unpacked/

# 4. fonts, then pack against the previous version
python scripts/patch_fonts.py _unpacked/
python scripts/office_io.py pack _unpacked/ "<deck> v0.9.pptx"

# 5. font check must print CLEAN, then render-verify (step 6 above)
```

- `clone_slide.py` appends to the end of `<p:sldIdLst>`; **reposition the entry by hand** to place the slide.
- It used to emit an out-of-range `sldId` on decks carrying an id at the 2147483647 ceiling (an invalid file).
  Fixed Sept 2026 - it now takes the lowest free id - but check the entry looks sane.
- **Never build into a file someone else is editing.** Version forward, and confirm which lineage you are on.

## Constrained-HTML vocabulary (design ONLY in the translatable subset)

The translator maps a *subset* of HTML to PPT shapes. The more you design within it, the more faithful the .pptx. The subset is also the visual language of a good consulting slide, so this is not very limiting.

**USE (translates cleanly):**
- Positioned `<div>`s with solid fills, borders, and `border-radius` -> rectangles / rounded rectangles
- Text with inline `<b>` / `<span>` for emphasis -> text boxes with styled runs (one box per text block; inline emphasis becomes bold runs, block children become new paragraphs)
- **A bulleted list / multi-line block -> wrap it in `<div class="pgroup">`** so it becomes ONE text box with the bullets as paragraphs (see next section). Do NOT leave each `<p>`/bullet as a separate sibling div - that emits one text box per bullet, which loses indentation and consistent spacing (a defect the house standard flags).
- Thin divs as rules / lines; two-tone via an overlaid div with `rgba()` alpha
- `<img>` (photos) - place at a box

**Font colour: black / white / grey ONLY.** Emphasis is `<b>` (bold, still black) - never a coloured run. Amber/hot/coral are for *fills, borders, shapes* only (an amber `<div>` behind black text is fine; amber text is not). See `SKILL.md` -> Palette -> "Text / font colour".

**AVOID (does NOT translate - design around these):**
- **Rotated text / `writing-mode: vertical`** -> renders flat and overlaps. Use horizontal text, or omit the rotated label.
- **CSS border-triangles** (0-size element with borders) -> skipped (zero bounding box). Use a real shape/image if you need an arrowhead.
- **Gradients** -> approximated to a single solid (the top stop). Fine for accents; don't rely on gradient meaning.
- **`box-shadow`, SVG paths, icon fonts, inline SVG icons** -> not captured. Avoid, or accept they won't appear; rasterise to `<img>` if essential.

Flex/grid layout itself is fine - the extractor reads *computed* positions, so you never hand-place coordinates.

## Grouping lines into one text box (`.pgroup`)

**Any time you have 2+ stacked text lines that read as one block (a bulleted list, a label+value pair, a multi-line caption), wrap them in `<div class="pgroup">`.** The extractor then emits a SINGLE text box whose direct-text block children each become a *paragraph*, with the vertical gaps measured from the render and written as paragraph space-before (pt) + line-spacing (%). Without it, each `<p>`/`<div>` becomes its own floating text box - bullets lose their shared indentation and even spacing, which is the "each bullet in a different text box" defect.

```html
<div class="pgroup" style="position:absolute; left:616px; top:200px; width:600px; padding:10px 15px;">
  <p style="margin-bottom:6px;"><b>Q1 actuals in:</b> 2.4 MEUR revenue, 14% EBITDA margin</p>
  <p style="margin-bottom:6px;"><b>Full-year plan revised</b> to 9.8 MEUR / 1.4 MEUR</p>
  <p><b>1.1 MEUR cash, no debt</b>; two new directors joined in May</p>
</div>
```
- One `.pgroup` per list/box. The group's `padding` becomes the text-box insets; the per-paragraph `margin`/gap becomes space-before.
- **Hanging indent for bullets:** the translator does not yet read per-paragraph `text-indent`, so for a true hanging indent (marker stays put, wrapped lines align under the text) put the bullet glyph and the body in the same paragraph and give the paragraph a left padding via the group, OR hand-set `marL`/`indent` on the paragraph after translation. Keep bullet markers as a leading character in the paragraph text (e.g. a real `•`), not a CSS `::before` pseudo-element (pseudo-elements are not captured).
- Emphasis inside a paragraph is inline `<b>`/`<span>` -> runs (bold only; no colour - see font-colour rule above).

## Boilerplate (font + canvas)

Font paths are machine-specific. Get the correct `@font-face` block for this machine from
`scripts/config.py` rather than pasting a path:

```bash
python -c "import sys;sys.path.insert(0,'scripts');import config;print(config.font_face_css())"
```

This prints an empty CSS comment for a system font such as Arial (the default). Drop the result into the
slide's `<style>`, followed by:

```html
  *{box-sizing:border-box;}
  html,body{width:1280px;height:720px;margin:0;font-family:'<house font>',Arial,sans-serif;background:#fff;}
  .slide{width:1280px;height:720px;position:relative;overflow:hidden;background:#FFFFFF;}
```

The font-family value comes from `house.json` - swap in whatever the house standard names there.

The `.slide` background is promoted to the slide's real background property in translation, so set the canvas
colour there and never draw a rectangle to fake it.

**Palette: see `house_style.md` section 4** - the house default is near-monochrome (white canvas, grey ramp,
warm sand `#CCBB9D` as the single secondary, warmth from photography). Do **not** use the template's own theme
colours unless they are the brand, and do not treat amber as a general fill.

## Layout selection and template chrome

**Layouts are resolved by name, not filename.** `<body data-ppt-layout="...">` accepts an alias (`blank`,
`title`, `divider`, `end`), a substring of a layout name, or a literal `slideLayoutN.xml`; the default is the
blankest layout available. Run `python scripts/list_layouts.py` to print what the configured template offers.

**`.wordmark` / `.pg` behaviour:** if `house.json` sets `template_supplies_chrome` to `true`, `.wordmark` and
`.pg` are kept in the HTML preview but skipped in translation because the template master draws them.
Otherwise (the default) they translate as normal text boxes, and `wordmark_text` in `house.json` is what you
put in the `.wordmark` div.

## Native charts (hybrid) - real editable PPT charts inside the designed slide

Data charts should be REAL PowerPoint charts (right-click -> Edit Data), not shape-bars. Mark a chart region in the HTML with a `.ppt-chart` element carrying its data; the translator reserves that box and drops a native python-pptx chart there, while the rest of the slide stays as designed shapes (the house's chosen model, adopted 2026-06-14). Author bespoke annotations (CAGR arrow, callouts, a driver rail) as normal HTML elements OUTSIDE the chart box - they translate to shapes and sit around the chart. Don't author per-column overlays (PPT controls column geometry); put per-bar numbers as the chart's own data labels instead.

```html
<div class="ppt-chart"
     data-chart="stacked-column"            <!-- stacked-column | column | stacked-bar | bar | line | line-markers -->
     data-categories="FY22|FY23|FY24|FY25|FY26B"
     data-series='[
        {"name":"EBITDA","values":[12.1,15.6,17.9,20.4,23.5],"color":"1E1E1E",
         "labels":["17%","18%","16%","17%","17%"],"labelpos":"center","labelcolor":"FFFFFF","labelbold":true},
        {"name":"Revenue above EBITDA","values":[59.3,71.4,94.1,102.6,114.5],"color":"B8B8B8",
         "labels":["71","87","112","123","138"],"labelpos":"inside_end","labelcolor":"1E1E1E","labelbold":true}]'
     data-highlight='{"series":0,"point":2,"color":"FAA21B"}'   <!-- amber a single point: the one dip worth flagging -->
     data-legend="top"                       <!-- top | none -->
     data-valueaxis="hide"                    <!-- hide | show -->
     style="position:...;width:..px;height:..px;">native chart placeholder (shows only in HTML preview)</div>
```
Per-series keys: `color` (hex), `labels` (list of custom strings, or true for values), `labelpos`, `labelcolor`, `labelbold`, `labelsize`.

**WARNING - `labelpos` on STACKED charts: only `center`, `inside_end` and `inside_base` are legal.** PowerPoint rejects
`outside_end` and `above` on a stacked series - and it rejects them by refusing to open the whole file
("corrupted and unreadable"), while python-pptx reads it back perfectly happily. That combination made it a
genuinely nasty bug to trace (found Sept 2026 by bisection on a real deck). The translator now clamps an
illegal value to `inside_end` and prints a warning, so this cannot bite again - but author it correctly.
For a column total, `inside_end` reads naturally anyway. On non-stacked charts all five values are fine.

`data-gridlines="hide"` drops the value-axis gridlines. `data-valueaxis="hide"` now does this too - hiding the
axis used to leave its gridlines behind as stray rules across the plot. Colours follow the chart rule (grey/black/dark-blue series, amber to mark ONE hero point - never coral/blue series). The `.ppt-chart` element and its contents are skipped from shape translation; only its box + data attributes are used. Implemented in `scripts/extract_geometry.py` (captures chart regions) + `scripts/html_to_pptx.py` (`add_native_charts`, post-pack via python-pptx).

## Known limitations / fixes baked into the translator
- Short labels are set `wrap="none"` and all text is shrunk x0.94 to absorb PPT-vs-browser metric drift (prevents mid-word wraps on short labels). If a long text box still re-wraps differently, widen its HTML box slightly and re-run.
- Colours are emitted as exact `srgbClr` hex from the HTML - no theme/palette guessing, so the .pptx matches the HTML precisely.

## Layout, type and colour

**All of it now lives in `house_style.md`** - canvas and margins, the scale-to-fill rule, the pt-vs-px type
scale, the palette, and the shape/structure rules. Do not keep a second copy here; earlier versions of this file
carried a px type scale that silently contradicted the pt spec.

The two things worth repeating because they are pipeline-specific:
- **`python scripts/typecheck.py <slide>.html`** mechanically checks the delivered pt sizes, colour, caps,
  tracking, dashes and canvas usage. Run it before extracting geometry. It knows about the 0.94 shrink; you
  will not get the sizes right by eye.
- Regenerate the .pptx from the same HTML after any change - never hand-patch a packed .pptx twice. Version
  `v01/v02/...` and park superseded builds in `_superseded/`.

## Translator gotchas learned on real decks (read before designing)
- **CSS borders are dropped** (`border`, `border-top`, `border-bottom`, `border-right`). For table row separators use `border-collapse:separate; border-spacing:1px` (real gaps show the canvas colour) plus spacer rows `<tr class="gap"><td colspan=N></td></tr>` between groups; for rules use a 1-1.5px `<div>` with a background.
- **Rule divs must not overlap filled rects drawn later** - a header underline placed at the first data row's top edge is hidden under that row's rectangle; put it inside the header row.
- **`vertical-align` on table cells is ignored** (text ends up top-aligned). For centred labels in tall cells, leave the cell empty and add an absolutely positioned `display:flex;justify-content:center` div at the cell's coordinates.
- **Flex centring is not read - `text-align:center` is.** Any centred label needs `text-align:center` explicitly.
- **Single-line text <= 34 chars gets `wrap="none"`** - lengthen the text or it will run out of its block.
- **Inline elements collapse**: `inline-block` spacing, swatch `<span>`s and `<sup>` are flattened into the parent text box. Use separate absolutely positioned divs for swatches / number columns; avoid superscripts (carry the note in the footnote text instead).
- **Marker divs inside a `.pgroup` lose their indent.** The dot survives as a shape, but the grouped text box
  spans the full group width, so the text ignores the per-row flex offset and renders over the dot. Seen on
  every slide of a real deck (Sept 2026). Put the bullet glyph in the paragraph text instead:
  `<div>&#8226;&nbsp; Item text</div>`.
- **CSS `::before` / `::after` pseudo-elements are dropped.** They render perfectly in the browser and are
  simply absent from the .pptx - square bullet markers built with `content:''` vanished entirely on a real
  build (Aug 2026) and were only caught at render-back. Use a real sibling element:
  `<div class="bi"><div class="bidot"></div><div class="bitext">...</div></div>`.
- **Inline `<svg>` is dropped entirely.** A growth axis drawn as `<svg><polyline/><circle/></svg>` rendered in
  the browser and disappeared completely in PowerPoint, leaving only the floating text labels. Rebuild with
  real divs (a 1px-tall div for a line, `border-radius:50%` divs for dots, sized/positioned inline), or
  rasterise to `<img>`.
- **Non-rectangular shapes (diagonals) are not translated**: give the div `.ppt-skip`, then inject an
  `<a:custGeom>` freeform into the slide XML (write a small python-pptx or lxml helper for this; the translator
  marks the div .ppt-skip so nothing overlaps it). (Since Sept 2026 the translator no longer emits full-slide
  background rectangles, so a freeform inserted first is no longer hidden behind one.)
- **Backgrounds are a slide property now, not a shape.** An opaque, square, borderless, canvas-sized div at the
  bottom of the stack is promoted to the slide's real `<p:bg>`. So author the canvas colour normally
  (`.slide{background:#F5F2EC}`) and do not draw a rectangle to fake it. A *later* full-bleed div (a scrim over
  a photo) is still emitted as a real shape, which is what you want.
- **Two-word labels in a narrow flex column collapse to one line and ride into the next column.** Confirmed on
  a real build (2026-09-08). Give label columns 20-30% more width than the browser needs, rather than sizing
  them to the visible text.
- **Legend swatches built as inline spans collapse into the label text box.** Confirmed on a real build
  (2026-09-08). Build each swatch and each label as its own absolutely positioned div - never rely on inline
  layout to keep a swatch and its label apart.
- **Percentages centred with flex inside bar segments render left-aligned.** Confirmed on a real build
  (2026-09-08). Add `text-align:center` explicitly - flex centring on the container is not enough (consistent
  with the flex-centring gotcha above).
- Headless Edge screenshots occasionally hang on exit: use a fresh `--user-data-dir` per run and a 90s `timeout`; the PNG is usually already written.

## When NOT to use this pipeline
If a near-identical prior slide exists, prefer cloning it (`scripts/clone_slide.py`) and swapping text - cheaper and inherits a human's layout. Build fresh via this pipeline when no close precedent exists.
