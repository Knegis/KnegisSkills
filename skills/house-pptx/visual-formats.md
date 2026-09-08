# Visual Format Catalog - matching message to visual

Part of the house slide-building skill. Given a slide's MESSAGE TYPE, shortlist 2-3 candidate formats, sketch
them, let a reviewer pick. The goal is *proposing the right visual for the message* - not defaulting to
bullets, and not repeating the same format deck after deck.

**This is a thinking aid, not a lookup table.** Derive the format from what the message needs; invent a fitting visual if nothing here is right (the catalog has an explicit "no pattern fits -> invent" path). Do NOT pick a format because the `reference/` gallery happens to contain one - that is backwards. Fit-to-message brainstorming (including novel formats) is the prized output; examples judge execution quality only, never dictate the format.

## Index: message type -> candidate formats

| The slide's message is... | Strong candidates | Avoid |
|---|---|---|
| "X is made of these parts" (composition) | Layer cake, block architecture, flower/petal, treemap | Pie charts (off-brand feel), plain bullets |
| "How we operate / deliver" (operating model) | Blueprint (swimlane blocks), hub-and-spoke, engine-room diagram, flywheel | Generic pyramid |
| "A leads to B leads to C" (causality/flow) | Chevron flow, value chain, funnel, domino sequence | Numbered bullets |
| "Then vs now / without vs with us" (contrast) | Split-panel before/after, two-column tension, transformation arrow | Two bullet lists |
| "Where the market/players sit" (landscape) | 2x2 positioning map, bubble landscape, convergence map (players moving to center), petal/ecosystem map | Logo soup without axes |
| "We are growing / trajectory" (trend) | House stacked bar (EBITDA bottom, rev-minus-EBITDA top, CAGR arrow), line with annotated inflections, waterfall bridge | 3D charts, dual-axis tricks |
| "What explains the change" (decomposition) | Waterfall bridge, driver tree, stacked delta bars | Unannotated line chart |
| "These are our options" (choices) | Option cards with harvey-ball criteria, decision tree, 2x2 effort/impact | Wall of prose |
| "We recommend this path over time" (roadmap) | Horizon timeline (phases + milestones), ramp chart, swimlane roadmap | Gantt clutter |
| "Proof it works" (evidence/case) | House 2x2 ref-case grid (title + body + 3 KPIs), single hero case with KPI banner, logo wall + 2 deep-dives | KPI-less logo walls |
| "Here is every source, and here is what we conclude" (triangulation) | **Evidence-row table** (one row per source + synthesis row), source-spread dot plot | A single averaged number with no visible basis |
| "This is what people actually told us" (qualitative proof) | **Quote rail** attached to any exhibit, quote-card grid | Paraphrased "clients say..." bullets with no attribution |
| "How big is the prize" (sizing) | Concentric TAM/SAM/SOM, bar ladder, annotated big-number hero | Pseudo-precise decimals |
| "Many forces act on X" (pressure/context) | Porter-style force diagram, radial pressure map, headline/clipping collage | Bullet list of trends |
| "We score better than alternatives" (comparison) | Criteria matrix with harvey balls, spider/radar (max 5 axes), bar pairs | Feature tables with ticks only |
| "Who does what" (org/roles) | Role cards in delivery-flow order, RACI-lite grid, team photo grid + capability tags | Org-chart spaghetti |
| "One number that matters" (hero stat) | Big-number hero (54pt+) with 1-line context + source, KPI banner trio | Burying the number in a table |
| "How the pieces connect" (system) | Hub-and-spoke, layered platform diagram (PLATFORM/DELIVERY split), node-link map (max ~12 nodes) | Dense network hairballs |

## Construction notes (PPT-buildable, on-brand)

**Palette reminder before you read these:** the house default is **near-monochrome** - white canvas, a grey ramp
doing the structural work, **warm sand `#CCBB9D` as the single secondary**, and warmth coming from photography
rather than graphic fills. Amber is a spotlight for at most one element per deck, often none. Ignore any
"accent1 / accent4 / navy / coral" naming in older notes (stale template theme), and do not treat any
amber-heavy reference material as the colour standard - it is warmer than the house usually delivers.
Full palette and the pixel census behind it: `house_style.md` section 4.

Working colours below: black `#000000`, near-black `#1E1E1E`, dark fill `#373737`, mid greys `#585958` / `#7E7F7E`,
light greys `#B8B8B8` / `#BEBFBE`, panel `#EEEEEE`, warm light grey `#DCD6D2`, warm sand `#CCBB9D`,
caption grey `#9F9A94`, rare navy marker `#1D405C`.

- **Layer cake / block architecture:** stacked square rectangles stepping through the grey ramp; the emphasised
  layer takes the warm sand fill with black text. Label outside-left.
- **Blueprint / swimlane operating model:** 3-5 lanes on `#EEEEEE`, process blocks inside in mid grey; the lane
  where the house plays takes warm sand. Legend bottom-right, 9pt caption grey.
- **Hub-and-spoke:** `#373737` centre circle with white text, 1px grey spokes, satellite circles `#EEEEEE` with
  black text. Max 8 spokes.
- **Flywheel:** 3-5 curved arrows in mid grey around a centre label; warm sand on the stage being argued.
- **Chevron flow / value chain:** chevrons in `#EEEEEE`, the emphasised stage in `#373737` (white text) or warm
  sand (black text); 1-line caption under each.
- **Funnel / convergence map:** trapezoid stack; or the landscape version - player groups at the edges with grey
  arrows converging on a centre zone, the contested space picked out in warm sand.
- **Split-panel before/after:** vertical split; left in light greys (the old way), right darker with a warm sand
  accent (the house way); mirrored row structure so the contrast reads line by line. See the reference corpus
  for a built example.
- **2x2 positioning map:** axes as 1px grey lines with end labels, quadrant labels 9pt grey, entities as grey
  dots; the house marker in `#1D405C` or warm sand and visibly larger.
- **Waterfall bridge:** floating bars via an invisible spacer plus a visible delta bar; totals in `#373737`,
  increases in mid grey, decreases in light grey, connectors 1px grey. Direction reads from position and the
  signed label, never from colour.
- **Driver tree:** right-to-left tree of square rectangles, KPI at the root in warm sand; 2 levels max.
- **Option cards:** 3-4 equal cards on `#EEEEEE`, each with option name, 1-line essence, 3 harvey-ball criteria,
  footer verdict; the recommended card gets a `#373737` header bar with white text.
- **Harvey balls:** pie-slice shapes at 0/25/50/75/100 in `#373737`; never more than 5 criteria.
- **Horizon timeline:** thick `#373737` baseline arrow, phase blocks above stepping light grey -> mid grey ->
  warm sand by phase, milestones as diamonds with date labels below.
- **Concentric sizing:** 3 circles bottom-aligned, light grey -> mid grey -> warm sand inward; values inside,
  definitions in a side legend.
- **Radial pressure map:** centre entity, 4-6 labelled arrows pointing inward in `#373737`, each with a 1-line
  evidence caption; arrow weight encodes force strength.
- **Spider / radar:** max 5 axes, two series max - the house in `#373737`, market in `#B8B8B8`.
- **Big-number hero:** 32-54pt number in **black** on white (never a coloured number - it is text), 14pt context
  line, 8pt caption-grey source line. One per slide. See the reference corpus for a built example.
- **2x2 ref-case grid (house format):** four cards, each = declarative case title, 2-3 line body, exactly 3 KPIs
  in a row (black number, grey label). Soft KPIs flagged in a footnote.
- **House stacked bar:** EBITDA segment at the bottom in `#1E1E1E`, organic net revenue in mid grey, acquired
  revenue in warm sand, total labelled above each bar, CAGR arrow spanning above. See the reference corpus for
  a built example of this construction.

- **Evidence-row table (triangulation):** the credibility pattern from top-tier due-diligence packs
  (`reference/T2_evidence_table_quote_rail.html`). **One row per source** - each market report, each
  expert, each customer, each model - grouped by source type down a left spine, with a value per column, a
  short comment on the right, and a **pale tint** encoding direction or sentiment. Then **one synthesis row at
  the bottom**, visually separated (heavier top rule, italic label like "Our view"), carrying the number you
  actually conclude. Sources stay anonymous but specific: "Expert #4", "Former MD at a tech services firm".
  Why it works: the reader sees the spread and the disagreement before the conclusion, so the conclusion reads
  as judgment rather than assertion. Build it as a real table with `border-collapse:separate; border-spacing:1px`
  (CSS borders are dropped in translation); tints from a pale grey/sand ramp, never red/green - direction is
  carried by the label. **Do not average away the disagreement** - the visible spread is the point.

- **Quote rail:** a component, not a slide - it attaches to almost any exhibit and turns interview evidence into
  a real information register. A grey `#EEEEEE` panel down the right ~22-25% of the slide, holding 3-6 cards,
  each: a small quote glyph, the quote in italic (bold the clause that carries the point), and an attribution
  line in caption grey beneath. Attribution is role plus context, never a name the reader cannot verify -
  "Managing Director, <brand>" or "Former VP, tech services". Keep quotes verbatim and short; if you are
  tempted to paraphrase, you are writing a bullet, not quoting. Used on most analytical pages of top-tier
  due-diligence packs (`reference/T2_evidence_table_quote_rail.html` is the built example). It also solves the
  common "the exhibit is only 70% of the slide" problem - the rail earns the remaining width instead of leaving
  it dead.

**Charts are native, not pictures.** Data charts go through the `.ppt-chart` hybrid convention in
`html_pipeline.md` - a real editable PowerPoint chart for the data, with bespoke annotations built as shapes
around it. The older "render it as a matplotlib PNG" guidance is superseded; a picture of a chart cannot be
edited by the person who receives the deck.

## Selection discipline
1. Match on the MESSAGE, not the data shape ("we're converging on the client's problem" is a landscape/convergence message even if you have trend data).
2. At least one candidate per slide must be a non-default choice.
3. Variety across the deck: no format more than twice in a row; dividers reset the rhythm.
4. Density: a format that leaves half the slide empty at real content volume is the wrong format - sketch with REAL content to find out.
5. If no catalog pattern fits, an optional web inspiration sweep is allowed (search e.g. "operating model slide consulting"); describe what works in the found examples, never copy artwork, rebuild in house shapes/palette.
