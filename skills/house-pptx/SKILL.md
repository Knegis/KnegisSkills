---
name: house-pptx
description: "Use this skill for ALL PowerPoint work where a consulting-grade, on-brand deck is wanted. It builds dense, native (editable) slides through an HTML-first pipeline onto a configurable 16:9 template, enforces a house standard (one font, a near-monochrome palette, a pt-based type scale, full-sentence titles) mechanically, and makes the human review HTML mockups before any .pptx exists. Trigger whenever the task involves creating, editing or touching a .pptx file, and on words like deck, slides, pitch, presentation, title slide, divider, or template. Brand settings (font, template, palette, wordmark) come from house.json in this folder."
---

# House PPTX Standard

Installing on a new machine? Follow `GUIDE.md` step by step. This skill builds PowerPoint decks that are dense, on-brand and native (real editable shapes and charts, not
pictures of slides). It is self-contained: it needs Python with python-pptx, pillow and playwright, a headless
Edge or Chrome, and desktop PowerPoint for the render-back gate. No other skill is required.

**What "on-brand" means is configured, not hardcoded.** `house.json` at the root holds the font, the template,
the palette roles, the wordmark and the acronym allowlist. Every script and every rule below reads from it.
The defaults are neutral (Arial, the generated `template/house_template.pptx`, a near-monochrome palette).
To adopt your own brand, edit `house.json` and drop your template in `template/`; nothing else changes.

## START HERE: how slides are built

> ## STOP: the one rule that matters most
> **Iterate HTML mockups with the user. Do not build the .pptx until they have seen them and said go.**
> Almost all of the work belongs in HTML, where changing the thinking is cheap - expect several rounds of
> comments before PowerPoint is mentioned. **Delivering a finished deck the user has never seen is a failed
> run, even if every quality gate passed.** Passing typecheck and the render-back gate proves you built it
> correctly, not that you built the right thing. Only go straight through if told to explicitly.
> Full sequence: `html_pipeline.md` -> "The build loop".

**Build slides via the HTML-first pipeline - do NOT hand-author OOXML shape geometry.** Agents cannot lay out a
slide blind in XML; it produces thin, broken, sometimes corrupt slides (proven repeatedly). Design in HTML where
the layout is visible and iterable, then translate it into native, editable PowerPoint shapes.

**Read in this order:**

| | Document | What it settles |
|---|---|---|
| 0 | **`00_intake.md`** | The question gate. Message, audience, density tier, evidence, constraints - settled *before* you build. Ask if uncertain; a thin brief is the root cause of most thin slides. |
| 1 | **`house_style.md`** | The design contract: canvas and margins, **use the whole slide and scale up to do it**, the pt-vs-px type scale, the palette, shape and language rules. |
| 2 | **`depth_rubric.md`** | The quality bar, and the **T1/T2/T3 density tiers**. "Thin" is a defined failure. |
| 3 | **`reference/MANIFEST.md`** | The tiered reference corpus. **Load and view 2+ exhibits at your tier before designing.** A yardstick for depth and colour, never a format menu. |
| 4 | **`visual-formats.md`** | Thinking vocabulary for choosing a format from a message. |
| 5 | **`html_pipeline.md`** | The build loop, the translatable HTML subset, and the translator gotchas. |

**Tools that check your work so you are not relying on memory:**
- `python scripts/doctor.py` - confirms this machine can build (template, font, browser, PowerPoint).
- `python scripts/typecheck.py <slide>.html` - delivered pt sizes, colour, caps, tracking, dashes, canvas usage,
  text collisions, panel overflow.
- `python scripts/workroom.py <dir> --open` - regenerates the deck's browser workroom, which is **what the human
  reviews**. Your own PNG renders are throwaway QA; delete them when done.

**Format choice vs execution - the most important behaviour.** Choose each slide's visual format by
BRAINSTORMING from its message (what best portrays *this* point), never by picking the closest reference and
refilling it. Fit-to-message, even novel, visuals are the goal - do not collapse this into pattern-matching.
References inform *execution* (depth, colour, construction technique), never *which format to use*. The only
slides you may reuse wholesale are generic chrome (title/divider/agenda/CV).
**Order: message -> brainstorm format -> THEN consult references for execution.**

The sections below (template handling, font patching, palette, layouts) are the **underlying mechanics** the
pipeline relies on, and apply to any direct hand-edits.

## Core rules (non-negotiable)

1. **Start from the configured template, never from scratch.** `scripts/config.py` resolves it from
   `HOUSE_PPTX_TEMPLATE`, `house-pptx.json`, or `house.json` -> `template`. The shipped default is the neutral
   `template/house_template.pptx` (regenerate with `python scripts/make_template.py`). Any 16:9 .pptx works;
   `python scripts/list_layouts.py` shows what it offers. Do not use `pptxgenjs` or build from blank unless
   the user explicitly asks.
2. **One font, the house font, on every element.** It is `house.json` -> `font.name` (default Arial). Templates
   ship with fallback fonts hardcoded in the theme, master and layouts; `scripts/patch_fonts.py` rewrites every
   `typeface` attribute to the house font, and the pipeline runs it for you. If you hand-write XML, always emit
   `<a:latin typeface="<house font>"/>` explicitly; never rely on theme inheritance.
3. **Stick to the house palette** in `house_style.md` section 4 (the roles are in `house.json` -> `palette`).
   Do not invent hex codes per deck, and do not use the template's own theme colours unless they are the brand.
4. **Keep 16:9 (13.33" x 7.50").** Never resize the canvas. The pipeline maps a 1280x720 px HTML canvas onto it.
5. **Preserve whatever footer system the template has.** Keep date / footer / slide-number placeholders unless
   told to remove them.
6. **Slide titles are full declarative sentences.** A reader should understand the slide from the title alone.
7. **Visual QA is mandatory**: render the built .pptx back through PowerPoint and look at it. The browser
   mockup is not evidence (`html_pipeline.md` -> phase 2).

## Template handling (read before first use)

- **A template may ship with no `ppt/slides/` directory** (layouts and masters only). The pipeline creates it.
  If you edit by hand, `mkdir -p unpacked/ppt/slides/_rels` before adding slides.
- **`<p:sldIdLst>` may be missing from `presentation.xml`.** The pipeline inserts it in the schema-correct
  position: after `<p:handoutMasterIdLst>` (or `<p:notesMasterIdLst>`, or `<p:sldMasterIdLst>`), before
  `<p:sldSz>`. If you hand-edit, keep that order or PowerPoint refuses the file.
- **Slide ids must be 256 <= id <= 2147483647.** `clone_slide.py` takes the lowest free id; do the same by hand.
- **Chrome the master already draws** (a logo, a page number) must not be drawn twice. If your template's master
  supplies them, set `template_supplies_chrome: true` in `house.json`; the translator then skips the `.wordmark`
  and `.pg` elements of the HTML. With the default neutral template they translate as ordinary text.

## Manual workflow (when you must hand-edit XML)

The pipeline does all of this for you. For a hand edit:

```bash
# 1. copy the template to a versioned working file
cp "$(python -c 'import sys;sys.path.insert(0,"scripts");import config;print(config.TEMPLATE)')" "<deck>_v1.pptx"
# 2. unpack, 3. force the house font
python scripts/office_io.py unpack "<deck>_v1.pptx" unpacked/
python scripts/patch_fonts.py unpacked/
# 4. edit slide XML (or clone a slide in: python scripts/clone_slide.py <src.pptx> <n> unpacked/)
# 5. re-check fonts, 6. pack (validated by python-pptx on the way out)
python scripts/patch_fonts.py unpacked/
python scripts/office_io.py pack unpacked/ "<deck>_v1.pptx"
```

## Palette

**The default house slide is near-monochrome.** White canvas, a grey ramp doing the structural work, **warm sand
`#CCBB9D` as the single secondary**, warmth from photography rather than fills. This is measured on the house's
reference deck: white 50% of pixels, saturated colour 2.5% and virtually all of it inside photographs.

| Role | Hex |
|---|---|
| Canvas | `#FFFFFF` (white, not cream) |
| Panel / soft fill | `#EEEEEE` (warm alternative `#DCD6D2`) |
| Text primary / secondary / caption | `#000000` `#1E1E1E` / `#585958` `#7E7F7E` / `#9F9A94` |
| Dark fill (white text on) | `#373737` |
| Chart and shape greys | `#585958` `#7E7F7E` `#B8B8B8` `#BEBFBE` |
| **Warm sand - the one secondary** | **`#CCBB9D`** |
| Deep navy - rare marker | `#1D405C` |
| Amber - spotlight only, often unused | `#FAA21B` |

**Text colour is black, white, or grey. Full stop.** Emphasis is **bold**, never colour. A coloured fill behind
black text is fine; a coloured run of type is a defect. **Charts** are greys and black, optionally warm sand for
a second series; never coral, red or bright blue for a series. Colour encodes meaning, never decoration. Make
data charts **real editable PPT charts** via the `.ppt-chart` convention in `html_pipeline.md`.

To rebrand, change the values under `palette` in `house.json` and keep the role names; the docs refer to roles.
Full rationale, type scale and canvas rules: **`house_style.md`**.

## Typography

**The house font on every element.** Colour black / white / grey only; emphasis is bold.

**The full type scale, and the px-to-pt conversion you must use when authoring HTML, is in `house_style.md`
section 3.** Do not size type from memory: the pipeline applies a 0.94 shrink, so **author px = target pt x 1.418**.
A 26px title believed to be 24pt actually delivers 18.5pt, which is how slides end up quietly small.

Defaults: **title 24pt** (34px), **body 10 or 12pt** (14 / 17px), **headers 10-12pt bold**, footnotes 8pt,
floor 7.5pt. Cover titles 54pt, dividers 40pt, hero stats 32pt. Delivered sizes must land on whole or .5pt.
`python scripts/typecheck.py <slide>.html` verifies all of this mechanically. Sentence case only, no ALL CAPS,
no letter-spacing, 5+ distinct type styles per content slide, one grouped text box per list.

## Layout selection

Layouts are resolved by **name** against whatever template is configured, so the pipeline works on any deck.
`python scripts/list_layouts.py` prints them. Choose one per slide with `<body data-ppt-layout="...">`: an alias
(`blank`, `title`, `divider`, `end`), a substring of a layout name, or `slideLayoutN.xml`. Default is the
blankest layout, which is what a fully designed HTML slide wants. See `layouts.md`.

## Visual format selection

Layouts position content; **formats** are how a message becomes a visual. `visual-formats.md` is a catalog of
~30 consulting visual patterns indexed by message type, each with construction notes in the house palette.
Default-to-bullets is a defect: every content slide that carries a real message should use a deliberate format
from, or justified against, that catalog. Sketch 2-3 candidates in HTML, render, pick, then build the winner.

## Slide reuse (clone_slide.py)

Prefer cloning a proven slide over building from a blank layout - cloned slides inherit the density and craft
of human-made decks. `scripts/clone_slide.py <source.pptx> <slide_no> <unpacked_dir>` clones across decks:
copies slide XML and media, maps the layout by name (or imports the source layout when unmatched), strips
unsupported parts (charts and OLE - rebuild those via `.ppt-chart`), and registers the slide in content types,
presentation rels and `<p:sldIdLst>`. Run `patch_fonts.py` after cloning.

## Rendering (render_slides.ps1)

`scripts/render_slides.ps1 -PptxPath <deck> -OutDir <dir>` exports every slide to PNG through PowerPoint COM
(Windows, desktop PowerPoint). It renders a temp copy and never closes a PowerPoint the user already had open.
Use it for the mandatory render-back gate and for contact sheets. Delete intermediate PNGs when done.
`scripts/render_html.ps1` renders a slide HTML to PNG through headless Edge for your own design loop.

## Pre-delivery checklist

- [ ] **Brief settled** per `00_intake.md`; density tier declared; 2+ references at that tier actually viewed
- [ ] `python scripts/typecheck.py` run on every slide HTML - zero FAILs, WARNs understood
- [ ] **Type scale honoured**: title ~24pt, body 10-12pt, nothing below 7.5pt (`house_style.md` section 3)
- [ ] **Canvas used**: 24px margins, content to ~690px, no dead quadrant - objects grown, not type shrunk
- [ ] **Palette is near-monochrome**: white canvas, grey ramp, warm sand as the only secondary; no amber fills
- [ ] **Font colour is black / white / grey ONLY**; emphasis is bold, never colour
- [ ] **No background rectangle** faking a canvas colour - the slide background is a slide property
- [ ] **Bulleted lists are ONE grouped text box** (`.pgroup`), never one text box per bullet
- [ ] Built on the configured template; all text is the house font; the font one-liner prints CLEAN
- [ ] Canvas is 16:9; footer / date / slide-number placeholders intact
- [ ] Every slide title is a full declarative sentence; hyphens not em dashes
- [ ] **The user saw the HTML mockups and approved them before the .pptx was built** (unless told to skip)
- [ ] **Render-back done**: the PowerPoint render viewed and compared to the HTML (browser is not evidence)
- [ ] `workroom.html` regenerated so the human has a current review page
- [ ] File versioned (`v0.1`, `v0.2`, ...), not overwriting prior work or someone else's lineage

## Final font-verification one-liner

After packing, confirm the deck carries only the house font:

```bash
python -c "
import zipfile, sys
sys.path.insert(0, 'scripts'); import config
common = ['Arial', 'Calibri', 'Calibri Light', 'Helvetica', 'Times New Roman', 'Arial Black']
banned = [f for f in common if f.lower() != config.FONT_NAME.lower()]
z = zipfile.ZipFile(sys.argv[1]); hits = []
for name in z.namelist():
    if name.endswith('.xml'):
        txt = z.read(name).decode('utf-8', errors='ignore')
        for b in banned:
            if f'typeface=\"{b}\"' in txt: hits.append((name, b))
print('CLEAN' if not hits else f'OFF-BRAND FONTS FOUND: {hits}')
" "<deck>_v1.pptx"
```

If anything other than `CLEAN` prints, unpack again, re-run `patch_fonts.py`, and repack.

## Gotchas

- **`labelpos: outside_end` or `above` on a STACKED chart makes PowerPoint refuse to open the file** while
  python-pptx reads it fine. Only `center`, `inside_end`, `inside_base` are legal there. The translator clamps
  and warns, but author it correctly.
- **Hiding a chart's value axis used to leave its gridlines behind**; the translator now clears both. Use
  `data-gridlines="hide"` if you only want the gridlines gone.
- **CSS `::before` markers, inline `<svg>` and CSS borders are dropped in translation.** Bullet glyphs go in
  the paragraph text; lines are 1px divs; rules are divs. Full list in `html_pipeline.md`.
- **Font metrics differ between browser and PowerPoint**: give label columns 20-30% more width than the browser
  needs, build legend swatches as separate positioned divs, and add `text-align:center` explicitly wherever a
  label must be centred. Confirmed on a real build; details in `html_pipeline.md`.
- **Headless Edge occasionally hangs on exit** with the PNG already written; the render scripts use a fresh
  profile and a 90s timeout for this reason.
- **The neutral template's non-blank layouts are functional but plain.** For branded title and divider
  layouts, bring your own template.
