# house-pptx

A Claude Code skill for building PowerPoint slides that are dense, on-brand, and native (real editable shapes
and charts, not pictures of slides).

It exists because agents are bad at two specific things: laying out a slide blind in OOXML, and judging how
much content a slide should carry. This skill fixes the first with an HTML-first pipeline, and the second with
a tiered reference corpus and a mechanical style checker. It is brand-agnostic: font, template, palette and
wordmark live in `house.json`.

---

## Install

1. **Put the folder in your skills directory**, e.g. `~/.claude/skills/house-pptx/`. No other skill is needed.
2. **Install the Python dependencies:** `python -m pip install -r requirements.txt`
   (An agent setting this up should follow `GUIDE.md`, which has a verified expected output per step.)
3. **Check the machine:**
   ```bash
   python scripts/doctor.py
   ```
   It tells you exactly what is missing and how to fix it. Out of the box it resolves to the shipped neutral
   template and Arial, so it should pass on any Windows machine with Edge and PowerPoint.

### Bring your own brand

Edit `house.json`:

```json
{
  "brand": "Acme",
  "wordmark_text": "Acme",
  "template_supplies_chrome": false,
  "font": {"name": "Acme Sans",
           "faces": {"regular": "AcmeSans-Regular.otf", "bold": "AcmeSans-Bold.otf",
                     "italic": "AcmeSans-Italic.otf", "bolditalic": "AcmeSans-BoldItalic.otf"}},
  "template": "template/acme_template.pptx",
  "palette": {"...": "keep the role names, change the values"}
}
```

- **Template**: any 16:9 .pptx. Drop it in `template/` or point `template` at it. `python scripts/list_layouts.py`
  shows its layouts; slides land on the blankest one unless you choose otherwise. If its master already draws a
  logo and page number, set `template_supplies_chrome` to `true` so the HTML wordmark is not drawn twice.
- **Font**: a system font needs only `name`. A brand font needs the four face filenames and, if they are not in
  a standard fonts folder, `HOUSE_PPTX_FONTDIR` (or `font_dir` in a `house-pptx.json`).
- **Per-machine paths** go in `house-pptx.json` next to this README or `~/.house-pptx.json`, or in the env vars
  `HOUSE_PPTX_TEMPLATE` and `HOUSE_PPTX_FONTDIR`. `house.json` is the brand; `house-pptx.json` is the machine.

**You also need desktop PowerPoint (Windows).** The pipeline's final gate renders the built .pptx through
PowerPoint COM and compares it to the design. There is no LibreOffice fallback configured, and skipping the gate
is how broken slides ship - several translator bugs looked perfect in the browser and were only caught there.

---

## What the agent reads, in order

| Document | What it settles |
|---|---|
| `00_intake.md` | The question gate - message, audience, density tier, evidence, constraints, settled before building |
| `house_style.md` | Canvas, the scale-to-fill rule, the pt/px type scale, the palette, shape and language rules |
| `depth_rubric.md` | The quality bar and the T1/T2/T3 density tiers |
| `reference/MANIFEST.md` | The tagged reference corpus - view 2+ at your tier before designing |
| `visual-formats.md` | Vocabulary for choosing a format from a message |
| `html_pipeline.md` | The build loop, the translatable HTML subset, the translator gotchas |
| `layouts.md` | How layouts are chosen on whatever template is configured |

`SKILL.md` is the entry point and links all of these.

## Tools

| Command | What it does |
|---|---|
| `python scripts/doctor.py` | Check this machine can build decks |
| `python scripts/make_template.py` | Regenerate the neutral 16:9 template |
| `python scripts/list_layouts.py [tpl]` | List a template's layouts and the names the pipeline matches on |
| `python scripts/typecheck.py <slide>.html` | Enforce the house style mechanically - delivered pt sizes, colour, caps, tracking, dashes, canvas usage, collisions |
| `python scripts/workroom.py <dir> --open` | Regenerate the deck's browser review page (every slide, full size, zoom + contact-sheet grid) |
| `python scripts/extract_geometry.py <slide>.html geom.json` | Read computed layout out of the browser |
| `python scripts/html_to_pptx.py geom.json out.pptx` | Translate to native PowerPoint shapes on the template |
| `python scripts/build_deck.py out.pptx a.html b.html ...` | Build a multi-slide deck in one pass |
| `python scripts/clone_slide.py src.pptx N unpacked/` | Clone a slide from another deck |
| `python scripts/office_io.py unpack\|pack ...` | Unpack / pack a .pptx (pack validates with python-pptx) |
| `python scripts/patch_fonts.py unpacked/` | Force every typeface to the house font |
| `powershell -File scripts/render_html.ps1 ...` | Render a slide HTML to PNG |
| `powershell -File scripts/render_slides.ps1 ...` | Render a built .pptx to PNGs via PowerPoint |

## The loop, in one screen

```bash
# 0. settle the brief (00_intake.md) - ask if the message, tier or evidence is unclear
# 1. brainstorm the format from the message; design it in constrained HTML
python scripts/typecheck.py deck/slide_A.html            # 2a. mechanical check
powershell -File scripts/render_html.ps1 -HtmlPath deck/slide_A.html -OutPath qa/a.png   # 2b. look at it
python scripts/workroom.py deck --open                   # 3. show the human, in the browser. STOP. Iterate.
python scripts/build_deck.py out.pptx deck/slide_A.html deck/slide_B.html   # 4-5. only after approval
powershell -File scripts/render_slides.ps1 -PptxPath out.pptx -OutDir qa/ppt   # 6. MANDATORY: view and compare
```

## Two things people get wrong

**Font sizes.** Sizes are specified in PowerPoint points but authored in CSS pixels, and the translator applies a
6% shrink. **Author px = target pt x 1.418.** A 26px title is not 24pt, it is 18.5pt. The table is in
`house_style.md` section 3 and `typecheck.py` verifies it.

**Format selection.** The reference corpus is a yardstick for *depth and colour*, never a menu of formats. Choose
the visual by reasoning from the slide's message; consult references afterwards to judge whether your execution
is rich enough. Picking a format because a reference exists is the defect this skill most wants to prevent.

## The reference corpus

`reference/` ships with two verified exhibits on a fictional company (HTML plus PowerPoint render). It is
deliberately small: the most valuable thing you can add is your own house's best slides, tagged by tier and
message type as described in `reference/MANIFEST.md`. Nothing in this folder is confidential.

## Licence and provenance

All scripts in `scripts/` are original to this skill and depend only on the Python standard library,
python-pptx, pillow and playwright. No third-party skill code is included.
