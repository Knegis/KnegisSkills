# House style - the house slide design contract

Everything on this page is a **default with a reason**, not a law. You are the designer: deviate when the slide
genuinely needs it, and say so. But deviating *by accident* - a title that ended up small because you never checked,
a column that stopped short because you ran out of copy - is the failure this document exists to prevent.

Read this before authoring any HTML. The mechanical checks at the bottom are run with `scripts/typecheck.py` and
grep, never from memory.

---

## 1. The canvas

**1280 x 720 px HTML == a 13.33" x 7.5" 16:9 slide.** `px * 0.75 = pt`, `px * 9525 = EMU`.

| | Value | Note |
|---|---|---|
| Side margins | **24px** | -> content width **1232px**. Not 40, never 64. |
| Top of title | ~34px | |
| Content starts | ~110-120px | below title + subtitle |
| Content runs to | **~690px** | leave no empty bottom band |
| Footer / page no. | bottom 12px | |

Every full-width element - title, subtitle, bands, tables, the column row - is `left:24px; width:1232px`.
If you find yourself typing `left:44px`, you are working to the old margin and losing 40px of canvas.

## 2. Use the whole slide, and scale up to do it

**The single most common defect is a slide that is technically correct and visually half-empty.**

When you render your draft and see dead space, the fix order is:

1. **Grow the objects.** A diagram at 190px that could be 260px should be 260px. Make the venn bigger, the map
   bigger, the bars taller, the row pitch looser.
2. **Grow the type.** Move up the scale in §3. Small type is a decision you make *only* when genuinely fitting a
   lot of content into a fixed space - never as a default posture.
3. **Add a register.** A source line, a callout, an annotation, a small supporting exhibit (see `depth_rubric.md`).
4. **Only then** reconsider the format - it may be the wrong one for this content volume.

What you must **not** do is leave it, or shrink everything further "to be safe". Shrinking to be safe is how a
slide ends up at 9pt body copy with a third of the canvas white.

**Technique that does this automatically:** make columns flex containers and let the exhibit absorb the slack,
rather than stacking fixed-height blocks and hoping they reach the bottom.

```css
.col     { position:absolute; top:110px; height:502px; display:flex; flex-direction:column; }
.exhibit { flex:1; display:flex; align-items:center; justify-content:center; }  /* grows to fill */
.blist   { flex:0 0 auto; }                                                     /* text stays its size */
```

## 3. Type scale

**The house standard specifies font sizes in PowerPoint points.** You author in CSS pixels. These are not the same
number, and the pipeline applies a 6% shrink (`SHRINK = 0.94` in the translator) to absorb browser-vs-PowerPoint
metric drift. So **author px = target pt x 1.418**, not `x 1.333`.

Getting this wrong is not cosmetic: for two years slides were authored with 26px titles believing that was ~24pt.
It delivers **18.5pt**. Use the table.

| Delivered pt | Author px | Use for |
|---:|---:|---|
| **24** | **34** | **Slide title** (content slides) - the default |
| 20 | 28.5 | Title, when it must run to 2 lines |
| 18 | 25.5 | Big block header / hero sub-number |
| 16 | 22.5 | Section header inside a busy slide |
| 14 | 20 | Large body, sparse slides; big-block header |
| **12** | **17** | **Body copy (upper default); sub-headers when bold** |
| 11 | 15.5 | Body copy, dense slides |
| **10** | **14** | **Body copy (lower default); column headers when bold** |
| 9.5 | 13.5 | Dense table cells |
| 9 | 13 | Captions, axis labels |
| 8 | 11.5 | Footnotes, source lines |
| 7.5 | 10.5 | Absolute floor - only when a real constraint forces it |
| 32 / 40 / 54 | 45.5 / 56.5 / 76.5 | Hero stat; divider title; cover title |

**Defaults, stated as the house standard states them:** title **24pt**; body text **10 or 12pt**; headers
**10 or 12pt bold**, or a little larger where they carry weight. Everything else on the slide should be a
deliberate step off that spine.

**Hard rules on top of the scale:**
- Delivered sizes must be **whole or .5 pt only** (9, 9.5, 22.5 - never 9.87). The table above already lands on
  clean values; `pt100()` snaps, but authoring off-table means you don't know what you'll get.
- **5+ distinct type styles** on a content slide (`depth_rubric.md` §2). One or two sizes reads flat.
- **Sentence case everywhere. Never ALL CAPS** - not for labels, kickers, eyebrows, chips or tags. Genuine
  acronyms (AI, KPI, NPS, OpCo) keep their capitals.
- **No `letter-spacing`.** Default tracking only. Distinguish a label by making it bold + smaller + grey, never
  by tracking it out.
- **The house font only**, as set in `house.json` -> `font.name` (the shipped default is Arial). No other font
  family anywhere in the packed file.

## 4. Colour

**The default house slide is near-monochrome.** Greyscale does all the structural work; one warm neutral carries
the single contrast; warmth comes from photography, not from graphic fills.

This is measured, not asserted. A pixel census of the house's reference deck (14 pages) found white 50%, a grey
ramp next, saturated colour 2.5% almost entirely inside photographs; the only graphic chroma was warm sand
`#CCBB9D` at 0.54% and a deep navy marker at 0.007%. There is **no amber anywhere in it.**

### The palette

| Role | Hex | Use |
|---|---|---|
| Canvas | `#FFFFFF` | The default. **White, not cream.** |
| Panel / soft fill | `#EEEEEE` | KPI panels, banded backgrounds, table zebra |
| Warm light grey | `#DCD6D2` | A softer alternative panel fill |
| Text - primary | `#000000` / `#1E1E1E` | Titles and body |
| Text - secondary | `#585958` / `#7E7F7E` | Supporting copy, labels |
| Text - caption | `#9F9A94` | Footnotes, sources, notes (warm grey) |
| Dark fill | `#373737` | Dark bands, charcoal blocks, filled headers (white text on) |
| Mid fill | `#585958` / `#7E7F7E` | Primary chart series, filled shapes |
| Light fill | `#B8B8B8` / `#BEBFBE` | Secondary chart series, inactive states |
| **Warm sand** | **`#CCBB9D`** | **The one secondary.** A second series, a contrasting band, a highlighted tier |
| Deep navy | `#1D405C` | Rare marker accent - a dot, a small square, one flagged item |

### Amber is a spotlight, not a palette colour

`#FAA21B` still exists in the brand, but **it is not a default and it is not a fill you reach for.** Use it for at
most **one** thing in a deck - a single hero data point, one focal element - and frequently not at all. Older
amber-heavy material is not the standard; judge colour against the near-monochrome reference deck instead.

If you find yourself filling bands, cards, chevrons and header bars with amber, you have the wrong palette. Fill
them with greys, and let one warm sand element carry the contrast.

### Rules that do not change

- **Text is black, white, or grey. Full stop.** `#000000` / `#1E1E1E` on light, `#FFFFFF` on dark or photo,
  `#585958` / `#7E7F7E` secondary, `#9F9A94` captions. **Emphasis is bold, never colour.** Coloured type is a
  defect; black type on a coloured fill is fine.
- **Charts: greys and black, optionally warm sand for a second series, or a dark blue family.** Never coral, red,
  or bright blue for a data series. Colour encodes meaning - group membership, actual vs forecast, organic vs
  acquired - never decoration.
- **Full-bleed photography** on cover, section and case slides: dark, moody, low-key, white text over it. This is
  where colour and warmth live. The cover of the house's reference deck is the example to follow.
- Cream `#F5F2EC` is still acceptable where a deck has already committed to it, but **white is the default.**

## 5. Structure and shapes

- **Backgrounds are backgrounds, not objects.** To make the canvas beige, set the canvas beige
  (`.slide{background:#F5F2EC}`) and let the translator promote it to the slide's real background property.
  Never draw a full-bleed rectangle to fake it - it becomes a selectable object that traps clicks and gets
  dragged by accident. (Fixed in the translator; the rule stands so nobody reintroduces it by hand.)
- **Square corners.** `border-radius:0` on every rectangle, card, band and chip. Circles stay circular.
- **No coloured left-border accents** on text blocks or cards. To highlight, use a tinted background wash
  (`background:#F2F2F2` or light amber), not a vertical rule.
- **No stat-tile hairlines.** The big-number / thin-rule-above / small-label KPI tile reads as generic AI output.
  Prefer a prose sentence with the numbers bolded, or a genuinely designed exhibit.
- **Text lives inside its shape.** Give the filled div the text as its own content rather than overlaying a
  separate text box on a background rectangle. Exceptions: text spanning several shapes, annotations sitting
  outside a shape, or labels that must align independently.
- **One list = one text box.** Wrap any 2+ line block in `<div class="pgroup">` so it becomes a single text box
  with real paragraphs and consistent spacing. One box per bullet is a defect.
- **Bullet markers go inside the paragraph text, as a real glyph** - `<div>&#8226;&nbsp; Item text</div>`.
  Two wrong ways, both verified: a CSS `::before` marker is silently dropped in translation, and a separate
  marker `<div>` inside a `.pgroup` survives as a shape but loses its indent, because the grouped text box
  spans the whole group width and the text then renders on top of the dot. A marker div only behaves outside
  a `.pgroup` - and then you are back to one text box per bullet, which is the defect above. So: glyph in the
  paragraph.
- **Align across columns.** Repeated elements in parallel columns share an absolute top; never let them float
  wherever the copy above happens to end.

## 6. Language and numbers

- **Hyphens, never em dashes.** Verify by grep, not recollection.
- Currency reads **"147 MNOK"**, never "NOK147m".
- **No emojis**, including as bullet markers.
- Titles are **full declarative sentences** - a reader understands the slide from the title alone.
- One **anchor phrase** per deck, used verbatim; no drift.
- **Never invent a number, client name, or result.** If it isn't sourced, either ask (see `00_intake.md`) or mark
  it `[ILLUSTRATIVE]` on the slide itself.
- No internal jargon in client- or investor-facing material.

### Sources and footnotes - when they are required
These are **not** decorative chrome to sprinkle on every slide, and they are **not** optional on evidence slides.

- **Required** when the slide carries data, a claim drawn from an external pack (commercial due diligence, IM,
  FDD, bank material), a market figure, or anything a reader could reasonably ask "says who?" about.
- **Omit** on pure narrative, capability, divider and cover slides, where a source line is just noise.

When in doubt, include it - an unsourced number in investor material is a bigger failure than a redundant caption.

## 7. Mechanical checks (run these; do not self-certify)

```bash
python scripts/typecheck.py <slide>.html        # type scale, delivered pt, caps, letter-spacing, em dashes
grep -n " - " <slide>.html                        # em dashes: must return nothing
grep -nE "left:(4[0-9]|[5-9][0-9])px" <slide>.html   # off-margin content (should be 24px)
```
Then the render-back gate in `html_pipeline.md` §5 - view the PowerPoint render, not just the browser mockup.
