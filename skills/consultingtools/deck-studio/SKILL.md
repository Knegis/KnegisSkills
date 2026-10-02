---
name: deck-studio
description: "Build new PowerPoint slides from a brief: dense, native and editable, on the user's own template or a plain built-in one, through an HTML-first pipeline that shows the user HTML mockups in a browser workroom before any .pptx exists. Trigger on requests to make or create a slide, slides, a deck, a presentation, a pitch, a one-pager or a .pptx (including 'make a slide on X' and 'turn this into a slide'), and on 'use this template'. Out of scope: reading, summarising or editing an existing .pptx (defer to a general pptx skill); editing happens in the HTML and the .pptx is regenerated."
---

# deck-studio

Builds slides that are dense, consistent and native (real shapes and charts, not pictures), on whichever
PowerPoint template the user chooses. The template decides the font, the colours and the layouts;
`scripts/use_template.py` switches it. Without a template of their own the user gets the plain built-in one
(Arial, a neutral grey palette with one blue accent). First time on a machine: `python scripts/setup.py`
(see `GUIDE.md`).

## The workflow, and the one rule

**Design and iterate in HTML, in the browser workroom, with the user. Convert to .pptx when they are happy or
ask for it.** Do not hand over a .pptx the user has not seen as HTML unless they told you to skip the review.
The HTML round is where the thinking changes cheaply; translation is mechanical and should be uneventful.

```bash
# 0. settle the brief (00_intake.md) AND the template (below) - ask if unclear
python scripts/use_template.py <their.pptx> --deck deck    # or: --plain --deck deck. Prints the palette to design against
# 1. design each slide as constrained HTML (PIPELINE.md); look at reference/ exhibits at your tier
python scripts/typecheck.py deck/slide_a.html                        # 2. mechanical checks + translator warnings
python scripts/render_html.py deck/slide_a.html qa/a.png             #    look at your own work
python scripts/workroom.py deck --serve --open                       # 3. show the user in the workroom, every round. STOP. Iterate.
#    Read deck/workroom_state.json at the start of every round: the user's comments, archive choices and
#    builds live there (PIPELINE.md -> Workroom server). Never write that file yourself. After acting on a
#    comment, record what you changed: python scripts/ledger.py note "<id>" --category <cat> --fix "..."
python scripts/build_deck.py out_v01.pptx deck/slide_a.html deck/slide_b.html   # 4. after the go
python scripts/render_slides.py out_v01.pptx qa/ppt                  # 5. MANDATORY: view and compare to the HTML
python scripts/fontcheck.py out_v01.pptx                             #    must print CLEAN
python scripts/chrome_slide.py out_v01.pptx --at 1 --layout title --title "..."   # covers/dividers: template layouts
```

**Which template: ask at the start of every new deck.** Run `python scripts/use_template.py --show` first; its
first line names the active template. Then, in the same batched message as the intake questions, ask:
"Which PowerPoint template should this deck use? Send me your own .pptx or .potx (your company's or the
client's) and I will take its fonts, colours and layouts from it, or say 'plain' for the built-in neutral
template. The active one right now is <name>." Before writing any slide HTML, apply the answer with
`use_template.py <file> --deck <deck folder>` or `use_template.py --plain --deck <deck folder>`, and design
against the palette it prints (the role names in `STYLE.md` then mean those colours). The choice is recorded
in `<deck folder>/deck_template.json`. **When you come back to an existing deck**, do not ask again: run
`use_template.py --resume <deck folder>` before building, so the deck is rebuilt on its own template even if
another deck switched the template since. A request mid-deck like "use this template instead" is a switch:
run it with `--deck` and tell the user the slides will be re-checked against the new palette.

**Where the deck lives: ask once per new deck.** Before writing the first file of a new deck, ask the user
where to keep it, with a recommendation: a `<short-deck-name>/` folder inside the folder they are working in
(give the full path). Ask it in the same batched message as the intake and template questions, not as a
round of its own. Everything for the deck goes there: slide HTML, `workroom_state.json`, `deck_template.json`,
`build/` versions. For a revision or a new slide in an existing deck, find its folder (ask only if you
cannot) instead of asking again. Never build in a scratch or temp folder of your own.

**Every time you show slides, show them in the workroom**, from the first mockup on. Start it once per deck, in
the background (it keeps running): `python <this skill's folder>/scripts/workroom.py <deck folder> --serve --open`.
It prints its URL; tell the user. If port 8765 is taken it moves to the next free port, and if a server for that
deck is already running it reopens that one, so running the command again is always safe (also after it has
stopped itself when idle). On later rounds tell the user to refresh the page rather than restarting anything.
The scripts live in this skill's folder: call them by full path while working in the user's deck folder.
`--open` opens their real browser; an in-app browser pane cannot read files outside its project folder, so
never review through one.

## Read when

| Document | Read it when |
|---|---|
| `00_intake.md` | Before designing anything: the questions that make or break a slide |
| `STYLE.md` | Before authoring HTML: canvas, type scale (author px = pt x 1.418), palette roles, shapes, tiers |
| `PIPELINE.md` | Before authoring HTML: the loop, boilerplate, translatable subset, native charts, chrome slides, adding to a deck, templates |
| `reference/MANIFEST.md` | Before designing: the exhibits at your tier, a yardstick for depth and never a menu of formats |
| `WORKROOM.md` | When the deck is under review: the live page, the state file you read each round, `ledger.py note`, promote |
| `visual-formats.md` | When choosing a format: message type to candidate visuals, with construction notes |
| `GUIDE.md`, `README.md` | Install, machine setup, tool table; not needed to build a slide |

## Rules that do not bend

1. **Format comes from the message.** Brainstorm what portrays this point, then consult references for depth
   and construction. Picking a format because an exhibit exists is a defect. Title plus bullets is a defect.
2. **Settle the brief and the template before building.** Message as one declarative sentence, audience, tier,
   evidence, constraints, template. Ask batched questions when the answer changes the slide; decide routine
   matters yourself. **Always ask which tier the user wants (T1 / T2 / T3 or in between) with a one-line
   explanation of each**, unless they named it already (`00_intake.md` item 3), **and which template** (above).
3. **Never invent a number, client or result.** Ask, or mark it `[ILLUSTRATIVE]` on the slide. A figure taken
   from a file gets a sidecar `<slide>.analysis.json` (cell, shown value, transform; schema in `WORKROOM.md`)
   so the workroom Analysis tab can show the source sheet next to the slide.
4. **Type in points, colour by role, text in black/white/grey, emphasis by bold**, per `STYLE.md`.
   `typecheck.py` enforces it; do not size type from memory.
5. **Fill the canvas**: 24px margins, content to ~690px; grow objects and type before adding whitespace.
6. **Titles are full declarative sentences. Hyphens, not em dashes. Sentence case. No emojis.**
7. **Native charts** via `.ppt-chart`; one `.pgroup` text box per list; images via `<img>` (translated to real
   pictures, `PIPELINE.md` -> Images). If an asset bank sits next to this skill folder (`../asset_bank/`),
   **query it before drawing or sourcing any image:** `python ../asset_bank/find_asset.py <words>`. Without
   one, ask the user for the image file. Reference the file by absolute path.
8. **Chrome slides use the template's layouts** (`chrome_slide.py`). When the template's master draws a logo
   or page number (`use_template.py` detects it), the HTML draws none.
9. **Render-back is mandatory.** The browser mockup is not evidence of the .pptx. View the PowerPoint render.
10. **Version, never overwrite.** `v01`, `v02`; never build into a file someone else is editing.

## Before handing over

- [ ] The user chose the template and it is recorded in `deck_template.json`
- [ ] The user saw the HTML in the workroom and said go (or told you to skip)
- [ ] `typecheck.py` zero FAILs on every slide; warnings understood
- [ ] `fontcheck.py` prints CLEAN; render-back viewed and compared
- [ ] Titles are sentences; sources present wherever there is data; nothing `[ILLUSTRATIVE]` left unflagged
- [ ] Workroom regenerated; files versioned

## Tools

`setup.py` install everything | `doctor.py` check the machine | `use_template.py` choose the template
(`--show`, `--plain`, `--deck`, `--resume`) | `typecheck.py` style + translator warnings | `render_html.py` HTML
to PNG | `workroom.py` review page (`--serve` for the live one) | `build_deck.py` HTML to .pptx |
`render_slides.py` .pptx to PNGs | `snapshot.py` capture a slide into the asset bank (slide in slide) |
`fontcheck.py` font audit | `chrome_slide.py` cover/divider/end | `list_layouts.py` | `clone_slide.py` |
`office_io.py` unpack/pack | `patch_fonts.py` | `selftest.py`. Every script prints usage with `--help`.
