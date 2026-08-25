# East Neurology — Patient Information Sheets

A small, dependency-free generator that builds patient information sheets in the
East Neurology house style from a **content database** rather than from
hand-written HTML pages.

The problem it solves: these sheets overlap heavily. Sit-to-stand appears in four
of them. The "how to make solo home exercise safe" box belongs on all of them.
The floor-rescue plan belongs on three. Writing each page as its own HTML file
means seven copies of the same paragraph, drifting apart every time one is edited.

Here, every reusable piece of content is written **once**, stored under `content/`,
and referenced by id from whichever sheets need it — with per-sheet overrides where
the wording has to change.

```
npm run build          # builds every sheet into dist/
node src/build.mjs neck-pain   # builds one sheet
```

No dependencies, no build tooling. Node 18+.

---

## Layout

```
content/
  theme.json            design tokens, practice details, external links
  texts.json            short reusable prose snippets
  fragments.json        reusable BLOCKS and multi-block sections
  exercises/*.json      the exercise / technique library, split by topic
  sheets/*.json         one file per sheet: metadata + an ordered list of blocks
src/
  build.mjs             loads content, resolves references, writes dist/
  resolve.mjs           the @reference and {{token}} layer
  render.mjs            the block registry — one renderer per component type
  css.mjs               the house style, generated from theme.json
  inline.mjs            escaping + a tiny inline-markdown subset
dist/                   generated HTML (one file per sheet, plus index.html)
```

## How a sheet is written

A sheet is metadata plus an ordered list of blocks:

```json
{
  "meta": { "id": "neck-pain", "order": 7, "group": "Spine",
            "title": "Neck Pain", "summary": "…", "reviewed": "August 2026" },
  "blocks": [
    { "type": "intro", "paras": ["…"], "box": { "kind": "highlight", "text": "…" } },
    "@fragment:how-to-use",
    { "type": "phaseBanner", "variant": "a", "title": "The daily programme" },
    { "type": "exercises", "items": ["@exercise:chin-nod", "@exercise:neck-isometrics"] }
  ]
}
```

The hero header, the "other information sheets" list and the closing call to
action are added automatically (`meta.autoCta` / `meta.autoRelated` opt out).

## Reuse and overrides

| Form | Meaning |
| --- | --- |
| `"@exercise:chair-squats"` | insert that exercise as written |
| `"@fragment:safety-first"` | insert those block(s); a fragment may expand to several blocks |
| `"@text:acceptable-soreness"` | insert a shared sentence, anywhere a string is expected |
| `{{practice.name}}`, `{{links.stress}}` | token substitution from `theme.json` |

To reuse a library item with changes, patch it instead of copying it:

```json
{ "$ref": "exercise:tandem-gait",
  "set":    { "dose": "10 steps × 2, once a day" },
  "append": { "safety": " Corridor with two reachable walls, shoes on.",
              "how_to": ["An extra final step…"] } }
```

- `set` replaces a field outright.
- `append` appends to an array field, or concatenates onto a string field.
- `merge` shallow-merges an object field.

The build prints which items were reused and how often, so drift is visible:

```
Built 7 sheet(s). 24 content items were reused across sheets:
    fragment:how-to-use × 7
    text:acceptable-soreness × 6
    exercise:tandem-stance × 4
```

## Publishing

Three output modes:

```
node src/build.mjs              # dist/*.html            standalone single-file pages
node src/build.mjs --embed      # dist/embed/*.html      paste into a CMS page
node src/build.mjs --artifacts  # dist/artifacts/*.html  Claude Artifact fragments
```

**Embed mode** emits one `<div class="en-sheet">` per sheet with the whole stylesheet
scoped under that class (selectors prefixed, keyframes renamed) plus an armour layer
that re-asserts the fonts and colours a host stylesheet commonly overrides with
`!important`. Paste it into a custom-HTML block and nothing leaks in either
direction. It also writes `dist/embed/manifest.json` — page heading, slug and meta
description for each sheet — and rewrites inter-sheet links to
`{{links.home}}/<slug>`, overridable per sheet in `content/site-urls.json`.

**Artifact mode**

emits body-only fragments with a clean title for publishing as Claude Artifacts. Put
the published URLs in `content/artifact-urls.json` and rebuild; the cross-links are
rewritten to those URLs so the set browses as one site.

See `HANDOVER.md` for the step-by-step MailerLite publishing brief.

## Block types

`hero`, `intro`, `section` (nests blocks), `phaseBanner`, `steps`, `cards`,
`contentCards`, `exercises`, `box` (`highlight` / `reassurance` / `warning`),
`researchNote`, `science`, `checklist`, `table`, `faq`, `cta`, `related`, `html`.

Add a new component by adding one function to the registry in `src/render.mjs`
and the matching CSS in `src/css.mjs`; every sheet can then use it from JSON.

## Adding a new sheet

1. Add any genuinely new exercises to a file in `content/exercises/`.
2. Add anything that will be shared with other sheets to `content/fragments.json`.
3. Create `content/sheets/<name>.json` — mostly references, with the new prose in between.
4. `npm run build`.

## House style

Defined once in `src/css.mjs` and driven by `content/theme.json`: Crimson Pro
headings, DM Sans body, the teal/orange palette, gradient header, floating intro
card, numbered step cards, evidence badges, highlight / reassurance / warning
boxes, and a print stylesheet so the sheets can be handed out on paper.

## Clinical content

Content was drafted against current guidelines and reviews — among them the 2019
Cochrane exercise-for-falls-prevention review, the 2022 World Guidelines for Falls
Prevention, the Otago and LiFE programmes, the 2022 APTA vestibular hypofunction
guideline, LSVT BIG / PD Warrior amplitude and neuroplasticity principles, the
SPARX high-intensity exercise trials, AASM and ACP insomnia guidelines, McGill's
spine-sparing core work, and the Jull craniocervical flexion and Ylinen neck
strengthening protocols.

The sheets are patient-facing general information and are explicitly framed as
subordinate to individual medical advice.
