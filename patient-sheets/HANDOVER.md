# Handover — publishing the patient sheets to MailerLite

Written for a **fresh local Claude Code session**. Everything you need is in this
folder; you should not need the conversation that produced it.

---

## 1. What this is

Seven patient information sheets for East Neurology (Dr Ron Granot, Bondi Junction),
in the practice's established house style — the same style as the existing page at
`eastneuro.info/stress`.

They are generated from a content database, not hand-written. Content lives in
`content/`, the house style lives in `src/`. Never edit the files in `dist/` — they
are build output and are overwritten. Edit `content/`, then rebuild.

| Sheet | Suggested page heading | Suggested slug |
| --- | --- | --- |
| `balance-falls` | Balance and Strength at Home | `/balance` |
| `balance-neuromuscular` | Balance When the Problem Is Nerve or Muscle | `/balance-nerve` |
| `balance-vestibular` | Vestibular Rehabilitation at Home | `/dizziness` |
| `parkinsons-exercise` | Exercise for Parkinson's Disease | `/parkinsons` |
| `insomnia` | Treating Insomnia | `/insomnia` |
| `back-core` | Core Strengthening for Back Pain | `/back` |
| `neck-pain` | Neck Pain: Ergonomics and Gentle Strengthening | `/neck` |

The authoritative version of that table, with meta descriptions, is
`dist/embed/manifest.json`. **Confirm the headings and slugs with Ron before
publishing** — they are proposals, not decisions.

## 2. Getting it onto this machine

```bash
git clone -b claude/patient-education-sheets-yfrd68 \
  https://github.com/drrontodo/self-hosted-ai-starter-kit.git eastneuro-sheets
cd eastneuro-sheets/patient-sheets
node src/build.mjs --embed      # Node 18+; no dependencies to install
```

If the repo is already cloned: `git fetch origin claude/patient-education-sheets-yfrd68 && git checkout claude/patient-education-sheets-yfrd68`

## 3. Three build outputs — use the right one

```bash
node src/build.mjs              # dist/*.html          standalone pages
node src/build.mjs --embed      # dist/embed/*.html    paste into a CMS  <- use this for MailerLite
node src/build.mjs --artifacts  # dist/artifacts/*.html  Claude Artifact fragments
```

**For MailerLite, use `dist/embed/`.** Each file is a single `<div class="en-sheet">`
containing a scoped `<style>` block and the page content. Every CSS selector is
prefixed with `.en-sheet`, keyframes are renamed, and an armour layer re-asserts the
fonts and colours that a host stylesheet most often overrides. It has been tested
against a deliberately hostile host stylesheet and holds its appearance.

Cross-links between sheets in the embed build already point at
`https://eastneuro.info/<slug>`. If the slugs change, edit `content/sheets/*.json`
(`meta.slug`) or add overrides in `content/site-urls.json`, then rebuild.

## 4. The publishing task

For each of the seven sheets:

1. Create a new page on the MailerLite site that hosts `eastneuro.info`.
2. Set the page heading and URL slug from `dist/embed/manifest.json`.
3. Set the SEO/meta description from the same file (`metaDescription`).
4. Add a **Custom HTML** block and paste the entire contents of the matching
   `dist/embed/<id>.html`.
5. Publish, then open the live URL and check it against `dist/<id>.html` opened in a
   browser — they should look the same.

Finally, add the seven pages to the site navigation or to a contents page.
`dist/embed/index.html` is a ready-made contents page if a landing page is wanted.

## 5. Read this before you start automating

**Do not assume the MailerLite API can create site pages.** The documented public API
covers subscribers, groups, campaigns, forms, automations and webhooks. Website and
landing-page content is managed in the site builder and may not be reachable
programmatically at all.

So, in order:

1. List the MailerLite MCP tools actually available to you and read their schemas.
2. If a tool genuinely creates or updates **site pages**, use it, and confirm the
   custom-HTML content survives intact.
3. If not — which is the likely outcome — **say so plainly and switch to assisting
   manually**: open each embed file, copy it to the clipboard, and talk Ron through
   the paste, one sheet at a time. Do not improvise by pushing the content into a
   campaign, a form, or an automation; those are emails, not pages.

Two further cautions:

- **MailerLite's editor may sanitise a custom HTML block.** Publish ONE sheet first
  (`neck-pain` is the shortest) and inspect the live page before doing the other six.
  If the `<style>` block is stripped, stop and report it — the fallback is hosting the
  standalone `dist/*.html` files elsewhere and linking to them, which is a decision
  for Ron, not for you.
- **Do not touch subscriber lists, campaigns or automations.** This task is pages
  only. Nothing here should send an email to anyone.

## 6. If the content needs editing

Do not edit `dist/`. The content is in:

- `content/sheets/*.json` — one file per sheet: metadata plus an ordered list of blocks
- `content/exercises/*.json` — the exercise and technique library, shared across sheets
- `content/fragments.json` — shared blocks (safety, floor-rescue plan, referral pathway)
- `content/texts.json` — shared sentences
- `content/theme.json` — colours, fonts, practice details, external links

`README.md` explains the reference syntax (`@exercise:chair-squats`, `$ref` with
`set`/`append`). Rebuild after any edit, and commit the change so the source stays
the single copy.

## 7. Clinical caveats to pass on, not to fix yourself

The sheets deliberately include some unflattering evidence — that boxing programmes
for Parkinson's have not shown benefit in recent reviews, that balance training in
diabetic neuropathy has never been shown to reduce falls, that vitamin D does not
prevent falls, that sleep hygiene alone is a weak treatment. **These are intentional.**
If Ron wants them softened or removed, that is his call as the author; do not
edit clinical content on your own initiative.

One outstanding check for Ron: the styling was reproduced from the East Neurology
house-style specification, because `eastneuro.info` was unreachable from the machine
that generated it. Compare the header and intro card against the live `/stress` page
before publishing the set.
