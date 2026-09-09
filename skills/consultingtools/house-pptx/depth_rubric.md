# Depth rubric - the quality bar every house slide must clear

The recurring failure of agent-made slides is **thinness**: a title, a few bullets, one register of information,
half the canvas empty. Real house slides and top-consulting slides are *levelled* - many registers of information
on a controlled grid, with deliberate craft. This rubric defines the bar.

**Check your rendered slide against this before translating to PowerPoint, and iterate until it passes.**

---

## 0. Pick the tier first - then look at references at that tier

Density is not one setting. Decide which tier the slide is, and say so; then **load and actually view at least
two reference exhibits at that tier before designing.** This step is what separates a strong slide from a thin
one, and skipping it is the single most reliable predictor of a thin result.

| Tier | What it is | Registers | Typical use |
|---|---|---|---|
| **T1 Statement** | One idea, given room. Hero stat, cover, divider, single deep case. Sparse **by design** - not sparse by accident. | 3-5 | Covers, section breaks, one-number slides |
| **T2 Standard** | A normal content slide: a primary visual done properly, with labels, a synthesised read, and a source. | 6-8 | Most client and internal content slides |
| **T3 Dense** | Investor / DD grade: a primary visual **plus** a commentary rail **plus** supporting micro-exhibits **plus** caveats and source, all on one slide. | 10+ | Commercial due diligence, IM, board and investor material |

**Choosing the tier:**
- **Match the pack the slide sits in.** If the deliverable responds to or sits alongside an external pack
  (commercial due diligence, IM, FDD, bank material), **read that pack first** - it sets the bar, and guessing
  produces a slide that looks amateur next to it. This is the specific fix for the "the slides are too thin"
  failure.
- Investor and diligence material defaults to **T3**.
- A slide is only as deep as its evidence. If you have one data point, no format makes it T3 - say so and
  either get more evidence or build an honest T2. Do not pad.

**Finding references:** files in `reference/` are named `T<tier>_<messagetype>_<slug>` - so
`ls reference/T3_*` gives you every dense exemplar, `ls reference/*_trend_*` every trajectory slide. If the
corpus is thin on your tier, the external pack the slide sits beside is the reference. Details and what to
learn from each: `reference/MANIFEST.md`.

## 1. Information registers (6-10 on a T2/T3 content slide)
A deep slide layers distinct kinds of information, each styled to its importance:
1. **Declarative title** - a full sentence carrying the insight, often with the key number
2. **Subtitle / context line** - what the reader is looking at
3. **Unit / qualifier** - for data ("% of revenue", "FY26B"), italic, caption grey
4. **The primary visual or structure** - the chart, stack, matrix, panel set (the centrepiece)
5. **Supporting labels / annotations** - values, owners, callouts on the structure
6. **A synthesised "so-what"** - the implication, the investor read; the slide's conclusion, not just its data
7. **Caveats / footnote** - assumptions, basis, definitions (tiny, caption grey)
8. **Source / provenance** - required whenever the slide carries data (see `house_style.md` section 6)
9. **Section or topic tag** - orientation chip
10. **Chrome** - the house wordmark, page number

Title + one visual + footer is the floor, not the target.

## 2. Typographic hierarchy
**5+ deliberate text styles** mapped to the registers above: title bold; subtitle medium; unit italic small;
labels semibold; body regular; chips bold-small; footnotes 8pt caption grey. If everything is one or two sizes,
it reads flat. Sizes come from the type scale in `house_style.md` section 3 - and note that "make it smaller to
fit" is almost always the wrong move (section 2 of that document).

## 3. Functional colour
Colour encodes *meaning* - group membership, organic vs acquired, actual vs forecast, defensible vs commodity -
**never decoration**.

The house default is **near-monochrome**: white canvas, a grey ramp carrying the structure, **warm sand
`#CCBB9D` as the single secondary**, and warmth coming from full-bleed photography rather than coloured fills.
Charts are greys/black (optionally warm sand for a second series, or a dark-blue family) - **never coral, red or
bright blue**. Amber is a spotlight for at most one element in a deck, frequently none. Do not paint saturated
full-bleed panels. Full palette and the measured evidence behind it: `house_style.md` section 4.

A slide that needs "more colour" almost always needs **more contrast in the grey ramp, or a photograph** - not
an accent fill.

## 4. Grid, alignment, linkage
Everything sits on a consistent grid; columns and rows align; related elements are visually tied (brackets,
shared baselines, connectors). Repeated elements across parallel columns share an absolute top. Misalignment
reads as amateur.

## 5. Density with order
Fill the canvas - no large dead quadrants - but keep it legible in 5 seconds. Density without a grid is clutter;
a grid without density is thin. Both fail. When you see dead space, **grow the objects, then the type, then add
a register** - in that order (`house_style.md` section 2).

## Hard FAIL conditions
- Title + bullets, or a single information register
- A `[VISUAL: ...]` placeholder, or any "to be built later" - the visual IS the work
- Empty quadrant / large dead space at real content volume
- Colour used decoratively; amber or sand used as a general fill palette; any coloured type
- All text one or two sizes
- T3 claimed but no T3 reference was viewed and no commentary rail or supporting exhibit exists

## Self-check (run against the render, mechanically)
- [ ] Tier declared, and 2+ references at that tier actually viewed
- [ ] Title is a declarative sentence; the deck is understandable from titles alone
- [ ] Count the information registers - 6+ for T2/T3?
- [ ] 5+ distinct type styles present
- [ ] `python scripts/typecheck.py <slide>.html` run - no FAILs, WARNs understood
- [ ] Colour encodes meaning; near-monochrome; no coloured type; no saturated panels
- [ ] Elements aligned to a grid; related items visually linked
- [ ] Canvas filled to ~690px and to both 24px margins; still legible in 5 seconds
- [ ] A synthesised so-what is present, not just data
- [ ] Source present wherever the slide carries data; chrome (wordmark, page) present
- [ ] Hyphens not em dashes; "147 MNOK" currency style; numbers traceable or marked `[ILLUSTRATIVE]`
