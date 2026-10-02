# deck-studio

A Claude Code skill that builds PowerPoint slides: dense, native and editable, on your own template or a plain
built-in one.

It exists because agents are bad at two things: laying out a slide blind in PowerPoint XML, and judging how much
content a slide should carry. It fixes the first with an HTML-first pipeline (design in the browser, translate to
native shapes and charts) and the second with a tiered set of example slides and a mechanical style checker.
The user reviews HTML mockups in a browser workroom before any .pptx exists.

## Install

Unzip anywhere and tell your agent: "read SKILL.md, then run `python scripts/setup.py`". Details, manual
steps and platform notes: `GUIDE.md`.

## Use

Ask for a deck, slides or a presentation. At the start of every new deck the agent asks which template to use:
hand it your company's or a client's .pptx/.potx and it takes the fonts, colours and layouts from there, or say
"plain" for the built-in neutral template. It then settles the brief, shows HTML mockups in the workroom,
iterates with you, and builds the .pptx when you say go. Each deck remembers its template
(`deck_template.json` in the deck folder), so revisions are rebuilt on the same one.

## What is inside

| | |
|---|---|
| `SKILL.md` | Entry point: the workflow, the rules, what to read when |
| `STYLE.md` | Canvas, type scale, palette roles, shapes, density tiers |
| `PIPELINE.md` | The loop, translatable HTML subset, native charts, chrome slides, adding to a deck, templates |
| `00_intake.md` | The questions to settle before building |
| `visual-formats.md` | Message type to visual format, with construction notes |
| `reference/` | Exhibits at every tier on invented companies, as HTML plus PowerPoint render; `MANIFEST.md` |
| `house.json` | Built-in defaults: plain template, Arial, neutral palette, default layout |
| `template/` | The plain template (stock 16:9 Office layouts); templates you switch in are copied here |
| `scripts/` | The pipeline; every script prints usage with `--help` |
| `tests/`, `evals/` | pytest suite, `scripts/selftest.py` acceptance run, behavioural evals |
| `docs/how_it_works.html` | The whole flow on one slide; `python scripts/workroom.py docs --open` |

## Tools

| Command | Does |
|---|---|
| `python scripts/setup.py` | Install everything and prove the pipeline once |
| `python scripts/doctor.py` | Check this machine |
| `python scripts/use_template.py <file.pptx> --deck <dir>` / `--plain` / `--resume <dir>` / `--show` | Choose the template for a deck, go back to the plain one, re-apply a deck's template, show the active one |
| `python scripts/typecheck.py <slide>.html` | Style checks and translator warnings |
| `python scripts/render_html.py <slide>.html <png>` | Render a slide HTML |
| `python scripts/workroom.py <dir> --open` | The review page the user looks at |
| `python scripts/build_deck.py <out>.pptx <a.html> ...` | Build content slides into a deck |
| `python scripts/render_slides.py <deck> <dir>` | Render the deck back through PowerPoint (or LibreOffice) |
| `python scripts/fontcheck.py <deck>` | Confirm only the template's font is in the file |
| `python scripts/chrome_slide.py <deck> --layout ... --title ...` | Cover, divider, end slides from the template's layouts |
| `python scripts/list_layouts.py`, `clone_slide.py`, `office_io.py`, `patch_fonts.py` | Layout names, slide cloning, unpack/pack, font patching |
| `python scripts/selftest.py [--render]` | Deterministic acceptance run |
| `python -m pytest tests -q` | Unit and end-to-end tests |

## Licence

MIT; see `LICENSE`. All scripts are original to this skill and depend only on the Python standard library,
python-pptx and Playwright. No brand template or font ships with it. No name, number or text in `reference/`
refers to a real company; every exhibit is invented.
