# PIPELINE - how a slide goes from brief to native PowerPoint

Design every content slide in constrained HTML, iterate it with the user in the browser, then translate the
rendered layout into native, editable PowerPoint shapes on the deck's template (the user's own, or the plain one). Never hand-author slide XML:
an agent cannot lay out a slide blind, and it produces thin or corrupt slides.

## The loop

**Phase 1 - HTML, with the user (this is where the time goes)**

1. Settle the brief (`00_intake.md`). Declare the tier (`STYLE.md` section 6) and open the `reference/`
   exhibits at that tier.
2. Brainstorm the format from the message (`visual-formats.md` is the vocabulary), then write `<slide>.html`
   in the translatable subset below. Show mockups early and half-finished rather than late and polished.
3. `python scripts/typecheck.py <slide>.html`, then `python scripts/render_html.py <slide>.html <png>` and
   look at the PNG. Fix, repeat until clean.
4. `python scripts/workroom.py <deck-dir> --serve --open` and hand over (`WORKROOM.md`). **Stop here and take
   the user's comments** from `<deck-dir>/workroom_state.json`; several rounds are normal. Only the user's
   "go", a build they trigger from the page, or an explicit instruction to skip review, moves you to phase 2.

**Phase 2 - translate (fast and uneventful)**

5. `python scripts/build_deck.py <out>.pptx a.html b.html ...` extracts geometry from the browser, translates
   it, patches every typeface to the house font and packs onto the template. One slide:
   `extract_geometry.py` then `html_to_pptx.py`.
6. `python scripts/render_slides.py <out>.pptx <dir>` and **look at the PowerPoint render next to the HTML.**
   This gate is mandatory; several translator gaps looked perfect in the browser. `python scripts/fontcheck.py
   <out>.pptx` must print CLEAN.
7. Any change afterwards goes into the HTML and is rebuilt. Never hand-patch the .pptx; tell the user that
   manual edits in PowerPoint are overwritten by the next rebuild. Version files (`v01`, `v02`), never overwrite.

## Workroom server (live review page)

`python scripts/workroom.py <deck-dir> --serve --open` serves the workroom live: the user archives, reorders,
comments, builds versioned .pptx files and promotes good slides to `reference/` from the page; every comment
lands in the feedback ledger. **Read `WORKROOM.md`** for the state file the agent reads each round, the
`ledger.py note` routine and the distillation mapping.

## Chrome slides: cover, divider, agenda, end

These use the template's own layouts and placeholders, not HTML:

```bash
python scripts/chrome_slide.py deck.pptx --new --layout title --title "..."                # cover, new deck
python scripts/chrome_slide.py deck.pptx --layout divider --title "..."                     # append a divider
python scripts/chrome_slide.py deck.pptx --layout end --title "Thank you" --body "Name|mail|phone"   # if the template has one
```
Aliases `title | divider | end`; or a layout-name substring (`python scripts/list_layouts.py` prints them;
dashes may be typed as hyphens). The plain template has a title and a section layout but no end slide; many
company templates have all three. Unfilled placeholders are removed. Content slides built by `build_deck.py`
can be added into the same file with `clone_slide.py` (below).

## Boilerplate for a content slide

```html
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>...</title><style>
*{box-sizing:border-box;}
html,body{margin:0;padding:0;width:1280px;height:720px;font-family:Arial,sans-serif;background:#fff;}
.slide{width:1280px;height:720px;position:relative;overflow:hidden;background:#FFFFFF;color:#1E1E1E;}
.title{position:absolute;left:24px;top:24px;width:1160px;font-size:34px;font-weight:700;line-height:1.16;}
.subtitle{position:absolute;left:24px;top:112px;width:1160px;font-size:17px;font-style:italic;color:#595959;}
.source{position:absolute;left:24px;top:672px;width:1000px;font-size:11.5px;color:#8C8C8C;line-height:1.35;}
</style></head><body><div class="slide"> ... </div></body></html>
```
Replace `Arial` with the active template's font (`use_template.py --show`), e.g.
`font-family:'Georgia',Arial,sans-serif`, and the colours with the printed palette roles. A non-system brand
font needs its files: paste the output of
`python -c "import sys;sys.path.insert(0,'scripts');import config;print(config.font_face_css())"` into the
style block. When the template's master draws a logo and page number, the HTML draws neither. Layout: every
content slide lands on the default layout (`Blank` on the plain template; `use_template.py` picks the
blankest content layout of your own) unless `<body data-ppt-layout="...">` names another layout (alias, name
substring or `slideLayoutN.xml`).

## The translatable subset

| Translates | Becomes |
|---|---|
| Positioned `<div>` with a solid fill | rectangle (square corners; `border-radius:50%` for circles) |
| Text with inline `<b>`, `<i>`, `<span>` | one text box with styled runs; block children become paragraphs |
| `<div class="pgroup">` around 2+ lines | ONE text box, each block child a paragraph, gaps and line pitch measured from the render |
| Filled divs up to 8px thick, horizontal or vertical, no border or radius | line shapes (`p:cxnSp`) with that stroke weight, so the user gets a line, not a flat rectangle |
| Label + heading + body inside one `.pgroup` | ONE text box with paragraph spacing (see STYLE section 4) |
| `.slide` background colour | the slide's real background property |
| `<div class="ppt-chart" data-...>` | a native, editable PowerPoint chart (below) |
| `rgba()` fills | fills with alpha |
| `<img>` or a div with `background-image:url(...)` | a real picture (`p:pic`), see Images below |

Not translated, and the extractor warns when it sees them: rotation or any CSS transform, `::before` and
`::after` content, inline `<svg>`, CSS borders (use divs), `<table>` (translated
as shapes, not a native table), `box-shadow`, gradients (flattened to one colour), letter-spacing, flex
centring without `text-align:center`, swatch spans inside text. Non-rectangular shapes: give the div
`.ppt-skip` and add a freeform to the slide XML by hand afterwards.

Authoring rules the extractor cannot check for you:
- Give label columns 10-20% more width than the browser needs; PowerPoint's metrics differ slightly.
- Legend swatches and their labels are separate absolutely positioned divs, never inline spans.
- A header rule placed at the top edge of the first data row is hidden under that row's fill; put it inside the
  header row.
- `vertical-align` in table cells is ignored; use positioned divs for centred cell labels.
- Hanging indents: keep the bullet glyph in the paragraph text and use the group's padding; the translator does
  not read per-paragraph `text-indent`.
- Short single-line text is emitted without wrapping so it never breaks mid-word; give tight boxes a little slack.

## Images

`<img src="...">` and `background-image:url(...)` become real, editable pictures in the .pptx, embedded once per
deck (identical files are deduplicated by content hash) and interleaved in the correct z-order with shapes and
text. So a cover is a full-bleed `<img>` with `object-fit:cover`, a semi-transparent `rgba()` scrim div over it,
and white text on top.

- **Source:** absolute path, `file:///` URL, or a path relative to the HTML file. `http(s)` is not supported
  (the extractor warns and drops it); download first. Formats: png, jpg, jpeg, gif, bmp, webp, svg. **SVG is
  rasterised** to PNG at 2x the box size at extraction time, so the .pptx carries a bitmap, not vector art.
- **Fit:** `object-fit` on `<img>` and `background-size` on divs. `cover` crops (`a:srcRect`) honouring
  `object-position` / `background-position`; `contain` and `scale-down` letterbox the picture inside the box;
  `fill` (the `<img>` default) stretches; `none` keeps natural size, centred and cropped. State the fit
  explicitly; the default stretch is rarely what you want.
- **Circle crop:** `border-radius:50%` on a square box gives an ellipse-cropped picture (headshots).
- **Opacity:** `opacity` below 1 becomes picture transparency.
- **Where to get images:** the optional asset bank at `../asset_bank/` beside the skill folder (see `SKILL.md`
  rule 7; none ships with the skill). Its `find_asset.py` searches descriptions and tags; the `screenshot/`
  folder holds slide captures for slide-in-slide exhibits, and `snapshot.py` creates the folder on first use.

### Slide in slide

To show an existing slide as an exhibit inside a new one, capture it into the asset bank and place it as an
image:

```bash
python scripts/snapshot.py "<deck>.pptx" 7 --tags q3-review        # slide 7 of a deck -> asset bank screenshot/
python scripts/snapshot.py deck/slide_b.html                        # a mockup -> asset bank
python scripts/snapshot.py "<deck>.pptx" --all                      # every slide
python scripts/snapshot.py "<deck>.pptx" 7 --out qa/s7.png          # just a PNG, no manifest record
```
It prints the asset id and path; identical captures are deduplicated. Place it as an `<img>` at 16:9 with
`object-fit:contain`, a `#BFBFBF` div 1px larger behind it as the frame, and an 11.5px caption in `#8C8C8C`
underneath ("Exhibit: slide 7 of the Q3 deck"). Keep captures at 560px wide or more so their text stays legible.

## Native charts

```html
<div class="ppt-chart" data-chart="stacked-column"        <!-- stacked-column | column | stacked-bar | bar | line | line-markers -->
     data-categories="FY22|FY23|FY24|FY25|FY26B"
     data-series='[{"name":"EBITDA","values":[12.1,15.6,17.9,20.4,23.5],"color":"1E1E1E",
                    "labels":["17%","18%","16%","17%","17%"],"labelpos":"center","labelcolor":"FFFFFF","labelbold":true},
                   {"name":"Revenue above EBITDA","values":[59.3,71.4,94.1,102.6,114.5],"color":"B8B8B8",
                    "labels":["71","87","112","123","138"],"labelpos":"inside_end","labelcolor":"1E1E1E","labelbold":true}]'
     data-highlight='{"series":0,"point":2,"color":"E8833A"}'    <!-- optional: spotlight one point -->
     data-legend="top" data-valueaxis="hide" data-gridlines="hide"
     style="position:absolute;left:24px;top:200px;width:780px;height:430px;">chart</div>
```
The workroom and `render_html.py` draw an approximate picture of the chart from these same attributes
(`scripts/chart_preview.js`), so the review page shows a chart rather than an empty box; it is a likeness, and
the PowerPoint render-back is still the only evidence of the real one. Anything you put inside the div is
replaced by that preview and is never translated.

Per series: `color`, `labels` (strings, or `true` for values), `labelpos`, `labelcolor`, `labelbold`,
`labelsize`. Chart-level `data-valuemax="150"` pins the value axis to 0-150, so small multiples share one
honest scale (without it every chart auto-scales to its own data). `data-catlabelsize="8"` (pt) and
`data-catlabel-rotation="0"` keep category labels of a narrow chart horizontal and small. **On stacked charts only `center`, `inside_end` and `inside_base` are legal label positions**;
PowerPoint refuses to open a file with `outside_end` or `above` on a stacked series. The translator clamps and
warns, but author it correctly. Annotations (CAGR chip, callouts, a driver rail) are ordinary HTML outside the
chart box. Do not draw per-column overlays; use data labels.

## Adding a slide to an existing deck

```bash
python scripts/build_deck.py _new.pptx slide.html                # 1. build the new slide standalone
cp "deck v0.8.pptx" "deck v0.9.pptx"                             # 2. version forward, never overwrite
python scripts/office_io.py unpack "deck v0.9.pptx" _unp/
python scripts/clone_slide.py _new.pptx 1 _unp/                  # 3. clone in (appends; move its <p:sldId> to position)
python scripts/patch_fonts.py _unp/
python scripts/office_io.py pack _unp/ "deck v0.9.pptx"          # 4. pack (validated), then fontcheck + render-back
```
Never build into a file someone else is editing. If a near-identical slide already exists in a human-made
deck, cloning it and swapping the text is cheaper than building fresh.

## Templates

Asked for at the start of every new deck (`SKILL.md` -> Which template).
`python scripts/use_template.py <template.pptx> --deck <deck folder>` copies the template in, reads its theme,
maps the theme onto the palette roles (so `STYLE.md` section 3 and `typecheck.py` now mean the template's
colours), takes its font, detects whether its master draws chrome, picks a default layout, prints the palette
to design against, and records the choice in `<deck folder>/deck_template.json`.
`--plain --deck <deck folder>` chooses the plain built-in template. `--resume <deck folder>` re-applies a
deck's recorded template before a revision. `--show` prints the effective settings.
