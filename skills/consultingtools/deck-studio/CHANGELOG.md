# Changelog

## 2026-10-02 - v1.0.1, neutral examples

- **Reference corpus trimmed to 10 exhibits** (three removed).
- **Neutral example settings.** Place names, people and company names in the remaining exhibits are now
  generic; the five edited exhibits were rebuilt and re-rendered through PowerPoint, and `CORPUS_SHA256.txt`
  regenerated.
- **Config file** is `deck-studio.json` next to the skill (or `~/.deck-studio.json`); environment overrides are
  `DECK_STUDIO_TEMPLATE` and `DECK_STUDIO_FONTDIR`.
- `typecheck.py`: currency codes grouped in one list (adds MGBP, MCHF, MDKK, JPY, CAD, AUD).
- LICENSE: copyright holder is "deck-studio contributors".

## 2026-09-30 - v1.0.0, first release

- **Template chosen per deck.** At the start of every new deck the agent asks which PowerPoint template to use:
  the user's own .pptx/.potx, or the plain built-in one. `scripts/use_template.py <file> --deck <folder>` (or
  `--plain --deck <folder>`) applies it, derives the palette and font from the template's theme, and records the
  choice in `<folder>/deck_template.json`; `--resume <folder>` re-applies it before a revision, so a deck is
  always rebuilt on its own template. `--show` names the active template.
- **Plain built-in template**: stock 16:9 Office layouts, Arial, a neutral grey palette with one steel-blue
  accent (`house.json`). No brand template or font ships.
- **HTML-first pipeline**: constrained slide HTML, a mechanical style checker (`typecheck.py`), a browser
  workroom for review rounds (`workroom.py --serve`: comments and pins, archive, reorder, build, an Analysis
  tab showing the source workbook next to each data slide), and translation to native, editable shapes,
  pictures and charts (`build_deck.py`), with a mandatory PowerPoint render-back (`render_slides.py`) and a
  font audit (`fontcheck.py`).
- **Reference corpus**: 13 exhibits at three density tiers on invented companies, each as the HTML that built
  it plus its PowerPoint render on the plain template (`reference/MANIFEST.md`).
- Tests: `python -m pytest tests -q` (offline) and `-m browser` (needs Edge or Chrome); `scripts/selftest.py`.
