# WORKROOM - the live review page, comments and the feedback ledger

Read this when a deck is under review with the user (phase 1, step 4 of `PIPELINE.md`).

`python scripts/workroom.py <deck-dir> --serve [--port 8765] [--open]` runs a local server (127.0.0.1 only)
and serves the workroom live. It is the default way to show slides; static mode (`workroom.py <deck-dir>
--open`) still works as a fallback. One server per deck: if 8765 is taken the server moves to the next free
port, and starting it again for a deck that is already served just reopens that server. The server:

- Watches the deck folder: new slide files appear automatically, edits show on refresh, and each slide's
  **round** counter increments when its file changes. Rounds-to-build is the skill's first-try metric.
- Lets the user **archive / restore** slides (archived slides leave the rail and the build set, nothing is
  deleted), **reorder** with arrows, **comment** per slide, and **Build deck**: all active slides in rail
  order go through `build_deck.py` into `<deck-dir>/build/<deck>_vNN.pptx` (never overwriting), then through
  `render_slides.py`; each built pane gets an **HTML | PowerPoint** toggle to compare the mockup with the real
  render.
- **Stops by itself** after 2 hours with no request and no build running (`--idle-hours N`, 0 = never), so a
  forgotten review round leaves no process behind. Closing the browser tab does not stop it; Ctrl+C does.
- Records everything in `<deck-dir>/workroom_state.json`. **Only the server writes this file, and only in
  response to the user's clicks.** The agent reads it: `slides.<file>.comments[]` (text, timestamp, round,
  `view`, optional `anchor` and `target`), `status`, `rounds`, `built_version`, and `builds[]` (version,
  slides, ok, log). Treat a comment as the user's instruction for the next round; treat a build the user
  triggered as their "go" for those slides.
- **Comment view.** Each comment says which pane the user was judging: `view` is `html` (the mockup) or
  `ppt` (the PowerPoint render). A `ppt` comment is almost always a translator issue: fix the translator or
  the HTML pattern that misled it, not the design, and log it as `translator`.
- **Pinned comments.** With Pin the user clicks a spot or drags a box on the slide. `anchor` is `{x,y,w,h}` in
  slide px on the 1280x720 canvas (w=h=0 for a point). In HTML view `target` names the element under the
  pin: `{tag, classes, id, text, box}` where `box` is the element's own slide-px rectangle. Use `target` to
  find the element in the HTML (class and text excerpt), and `anchor` versus `target.box` to read intent:
  a box drawn wider than the element usually means "make it this size"; a point on a word means that text.
  Pins show as numbers on the preview and in the comment list; hovering a pin shows the note; the user can
  hide them. Comments without a pin are still plain text. Pin also works from the grid (contact-sheet) zoom:
  Archive/Restore and Pin are the two actions kept on the one-line caption there (the user works mostly in grid),
  and the note popover opens on the card.
- **Edit and remove.** Every comment (list entry and pin tooltip) has edit and a red x. Comments carry a
  stable `cid`; ledger row ids are `<deck>:<slide>:<cid>`, so removing one comment never moves another's
  category or fix. A removed comment drops out of the ledger on the next sync; an edited one shows `edited`
  and keeps its pin. Never edit or remove the user's comments yourself; the ledger `note` is your side.
- Images in slides preview through the server; the .pptx build is unaffected by preview.

- **Promote** (on built panes): the user files a slide they like into `reference/` as
  `T<tier>_<msgtype>_<slug>.html` + the PowerPoint render `.png`, with a MANIFEST row and hash lines. The
  next deck's agent sees it as an exhibit. The pane shows a `reference: ...` badge.
- **Rounds to build** in the header: mean rounds before the first build, over built slides. This is the
  first-try metric; lower is better.

**Feedback ledger.** Every comment ends up in `feedback/ledger.jsonl` (the server registers the deck on start
and syncs after each comment and build). The agent's half of the record is written with:

```bash
python scripts/ledger.py show --uncategorised                 # what the user said that has no response yet
python scripts/ledger.py note "<deck>:<slide>:<cid>" --category density --fix "grew the chart to 620px, added source line"
```
Categories: `format` (wrong visual for the message), `density` (thin or crowded), `type` (sizes, hierarchy),
`colour`, `translator` (browser and PowerPoint differ), `content` (numbers, wording), `other`.
`feedback/summary.md` is regenerated on every sync. Every few decks the summary is distilled: a recurring
`translator` item becomes an extractor warning or a `typecheck.py` rule, a recurring `type`/`colour`/`density`
item becomes a sentence in `STYLE.md`, a recurring `format` item becomes an exhibit or a `visual-formats.md`
row, a recurring behaviour becomes an eval.

Agent routine per round: read the state file (`ledger.py show --uncategorised` prints pins compactly as
`[view] @(x,y wxh) tag.class "text"`), revise the HTML for commented slides, run `typecheck.py`,
record a `ledger.py note` for each comment you acted on, tell the user what changed and that the page is
refreshed. Do not restart the server between rounds unless it stopped on idle (then rerun the same command; state is kept); do not regenerate `workroom.html` in serve mode (the
page is dynamic).

**Analysis tab (data provenance).** The served page has `Slides | Analysis`. Analysis lists every slide with a
thumbnail on the left and, on the right, the source sheet drawn like Excel: values, formula bar, precedents in
blue on click, cells shown on the slide highlighted with the marker number. It reads `<slide>.analysis.json`
beside the slide HTML, which you write whenever a figure comes from a file:

```json
{"sources":[{"id":"S1","file":"C:/.../databook.xlsx","sheet":"Net debt","range":"B4:E45","read":"2026-09-19T17:05"}],
 "figures":[{"marker":1,"source":"S1","cell":"D9","shown":"434.3","label":"Long-term debt, Dec-25",
             "transform":"x -1, rounded to 0.1","box":{"x":448,"y":236,"w":110,"h":30}}],
 "notes":["Signs flipped: databook stores debt negative; slide shows debt positive."]}
```
`box` is the slide-pixel rectangle of the element showing the figure (same convention as pins). `cell` is the
workbook cell the figure was read from; a figure you computed yourself lists the cells it used (`"E45,D45"`)
and says so in `transform`. Put every sign flip, unit change and rounding in `transform` or `notes`: those are
the steps the user cannot see in the sheet. A slide with no file-based figures needs no sidecar and shows as
one line. The tab reads workbooks read-only through openpyxl; nothing is written back.
