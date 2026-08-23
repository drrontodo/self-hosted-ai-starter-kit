#!/usr/bin/env node
/**
 * Build every patient information sheet from the content database.
 *
 *   node src/build.mjs            -> writes dist/*.html + dist/index.html
 *   node src/build.mjs vestibular -> builds one sheet only
 *
 * Content lives in content/ ; the house style lives in src/ . Nothing about a
 * page's wording is hard-coded in the templates, and nothing about the styling
 * is repeated in the content.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildCss } from './css.mjs';
import { makeResolver } from './resolve.mjs';
import { renderBlocks } from './render.mjs';
import { esc, escText } from './inline.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const readJson = p => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));

const theme = readJson('content/theme.json');

/** Merge every JSON file in a directory into one keyed bucket, so the library can be split by topic. */
function readJsonDir(dir) {
  const out = {};
  for (const f of fs.readdirSync(path.join(ROOT, dir)).filter(f => f.endsWith('.json')).sort()) {
    const part = readJson(path.join(dir, f));
    for (const [k, v] of Object.entries(part)) {
      if (k in out) throw new Error(`Duplicate id "${k}" in ${dir}/${f}`);
      out[k] = v;
    }
  }
  return out;
}

const library = {
  fragment: readJson('content/fragments.json'),
  exercise: readJsonDir('content/exercises'),
  text: readJson('content/texts.json'),
};

const sheetFiles = fs
  .readdirSync(path.join(ROOT, 'content/sheets'))
  .filter(f => f.endsWith('.json'))
  .sort();

const sheets = sheetFiles.map(f => ({ file: f, ...readJson(path.join('content/sheets', f)) }));
sheets.sort((a, b) => (a.meta.order ?? 99) - (b.meta.order ?? 99));

const index = sheets.map(s => ({
  id: s.meta.id,
  href: `${s.meta.id}.html`,
  title: s.meta.shortTitle ?? s.meta.title,
  desc: s.meta.summary,
  group: s.meta.group ?? 'Other',
}));

function page({ sheet, body, css }) {
  const m = sheet.meta;
  return `<!DOCTYPE html>
<html lang="en-AU">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escText(m.title)} | ${escText(theme.practice.name)}</title>
<meta name="description" content="${esc(m.summary)}">
<meta name="author" content="${esc(theme.practice.clinician)}, ${esc(theme.practice.name)}">
<meta property="og:title" content="${esc(m.title)}">
<meta property="og:description" content="${esc(m.summary)}">
<meta property="og:type" content="article">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="${esc(theme.fonts.googleHref)}" rel="stylesheet">
<style>
${css}
</style>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
${body.hero}
<main id="main" class="container">
${body.main}
</main>
<footer>
  <p class="practice">${esc(theme.practice.name)}</p>
  <p>${esc(theme.practice.address)}</p>
  <p><a href="${esc(theme.practice.siteUrl)}">${esc(theme.practice.site)}</a></p>
  ${m.reviewed ? `<p class="fineprint">Written by ${esc(theme.practice.clinician)}. Last reviewed ${esc(m.reviewed)}.</p>` : ''}
  <p class="fineprint">${esc(theme.practice.copyright)}</p>
</footer>
</body>
</html>`;
}

function buildSheet(sheet, css, asArtifact = false) {
  const { resolve, usage } = makeResolver({
    library,
    globals: { ...theme, sheet: sheet.meta },
  });

  const blocks = resolve(sheet.blocks, { sheet: sheet.meta });

  const ctx = {
    sheetId: sheet.meta.id,
    renderAll: bs => renderBlocks(bs, ctx),
    relatedFor: (excludeId, only) =>
      index
        .filter(i => i.id !== excludeId)
        .filter(i => (only ? only.includes(i.id) : true))
        .map(({ href, title, desc }) => ({ href, title, desc })),
  };

  const heroBlock = blocks.find(b => b.type === 'hero') ?? {
    type: 'hero',
    eyebrow: sheet.meta.eyebrow,
    title: sheet.meta.title,
    subtitle: sheet.meta.summary,
  };
  const rest = blocks.filter(b => b !== heroBlock);

  // Every sheet ends the same way unless it opts out — written once, not seven times.
  const tail = [];
  if (sheet.meta.autoRelated !== false) tail.push(resolve('@fragment:related-sheets', { sheet: sheet.meta }));
  if (sheet.meta.autoCta !== false) tail.push(resolve('@fragment:cta-standard', { sheet: sheet.meta }));

  const html = (asArtifact ? artifactPage : page)({
    sheet,
    css,
    body: {
      hero: renderBlocks([heroBlock], ctx),
      main: renderBlocks([...rest, ...tail.flat()], ctx),
    },
  });

  return { html, usage: usage() };
}

function buildIndex(css, asArtifact = false) {
  const groups = [...new Set(index.map(i => i.group))];
  const blocks = [
    {
      type: 'intro',
      paras: [
        `These sheets are written for my own patients at ${theme.practice.name}. Each one is a practical, evidence-based programme you can start at home, on your own, today.`,
        `They are a starting point, not a substitute for the assessment and advice you receive in the consulting room. If something on these pages does not fit what you have been told about your own condition, what you have been told takes priority.`,
      ],
    },
    ...groups.flatMap(g => [
      { type: 'section', title: g, blocks: [{ type: 'related', title: null, items: index.filter(i => i.group === g).map(({ href, title, desc }) => ({ href, title, desc })) }] },
    ]),
  ];
  const sheet = {
    meta: {
      id: 'index',
      title: 'Patient Information Sheets',
      artifactTitle: 'East Neurology Patient Sheets',
      summary: `Evidence-based home programmes and self-management guides from ${theme.practice.clinician} at ${theme.practice.name}.`,
      eyebrow: theme.practice.name,
      autoCta: false,
      autoRelated: false,
    },
    blocks,
  };
  const ctx = { sheetId: 'index', renderAll: bs => renderBlocks(bs, ctx), relatedFor: () => [] };
  const heroBlock = { type: 'hero', eyebrow: sheet.meta.eyebrow, title: sheet.meta.title, subtitle: sheet.meta.summary };
  return (asArtifact ? artifactPage : page)({
    sheet,
    css,
    body: { hero: renderBlocks([heroBlock], ctx), main: renderBlocks(blocks, ctx) },
  });
}

/**
 * Artifact mode (`--artifacts`) emits the same pages as body-only fragments for
 * publishing as Claude Artifacts: no <html>/<head>/<body> wrapper, a clean title,
 * and cross-links rewritten to published URLs from content/artifact-urls.json
 * (falling back to the local filenames when a URL is not yet known).
 */
function artifactPage({ sheet, body, css }) {
  const m = sheet.meta;
  return `<title>${escText(m.artifactTitle ?? m.title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="${esc(theme.fonts.googleHref)}" rel="stylesheet">
<style>
${css}
</style>
<a class="skip-link" href="#main">Skip to content</a>
${body.hero}
<main id="main" class="container">
${body.main}
</main>
<footer>
  <p class="practice">${esc(theme.practice.name)}</p>
  <p>${esc(theme.practice.address)}</p>
  <p><a href="${esc(theme.practice.siteUrl)}">${esc(theme.practice.site)}</a></p>
  ${m.reviewed ? `<p class="fineprint">Written by ${esc(theme.practice.clinician)}. Last reviewed ${esc(m.reviewed)}.</p>` : ''}
  <p class="fineprint">${esc(theme.practice.copyright)}</p>
</footer>`;
}

const artifactUrls = (() => {
  try { return readJson('content/artifact-urls.json'); } catch { return {}; }
})();

function rewriteLinks(html) {
  return html.replace(/href="([a-z0-9-]+)\.html"/g, (whole, id) =>
    artifactUrls[id] ? `href="${artifactUrls[id]}"` : whole);
}

const only = process.argv[2];
const css = buildCss(theme);
fs.mkdirSync(path.join(ROOT, 'dist'), { recursive: true });

const artifactMode = process.argv.includes('--artifacts');
if (artifactMode) fs.mkdirSync(path.join(ROOT, 'dist/artifacts'), { recursive: true });

let count = 0;
const allUsage = new Map();
for (const sheet of sheets) {
  if (only && only !== '--artifacts' && sheet.meta.id !== only) continue;
  const { html, usage } = buildSheet(sheet, css, artifactMode);
  const out = artifactMode
    ? path.join(ROOT, 'dist/artifacts', `${sheet.meta.id}.html`)
    : path.join(ROOT, 'dist', `${sheet.meta.id}.html`);
  fs.writeFileSync(out, artifactMode ? rewriteLinks(html) : html);
  usage.forEach(u => allUsage.set(u, (allUsage.get(u) ?? 0) + 1));
  console.log(`  ✓ ${sheet.meta.id.padEnd(22)} ${(html.length / 1024).toFixed(1)} KB  ${sheet.meta.title}`);
  count++;
}
if (!only || artifactMode) {
  const idx = buildIndex(css, artifactMode);
  fs.writeFileSync(
    path.join(ROOT, artifactMode ? 'dist/artifacts' : 'dist', 'index.html'),
    artifactMode ? rewriteLinks(idx) : idx
  );
  console.log(`  ✓ ${'index'.padEnd(22)} contents page`);
}

const shared = [...allUsage.entries()].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1]);
console.log(`\nBuilt ${count} sheet(s). ${shared.length} content items were reused across sheets:`);
console.log(shared.slice(0, 12).map(([k, n]) => `    ${k} × ${n}`).join('\n'));
