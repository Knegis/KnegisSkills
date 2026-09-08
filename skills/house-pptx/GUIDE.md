# GUIDE - install and first run, written for an agent to execute

This is the step-by-step setup for the `house-pptx` skill. Each step has a command and the exact output that
means it worked. Run them in order from the skill folder. Stop and report at the first step that does not
match; do not improvise around a failure.

## What you need on the machine

| Requirement | Why | Check |
|---|---|---|
| Windows 10/11 | the two render scripts are PowerShell + PowerPoint COM | `ver` |
| Python 3.9+ on PATH as `python` | all scripts | `python --version` |
| Microsoft Edge (or Chrome) | headless rendering and geometry extraction | doctor.py checks |
| Desktop PowerPoint | the mandatory render-back gate | doctor.py checks |
| Claude Code | to use it as a skill | `claude --version` |

macOS / Linux: the Python pipeline runs, but `render_html.ps1` and `render_slides.ps1` do not. You would need
your own render step (Playwright screenshot for HTML; LibreOffice `soffice --convert-to pdf` for the .pptx).
Not configured or tested.

## Step 1 - put the folder in place

Unzip so that `SKILL.md` sits directly at:

```
%USERPROFILE%\.claude\skills\house-pptx\SKILL.md
```

Claude Code scans `~/.claude/skills/*/SKILL.md`. A nested folder (`house-pptx/house-pptx/SKILL.md`) is not found.

## Step 2 - install the Python packages

```
cd %USERPROFILE%\.claude\skills\house-pptx
python -m pip install -r requirements.txt
```

Expected: pip ends with `Successfully installed ...` or reports the packages are already satisfied.
Playwright drives the system Edge (`channel="msedge"`); no `playwright install` download is needed when Edge
is present. If Edge is absent, run `python -m playwright install chromium` once.

## Step 3 - check the machine

```
python scripts\doctor.py
```

Expected: every line `[  OK  ]` except possibly `[ WARN ] reference corpus`, and the last line
`Usable, with the warnings above.` or `All good - you can build decks on this machine.`
Exit code 0. Any `[ MISS ]` line prints a fix under it; apply it and re-run.

## Step 4 - prove the pipeline end to end (about one minute)

```
python scripts\typecheck.py reference\T2_trend_stackedbar_driver_rail.html --quiet
```
Expected: `0 fail / 0 warn   -> PASS`

```
python scripts\build_deck.py smoke.pptx reference\T2_trend_stackedbar_driver_rail.html --approved
```
Expected, last lines: `  slide 1: T2_trend_stackedbar_driver_rail.html | 1 charts` then `DECK: 1 slides -> smoke.pptx`

```
powershell -NoProfile -File scripts\render_slides.ps1 -PptxPath smoke.pptx -OutDir smoke_png
```
Expected: `Exported 1 slides to ...\smoke_png`. Open `smoke_png\slide01.png` and compare it with
`reference\T2_trend_stackedbar_driver_rail.png`: same layout, same chart, same fonts. Then delete `smoke.pptx`,
`smoke_png\` and `_deck_work\`.

If PowerPoint shows a repair dialog when you open `smoke.pptx` by hand, stop and report; that is a real failure.

## Step 5 - brand it (optional, but do it before real work)

Edit `house.json`:

1. `font.name`: your brand font's family name. Leave `faces` empty for a font installed system-wide; for a font
   shipped as files, list the four filenames and set `HOUSE_PPTX_FONTDIR` to their folder.
2. `template`: drop your 16:9 .pptx into `template\` and put its path here (relative to the skill folder).
   Run `python scripts\list_layouts.py` to see its layouts; check `template_supplies_chrome` if its master
   already draws a logo and page number.
3. `wordmark_text`: what the HTML boilerplate writes top-right of content slides. Leave empty for none.
4. `palette`: change values, keep the role names.
5. `acronyms_extra`: brand names legitimately written in capitals.

Then re-run Step 3 and Step 4. `doctor.py` confirms the template is 16:9 and opens; the smoke build confirms the
font and layout resolution on your template.

## Step 6 - use it

In Claude Code, any request that mentions a deck, slides, a presentation or a .pptx file triggers the skill.
The agent reads `SKILL.md` first, which links everything else in order. The core behaviour to expect:

1. It settles the brief (`00_intake.md`) and asks batched questions if the message, audience or evidence is unclear.
2. It designs slides as HTML and shows you `workroom.html` in the browser. **It should stop here and wait for
   your comments.** Several rounds are normal.
3. Only when you say go does it build the .pptx, render it back through PowerPoint, and hand it over.

If the agent hands you a .pptx you never saw as HTML, that is a failed run by the skill's own definition;
say so and it will restart at step 2.

## Files, for orientation

```
SKILL.md              entry point (Claude reads this first)
GUIDE.md              this file
README.md             overview, install, tool table, the loop in one screen
requirements.txt      Python packages
house.json            brand settings: font, template, palette, wordmark
00_intake.md          the question gate
house_style.md        canvas, type scale, palette, shape and language rules
depth_rubric.md       quality bar and density tiers
visual-formats.md     message -> visual format catalog
html_pipeline.md      the build loop, translatable HTML subset, translator gotchas
layouts.md            choosing a layout on any template
reference/            two verified exhibits (HTML + PowerPoint render) + MANIFEST.md
template/             the neutral 16:9 template (regenerate: scripts\make_template.py)
scripts/              the pipeline; every script has a usage docstring at the top
evals/evals.json      three sample tasks to test the skill against
```

## Known limits

- Windows-only rendering (Edge + PowerPoint COM). See the note under "What you need".
- The neutral template's title and section layouts are plain. Bring your own template for branded chrome.
- The reference corpus is two slides. Add your house's best slides per `reference/MANIFEST.md`; the skill gets
  noticeably better at judging density when it has examples at every tier.
- Fonts render slightly differently in PowerPoint than in the browser. The translator absorbs most of it, and
  `html_pipeline.md` lists the three authoring rules that handle the rest.
