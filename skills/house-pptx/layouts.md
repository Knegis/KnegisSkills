# Layouts - choosing one on whatever template is configured

The pipeline does not depend on a particular template. It unpacks the template named in `house.json` (or
`HOUSE_PPTX_TEMPLATE`), reads the **names** of its slide layouts, and places each slide on one of them.

## See what you have

```bash
python scripts/list_layouts.py                 # the configured template
python scripts/list_layouts.py path/to/other.pptx
```

Output, for the shipped neutral template:

```
file                   placeholders  picture  name
slideLayout1.xml                  5           Title Slide
slideLayout2.xml                  5           Title and Content
slideLayout3.xml                  5           Section Header
slideLayout4.xml                  6           Two Content
slideLayout5.xml                  8           Comparison
slideLayout6.xml                  4           Title Only
slideLayout7.xml                  3           Blank
...
```

## Choose one per slide

In the slide HTML: `<body data-ppt-layout="...">`. The value may be

| Form | Example | Resolves to |
|---|---|---|
| alias | `blank`, `title`, `divider`, `end` | the first layout whose name contains one of the alias's patterns (blank / no content; title slide / cover; section header / divider; end slide / closing / thank) |
| name substring | `two content`, `dark`, `image light` | the first layout whose name contains it, case-insensitive |
| filename | `slideLayout7.xml` | that file, if the template has it |
| (nothing) | | the blankest layout in the template - fewest placeholders |

If nothing matches, the translator prints a warning and uses the blankest layout, so a typo never breaks the build.

## Which to use

- **A fully designed HTML slide wants the blankest layout** (the default). Everything on it is your own shapes,
  so a layout with title or body placeholders only adds empty boxes the recipient has to delete.
- **Chrome slides** (cover, divider, agenda, closing) are the exception: if the template has designed layouts for
  those, place the slide on them and keep the HTML content minimal, so the template's own treatment shows.
- **Content slides in a branded template**: still prefer the blankest content layout that carries the master's
  footer and page number. If the master draws a logo, set `template_supplies_chrome: true` in `house.json` so the
  HTML `.wordmark` and `.pg` are not translated on top of it.

## Adding your own template

Any 16:9 .pptx. Copy it into `template/` (or point `house.json` -> `template` at it), run
`python scripts/list_layouts.py` to see the names, then use those names in `data-ppt-layout`. Run
`python scripts/doctor.py` once: it checks the aspect ratio and that the file opens. Slide masters with a
hardcoded fallback font are normal; `patch_fonts.py` rewrites them to the house font on every build.
