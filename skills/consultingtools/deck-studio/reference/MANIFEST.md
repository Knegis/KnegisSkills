# Reference corpus - the depth bar, by example

**A yardstick, not a menu.** Use these to judge how dense, how layered and how coloured a slide should
be, and to borrow construction technique (how a rail is laid out, how a table packs a bar into each row). Do
not pick a slide's format by finding the nearest exhibit and refilling it: derive the message first, brainstorm
the format that fits it, then come here to judge execution. The only exception is chrome (cover, divider, end),
which carries no argument.

**Before designing, declare the tier (T1 / T2 / T3, see `../STYLE.md` section 6) and open the exhibits at that
tier.** If the deck sits beside an external pack (a due-diligence report, an information memorandum, bank
material), that pack sets the bar as well; read it first.

Every exhibit is on an invented company with invented numbers, built through this pipeline on the plain
template, and shipped as the HTML that built it plus the PowerPoint render it produced. No name, number or text
here comes from a real client, deal or internal deck. `CORPUS_SHA256.txt` lists the shipped hashes.

| File | Tier | Message type | What it is | What to learn |
|---|---|---|---|---|
| `T1_cover_title.png` | T1 | cover | Cover on the plain template's "Title Slide" layout, made with `scripts/chrome_slide.py` (no HTML). | Chrome slides use the template's own layouts and placeholders; the pipeline is for content slides. |
| `T1_divider_section.png` | T1 | divider | Section divider on the plain template's "Section Header" layout with a one-line subtitle, also via `chrome_slide.py`. | Same. On your own template these look exactly as its designer intended, which is the point. |
| `T1_statement_hero_stat` | T1 | statement | One number (94% on time) given room: hero figure, a two-line read, a three-row comparison, a dark-on-grey read-for-the-reader band, source. | Sparse by design: five registers, large type, nothing decorative. The band text is one paragraph with a bold lead-in. |
| `T2_trend_stackedbar_driver_rail` | T2 | trend / decomposition | Native editable stacked column (EBITDA dark at the bottom with margin labels, revenue above), a CAGR chip, a driver rail with three quantified drivers and a dark synthesis box. | The `.ppt-chart` hybrid: a real chart for the data, designed shapes around it; label positions legal on a stacked chart; a rail that earns its width. |
| `T2_evidence_table_quote_rail` | T2 | evidence | Quality-audit scores by plant: evidence-row table grouped by region with a stacked outcome bar in every row and a secondary-filled total row; a quote rail with three attributed quotes. | A table that is also a chart; positioned legend swatches; `.pgroup` quote cards; text inside its own filled shape; flex columns absorbing slack. |
| `T3_evidence_source_rows_commentary` | T3 | evidence / triangulation | Market-size triangulation: one row per source with value, growth, basis and comment, pale tints marking the outliers, a separated synthesis row, a commentary rail with caveats and a read-for-the-reader box, a topic tag, unit line and source. | Twelve registers on one slide and still legible in five seconds; how disagreement is shown before the conclusion; the caveat register. |
| `T2_roadmap_phase_columns` | T2 | roadmap | Four chapter columns (past, now, next, vision) for an invented ship-maintenance group: header band, sub-heading, a done / planned checklist with a grey detail line per item, a period band; the past chapter faded, the vision column a dark block. | Progression without chevrons: fill darkens chapter by chapter and a small gap separates columns. Hollow marks are a filled div with a white div inside; each checklist is ONE `.pgroup` with marks positioned to its line pitch. |
| `T2_process_stage_rows` | T2 | operating model / process | Four numbered stage rows of an invented clinic-opening playbook, three attribute columns each, thin separators and a three-pillar footer, inside one grey panel; a left column of the three groups who run it, as initials circles. | The number sits in a dark square instead of a left rule. A heading that is only `<b>` must be its own div; people without photos are initials circles with name and role under them. |
| `T2_roles_governance_dot_matrix` | T2 | org / roles | Governance of an invented retailer: group management and six regional heads as initials circles, four group functions, and a function-by-region grid of tinted cells with one dot each, joined by horizontal and vertical lines; two commentary panels. | Define the column centres once and reuse them for circles, labels, dots and lines. Break a vertical line where it would cross a heading. |
| `T3_evidence_small_multiples_rail` | T3 | evidence / small multiples | Twelve client panels of an invented consultancy, each a native column chart of revenue at four July cuts with a practices-per-year circle row, n/a for years before the client joined; one shared legend and a commentary rail whose claims match the panels. | Small multiples need one scale: `data-valuemax` on every chart, and `data-catlabelsize` so narrow charts keep horizontal labels. Every bullet in the rail must be checkable against the panels. |

Open the HTML to see how something is built. Copy construction freely; do not copy a format onto a slide
whose message is different.

## Adding an exhibit

Build it through the pipeline, render it back through PowerPoint, and drop both files here as
`T<tier>_<messagetype>_<slug>.html` and `.png`. Add a row above. Then, from inside this folder:
`sha256sum *.html *.png > CORPUS_SHA256.txt`. Only invented data or material cleared for anyone
who uses this skill belongs here; client, deal and confidential internal slides do not.
