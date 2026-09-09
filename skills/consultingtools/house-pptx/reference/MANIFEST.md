# Reference corpus - the depth and palette bar, by example

## How to use this (and how not to)

**These are a YARDSTICK, not a menu of formats and not templates to refill.**

- **DO** load them to calibrate how dense, how layered, and how coloured a house slide should be, and to borrow
  *construction techniques* (how a rail is laid out, how a stacked bar is annotated, how a table packs a bar
  into each row).
- **DO NOT** pick a slide's visual format by finding the nearest reference and refilling it. Choosing a format
  because an example exists is a defect.
- **The format is brainstormed fresh from the slide's message.** Derive the message, brainstorm the format that
  fits *it*, and only then come here to judge execution depth and colour. Never the reverse.
- **Only exception:** generic chrome (cover, divider, agenda, CV) carries no argument, so reusing the pattern is fine.

## The retrieval rule

Before designing, **declare the tier and view at least two references at that tier.** Skipping this is the single
most reliable predictor of a thin slide. Tiers are defined in `../depth_rubric.md` section 0.

Filenames are `T<tier>_<messagetype>_<slug>.<html|png>`, so you can pull what you need directly:

```bash
ls reference/T3_*                 # every dense exemplar
ls reference/*_trend_*            # every trajectory slide
ls reference/*_evidence_*         # every proof / case slide
```

**The corpus ships small on purpose** (two exhibits, both on a fictional company, both verified end to end).
If it is thin at your tier, **the external pack the slide sits beside is the reference** - a due-diligence
report, an information memorandum, bank material. Read that pack before designing; nothing in this folder
substitutes for it. And add your own house's best slides here as soon as you have them (see the end).

---

## Shipped exhibits

Each exists as HTML (how it is built) and as the PowerPoint render of the .pptx it produced (what it delivers).
Both pass `typecheck.py` with 0 fail / 0 warn and translate cleanly.

| File | Tier | Message type | Pattern | What to learn |
|---|---|---|---|---|
| `T2_evidence_table_quote_rail` | T2 | evidence / triangulation | Left: an evidence-row table (one brand per row, grouped by a domain spine, score, delta, N, and a stacked distribution bar in every row) with a separated, sand-filled total row. Right: a grey quote rail with three attributed verbatim quotes. | 24px margins and content filled to ~690px; the pt-correct type scale (24 / 12 / 10 / 9 / 8pt); the near-monochrome palette with warm sand used once, on the synthesis row; a table that is also a chart; `.pgroup`-wrapped quote cards; text living inside its own filled shape; flex columns absorbing slack. Also demonstrates the three metric-drift fixes (wide label column, positioned legend swatches, explicit `text-align:center`). |
| `T2_trend_stackedbar_driver_rail` | T2 | trend / decomposition | Left: a **native, editable** stacked column chart (EBITDA segment dark at the bottom with margin labels, revenue above in light grey with totals), a CAGR chip above, a unit line below. Right: a grey driver rail with three quantified drivers and a dark "read for the reader" box. | The `.ppt-chart` hybrid: real chart for the data, designed shapes around it; label positions legal on a stacked chart; a rail that earns the right-hand width instead of leaving it dead; a synthesis register in a dark fill with white text. |

Open the HTML when you need to see **how** something is built, not just what it looks like. Copy construction
patterns freely. **Do not copy the format** for a slide whose message is different - format comes from the
message (see the top of this file).

## What a T3 exhibit looks like (until you add one)

Top-tier due-diligence and investor packs share the same furniture, and it is the bar for T3: an exhibit on the
left ~70%, a grey quote or commentary rail on the right, a tag for pages that matter, a legend top-right, a
source line bottom-left, and 10+ information registers on the page. Near-monochrome discipline (white ~50%,
chroma ~2.5%) with one accent family. Two patterns worth building first, both written up in `../visual-formats.md`:

- **Evidence-row table**: one row per source (each report, each expert, each customer, each model), a value per
  column, a pale tint for direction, a comment on the right, then one visually separated synthesis row. Shows the
  spread and the disagreement before the conclusion.
- **Quote rail**: 3-6 verbatim, attributed quotes on a grey right panel, attached to almost any exhibit.

## Adding to the corpus

Drop a new exhibit here named `T<tier>_<messagetype>_<slug>.png` (and the `.html` if you built it through the
pipeline) and add a row above with its pattern and what to learn. Message types in use: `cover`, `credentials`,
`contrast`, `trend`, `composition`, `evidence`, `org`, `decomposition`, `comparison`, `roadmap`,
`operatingmodel`, `system`. Palette-correct, dense, real slides are the most valuable thing you can add -
especially as **HTML** exemplars, which show construction, not just appearance.

Keep `CORPUS_SHA256.txt` current (`sha256sum * > CORPUS_SHA256.txt` from inside this folder) if you distribute
the skill; it lets recipients confirm the corpus is exactly what you shipped.
