# GUIDE - install and first run

Written for the agent that receives this folder. Unzip it anywhere, then in Claude Code say:

> Read SKILL.md in <folder>, then run `python scripts/setup.py` from that folder and report the result.

`setup.py` installs the Python packages, a browser if none is present, any font faces bundled in `fonts/` (none
by default: the plain template uses Arial), copies the skill into `~/.claude/skills/deck-studio/` if it is not already there, runs the machine check
and a one-slide smoke build with a render-back, and writes `setup_report.txt` next to itself. It needs no admin
rights and is safe to run again. Send `setup_report.txt` back if anything says FAIL. Then **start a new Claude
Code session** so it picks up the skill, and try "make a slide on <anything>".

If you already have another skill that builds slides, keep only one of them active: they trigger on the same
requests, so the agent may pick the other one. Keep the general `pptx` skill if you have it: it reads and edits
existing decks, which this skill does not.

## What the machine needs

| Requirement | Windows | macOS | Linux |
|---|---|---|---|
| Python 3.9+ on PATH as `python` | yes | yes (`python3` may need an alias) | yes |
| A browser for rendering and geometry | Edge (present by default) or Chrome | Edge or Chrome, else `setup.py` installs Playwright's Chromium | same |
| A renderer for the mandatory .pptx render-back | desktop PowerPoint (COM) | PowerPoint for Mac, else LibreOffice (approximate) | LibreOffice (approximate) |
| Claude Code | to use it as a skill | | |

The Windows path with desktop PowerPoint is the tested one. macOS and Linux paths are implemented and
untested at the time of writing; on a Mac, run `setup.py` and check the report before relying on it.

## Manual steps, if you prefer them to setup.py

PowerShell:
```powershell
cd "$HOME\.claude\skills\deck-studio"          # after copying the folder there; SKILL.md must sit directly inside
python -m pip install -r requirements.txt
python scripts\doctor.py
```
bash / zsh:
```bash
cd ~/.claude/skills/deck-studio
python -m pip install -r requirements.txt
python scripts/doctor.py
```
`doctor.py` prints one line per check with a fix under every MISS. Fonts: the plain template uses Arial, so
there is nothing to install. If your own template uses a font that is not on the machine, install it for your
user (Windows: right-click, Install; macOS: double-click), or PowerPoint substitutes another. Then prove the
pipeline once:

```bash
python scripts/typecheck.py reference/T2_trend_stackedbar_driver_rail.html --quiet     # 0 fail -> PASS
python scripts/build_deck.py smoke.pptx reference/T2_trend_stackedbar_driver_rail.html  # DECK: 1 slides
python scripts/render_slides.py smoke.pptx smoke_png                                    # Exported 1 slides
python scripts/fontcheck.py smoke.pptx                                                  # CLEAN
```
Compare `smoke_png/slide01.png` with `reference/T2_trend_stackedbar_driver_rail.png`, then delete `smoke.pptx`
and `smoke_png/`. If PowerPoint shows a repair dialog when opening the file, stop and report.

## Using it

Any request to create slides, a deck, a presentation or a .pptx triggers the skill. What to expect:

1. The agent settles the brief and asks batched questions if the message, audience or evidence is unclear.
   For a new deck it also asks **which template to use** (send your own .pptx/.potx, or say "plain") and where
   to keep the deck, suggesting a folder next to your work; say yes or give a path.
2. It designs the slides as HTML and opens the workroom in your browser, every round: one page, every slide full size,
   with zoom and a contact-sheet view. Comment in the chat; it revises and reopens the page. Several rounds are
   normal. This is where to change the thinking. For the live review page (`workroom.py --serve`) a small
   local server runs in the background: stop it with Ctrl+C in its window, or it stops by itself after 2 hours
   without activity (`--idle-hours N` to change, 0 = never). Your comments are kept; the same command restarts it.
3. When you say go, it builds the .pptx on the deck's template, renders it back through PowerPoint, checks the
   fonts and hands it over. Later changes go into the HTML and are rebuilt; edits you make in PowerPoint are
   overwritten by the next rebuild.

Cover, divider and end slides come from the template's own layouts (`scripts/chrome_slide.py`).

**Templates:** the agent runs `python scripts/use_template.py <file> --deck <deck folder>`, which copies the
template into `template/`, derives the palette and font from its theme and prints them; the style checks then
enforce those colours. `--plain` goes back to the built-in template, `--show` names the active one, and
`--resume <deck folder>` re-applies the template a deck was started on. The choice is saved in
`<deck folder>/deck_template.json`. `house.json` (the built-in defaults) is never edited for this.

The template decides how the slides look, so a good one matters: a 16:9 file with a blank or near-blank content
layout, a title/cover and a section/divider layout, and theme colours and fonts set in the theme (not just
typed onto slides). A .potx works as well as a .pptx.

## The flow on one page

`docs/how_it_works.html` is a one-slide diagram of the whole flow (you, the agent, the scripts). Open it with
`python scripts/workroom.py docs --open`.

## Files

```
SKILL.md          entry point (the agent reads this first)     STYLE.md        canvas, type, colour, shapes, tiers
PIPELINE.md       the loop, HTML subset, charts, chrome, deck  00_intake.md    the five questions
visual-formats.md message type -> visual format                reference/      exhibits by tier + MANIFEST.md
house.json        built-in defaults (plain, Arial, neutral)     deck-studio.json the active template's settings (written by use_template.py)
template/         plain template + templates you switched in    fonts/          optional: brand font faces for setup.py to install
scripts/          the pipeline (every script has --help)        tests/, evals/  pytest suite, selftest, behavioural evals
docs/            how_it_works.html - the flow on one page
GUIDE.md README.md CHANGELOG.md LICENSE requirements.txt
```

## If something goes wrong

| What you see | What it is |
|---|---|
| The agent says it cannot open the workroom, or that a folder is not accessible | It is trying to use an in-app browser pane, which is sandboxed to one project folder. Tell it to run `python scripts/workroom.py <deck dir> --open`, which opens your normal browser on any platform. |
| You cannot find the slides the agent made | It asks where to keep each new deck and tells you the path. If it skipped that or built somewhere else, ask it where, and to move the deck next to your work. |
| A chart is an empty box | You opened a slide HTML directly. Chart boxes are drawn in the workroom and in the agent's render PNGs, not in the raw file: run `python scripts/workroom.py <deck dir> --open`. |
| The chart in the workroom is not quite the chart in the .pptx | Expected. The workroom draws a likeness from the chart data; PowerPoint draws the real thing. The render-back is the reference, which is why it is mandatory. |
| PowerPoint offers to repair the file | Stop and report it with the .pptx. Do not hand the deck on. |

## Known limits

- Images translate (`<img>`, background images; SVG rasterised). Remote http(s) images do not; download first.
- HTML tables become shapes, not native PowerPoint tables.
- Six chart types (column, bar, stacked variants, line). No waterfall or pie yet.
- LibreOffice renders are approximate; the PowerPoint render is the reference.
