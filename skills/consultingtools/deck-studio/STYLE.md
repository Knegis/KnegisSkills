# STYLE - the slide contract (canvas, type, colour, shapes, density)

Defaults with a reason, not laws: deviate when a slide needs it and say so. Deviating by accident (a title that
ended up small, a column that stopped short) is what this page and `scripts/typecheck.py` exist to prevent.

## 1. Canvas

1280 x 720 px HTML == a 16:9 slide. px x 0.75 = pt. px x 9525 = EMU.

| | Value |
|---|---|
| Side margins | 24px, so content width is 1232px (`left:24px; width:1232px` for every full-width element) |
| Title top | ~24px; title width 1160px (right edge 1184, clear of any logo the template's master draws) |
| Content starts | ~150-160px, below title and subtitle |
| Content runs to | ~690px; the source line sits at ~672px |
| Chrome | none in the HTML when the template's master draws logo, footer and page number (`use_template.py` detects it) |

**Use the whole slide.** A slide that is correct and half-empty is the most common defect. When you see dead
space: grow the objects, then the type, then add a register (source line, callout, caveat, small exhibit), and
only then reconsider the format. Never shrink everything "to be safe". Make columns flex containers so the
exhibit absorbs the slack:

```css
.col{position:absolute;top:160px;height:496px;display:flex;flex-direction:column;}
.exhibit{flex:1;}   /* grows to fill */   .list{flex:0 0 auto;}   /* text keeps its size */
```

## 2. Type scale

Sizes are specified in PowerPoint points and authored in CSS pixels. The translator shrinks text by 6% to
absorb browser-vs-PowerPoint metric drift, so **author px = target pt x 1.418**. A 26px title is 18.5pt, not
24pt. Use the table; `typecheck.py` verifies delivered sizes.

| Delivered pt | Author px | Use |
|---:|---:|---|
| **24** | **34** | Slide title (default) |
| 20 | 28.5 | Title when it must run to two lines |
| 18 | 25.5 | Big block header, hero sub-number |
| 16 | 22.5 | Section header inside a busy slide |
| 14 | 20 | Large body on sparse slides |
| **12** | **17** | Body copy (upper default); subtitle; bold sub-headers |
| 11 | 15.5 | Body on dense slides |
| **10** | **14** | Body copy (lower default); bold column headers |
| 9.5 | 13.5 | Dense table cells |
| 9 | 13 | Captions, axis labels, chips |
| 8 | 11.5 | Footnotes, source lines |
| 7.5 | 10.5 | Absolute floor |
| 32 / 40 / 54 | 45.5 / 56.5 / 76.5 | Hero stat / divider title / cover title |

Rules: delivered sizes are whole or .5pt only; 5+ distinct text styles on a content slide (one or two sizes
reads flat); sentence case everywhere, never ALL CAPS (genuine acronyms keep their capitals); no
letter-spacing; the template's font on every element (`use_template.py --show` prints it; Arial on the plain template).

## 3. Colour

The default slide is near-monochrome: a white canvas, a grey ramp doing the structural work, one accent as the
secondary. Colour encodes meaning (group membership, actual vs forecast, the highlighted row), never
decoration. Role names below are what the docs and `typecheck.py` refer to. The values in the table are the
plain template's (`house.json`); when the user's own template is active, `scripts/use_template.py` maps its
theme colours onto the same roles and prints them, and those printed values are the ones to design with.

| Role | Hex | Use |
|---|---|---|
| canvas | `#FFFFFF` | White |
| panel / panel_alt | `#EEEEEE` / `#E3E6EA` | Rails, banded backgrounds, table zebra, soft cards |
| text_primary | `#000000` / `#1E1E1E` | Titles and body |
| text_secondary | `#595959` / `#7F7F7F` | Supporting copy, labels, subtitles |
| text_caption | `#8C8C8C` | Footnotes, sources, units |
| dark_fill | `#373737` | Dark bands, synthesis boxes, filled headers (white text on) |
| mid_fill | `#595959` / `#7F7F7F` | Primary chart series, filled shapes |
| light_fill | `#B8B8B8` / `#BFBFBF` | Secondary series, inactive states |
| **secondary** | **`#9FB3C8`** | Steel blue: the one accent. A second series, a highlighted row, the argued stage |
| marker | `#24476B` | Deep blue, rare: one dot, one flagged item |
| spotlight | `#E8833A` | Orange: at most one element in a deck, often none. Never a fill palette |

**Warmth comes from photography**, not from fills: full-bleed imagery on cover, section and case slides with
white text over a dark scrim (`PIPELINE.md` -> Images). If a slide feels flat, add contrast in the grey ramp or
a photograph, never an accent fill.

Rules that do not change: **text is black, white or grey, and emphasis is bold, never colour** (black type on
a coloured fill is fine; coloured type is a defect). Charts are greys and black, optionally the secondary for
a second series; never a rainbow of series colours. On the plain template, do not use its stock Office theme
colours; use the roles above. `alt_canvas` `#F5F5F5` is acceptable as a slide background where a deck
already uses one.

## 4. Shapes and structure

- Backgrounds are a slide property: set `.slide{background:...}`; never draw a full-bleed rectangle.
- Square corners on every rectangle, card, band and chip (`border-radius:0`). Circles stay circular.
- No coloured left-border accents on cards. Highlight with a tinted background wash.
- No stat-tile hairlines (big number, thin rule, small label). Prefer a sentence with the numbers bolded, or a
  designed exhibit.
- Text lives inside its shape: the filled div carries the text; do not overlay a separate text box.
- One list = one text box: wrap any 2+ line block in `<div class="pgroup">`. Bullet glyphs go in the paragraph
  text (`&#8226;&nbsp; Item`), never as CSS `::before` or a marker div.
- A heading and its body inside one card are ONE text box too: wrap label, heading and body in a single
  `.pgroup` and set the gap with margins, so PowerPoint gets one box with paragraph spacing, not three
  stacked boxes the user has to select one by one. Only fills, rules and pictures sit outside the group.
- Repeated elements in parallel columns share an absolute top. Misalignment reads as amateur.
- Rules and connectors are 1-6px filled divs, horizontal or vertical only; the translator emits them as
  line shapes with that stroke weight. Arrowheads are glyphs (`&#9654;`).

## 5. Language and numbers

Titles are full declarative sentences: the reader understands the slide from the title alone. Hyphens, never
em dashes. Currency with the unit after the number ("147 MEUR"), never "EUR147m". No emojis. One anchor phrase per deck, used verbatim.
Never invent a number, client or result: ask, or mark it `[ILLUSTRATIVE]` on the slide. Sources are required
wherever the slide carries data or a claim someone could ask "says who?" about; omit them on pure narrative,
divider and cover slides.

## 6. Density: pick the tier, then check the registers

| Tier | What it is | Registers | Typical use |
|---|---|---|---|
| **T1 Statement** | One idea given room: cover, divider, hero stat. Sparse by design. | 3-5 | Covers, section breaks, one-number slides |
| **T2 Standard** | A primary visual done properly, with labels, a synthesised read and a source. | 6-8 | Most client and internal content slides |
| **T3 Dense** | Investor / diligence grade: primary visual plus commentary rail plus supporting exhibit plus caveats and source. | 10+ | Due diligence, IM, board and investor material |

Match the pack the slide sits in: if the deck responds to an external pack (a due-diligence report, an IM, bank
material), read it first; it sets the bar. A slide is only as deep as its evidence: with one data point no
format makes it T3, so say so rather than pad. Look at the exhibits at your tier in `reference/` before
designing (`reference/MANIFEST.md`).

Registers to layer on a T2/T3 slide: declarative title; subtitle or context line; unit or qualifier; the
primary visual; labels and annotations on it; a synthesised so-what; caveats; source; a topic tag.

**Hard fails:** title plus bullets or a single register; a `[VISUAL: ...]` placeholder; a large dead quadrant
at real content volume; colour used decoratively or coloured type; all text in one or two sizes; T3 claimed
with no commentary rail or supporting exhibit.

## 7. Check mechanically

```bash
python scripts/typecheck.py <slide>.html     # type scale, colour, caps, dashes, canvas usage, collisions,
                                             # overflow, and everything the extractor cannot translate
```
Then look at the render, and after translation look at the PowerPoint render (`PIPELINE.md` step 6).
