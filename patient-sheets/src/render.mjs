import { esc, md, paras, slug } from './inline.mjs';

/**
 * Block registry. A sheet is a list of blocks; each block's `type` picks a renderer.
 * Add a new visual component here once and every sheet can use it from JSON.
 */

const boxClass = { highlight: 'highlight-box', reassurance: 'reassurance-box', warning: 'warning-box' };

function boxHtml(b) {
  const cls = boxClass[b.kind ?? 'highlight'] ?? 'highlight-box';
  const title = b.title ? `<span class="box-title">${md(b.title)}</span>` : '';
  const body = b.list
    ? `<ul class="check-list${b.listStyle ? ' ' + b.listStyle : ''}">${b.list.map(i => `<li>${md(i)}</li>`).join('')}</ul>`
    : paras(b.text ?? b.paras);
  return `<div class="${cls}">${title}${body}</div>`;
}

function sectionOpen(b, renderAll) {
  const id = b.id ?? (b.title ? slug(b.title) : null);
  const head = [
    b.title ? `<h2 class="section-title">${md(b.title)}</h2>` : '',
    b.lede ? `<p class="section-lede">${md(b.lede)}</p>` : '',
  ].join('\n');
  return `<section${id ? ` id="${esc(id)}"` : ''}>\n${head}\n${renderAll(b.blocks ?? [])}\n</section>`;
}

export const renderers = {
  hero: b => `
<header class="hero">
  <div class="hero-inner">
    ${b.eyebrow ? `<span class="eyebrow">${md(b.eyebrow)}</span>` : ''}
    <h1>${md(b.title)}</h1>
    ${b.subtitle ? `<p>${md(b.subtitle)}</p>` : ''}
  </div>
</header>`,

  intro: b => `
<div class="intro">
  ${paras(b.paras ?? b.text)}
  ${b.box ? boxHtml(b.box) : ''}
</div>`,

  section: (b, ctx) => sectionOpen(b, ctx.renderAll),

  phaseBanner: b => `
<div class="phase-banner phase-${esc(b.variant ?? 'a')}">
  <h2>${md(b.title)}</h2>
  ${b.subtitle ? `<p>${md(b.subtitle)}</p>` : ''}
</div>`,

  steps: b => `
<div class="pathway">
${(b.items ?? []).map((s, i) => `
  <div class="step-card${s.type ? ' type-' + esc(s.type) : ''}">
    <div class="step-number">${esc(s.n ?? i + 1)}</div>
    ${s.badge ? `<span class="evidence-badge">${md(s.badge)}</span>` : ''}
    <h3>${md(s.title)}</h3>
    ${paras(s.body ?? s.text)}
    ${s.list ? `<ul class="check-list${s.listStyle ? ' ' + s.listStyle : ''}">${s.list.map(i2 => `<li>${md(i2)}</li>`).join('')}</ul>` : ''}
    ${s.box ? boxHtml(s.box) : ''}
  </div>`).join('')}
</div>`,

  cards: b => `
<div class="card-grid${b.variant === 'side' ? ' side-grid' : ''}">
${(b.items ?? []).map(c => `
  <div class="info-card${c.type ? ' type-' + esc(c.type) : ''}">
    <h4>${c.icon ? esc(c.icon) + ' ' : ''}${md(c.title)}</h4>
    ${paras(c.body ?? c.text)}
    ${c.list ? `<ul class="check-list${c.listStyle ? ' ' + c.listStyle : ''}">${c.list.map(i => `<li>${md(i)}</li>`).join('')}</ul>` : ''}
  </div>`).join('')}
</div>`,

  contentCards: b => (b.items ?? []).map(c => `
<div class="content-card">
  ${c.title ? `<h3>${md(c.title)}</h3>` : ''}
  ${paras(c.paras ?? c.text)}
  ${c.list ? `<ul class="check-list${c.listStyle ? ' ' + c.listStyle : ''}">${c.list.map(i => `<li>${md(i)}</li>`).join('')}</ul>` : ''}
</div>`).join('\n'),

  /** The core reusable unit: one prescribable exercise or technique. */
  exercises: b => (b.items ?? []).map(e => `
<div class="exercise-card" id="ex-${esc(slug(e.name))}">
  <div class="exercise-head">
    <h3>${md(e.name)}</h3>
    ${e.dose ? `<span class="dose-pill">${md(e.dose)}</span>` : ''}
  </div>
  ${e.badge ? `<span class="evidence-badge">${md(e.badge)}</span>` : ''}
  ${e.purpose ? `<p class="purpose">${md(e.purpose)}</p>` : ''}
  ${e.how_to?.length ? `<ol>${e.how_to.map(s => `<li>${md(s)}</li>`).join('')}</ol>` : ''}
  <div class="exercise-meta">
    ${e.progression ? `<div class="meta-item"><strong>Make it harder</strong>${md(e.progression)}</div>` : ''}
    ${e.regression ? `<div class="meta-item"><strong>Make it easier</strong>${md(e.regression)}</div>` : ''}
    ${e.safety ? `<div class="meta-item safety"><strong>Safety</strong>${md(e.safety)}</div>` : ''}
    ${e.evidence_note ? `<div class="meta-item"><strong>Why it works</strong>${md(e.evidence_note)}</div>` : ''}
  </div>
</div>`).join('\n'),

  box: b => boxHtml(b),

  researchNote: b => `<div class="research-note">${md(b.text)}</div>`,

  science: (b, ctx) => `
<section class="science-section"${b.id ? ` id="${esc(b.id)}"` : ''}>
  <h2>${md(b.title)}</h2>
  ${b.lede ? `<p class="section-lede">${md(b.lede)}</p>` : ''}
  ${ctx.renderAll(b.blocks ?? [{ type: 'cards', items: b.cards ?? [] }])}
</section>`,

  checklist: b => `
${b.title ? `<h3 class="section-title" style="font-size:1.25rem">${md(b.title)}</h3>` : ''}
<ul class="check-list${b.variant ? ' ' + esc(b.variant) : ''}">
${(b.items ?? []).map(i => `  <li>${md(i)}</li>`).join('\n')}
</ul>`,

  table: b => `
<div class="table-wrap">
  <table class="plan">
    ${b.head ? `<thead><tr>${b.head.map(h => `<th>${md(h)}</th>`).join('')}</tr></thead>` : ''}
    <tbody>
      ${(b.rows ?? []).map(r => `<tr>${r.map(c => `<td>${md(c)}</td>`).join('')}</tr>`).join('\n      ')}
    </tbody>
  </table>
</div>
${b.caption ? `<p class="section-lede" style="margin-top:.75rem;font-size:.92rem">${md(b.caption)}</p>` : ''}`,

  faq: b => `
<div class="faq">
${(b.items ?? []).map(f => `
  <details${f.open ? ' open' : ''}>
    <summary>${md(f.q)}</summary>
    ${paras(f.a)}
  </details>`).join('')}
</div>`,

  cta: b => `
<section class="cta">
  <h2>${md(b.title)}</h2>
  ${b.text ? `<p>${md(b.text)}</p>` : ''}
  ${b.buttons?.length ? `<div class="btn-row">${b.buttons.map(x => `<a class="btn${x.ghost ? ' ghost' : ''}" href="${esc(x.href)}">${md(x.label)}</a>`).join('')}</div>` : ''}
</section>`,

  related: (b, ctx) => {
    const items = b.items?.length ? b.items : ctx.relatedFor(b.exclude ?? ctx.sheetId, b.only);
    if (!items.length) return '';
    const heading = b.title === undefined ? 'Other information sheets' : b.title;
    return `
<section>
  ${heading ? `<h2 class="section-title">${md(heading)}</h2>` : ''}
  ${b.lede ? `<p class="section-lede">${md(b.lede)}</p>` : ''}
  <div class="related">
    ${items.map(i => `<a href="${esc(i.href)}"><strong>${md(i.title)}</strong><span>${md(i.desc)}</span></a>`).join('\n    ')}
  </div>
</section>`;
  },

  html: b => b.html ?? '',
};

export function renderBlocks(blocks, ctx) {
  return blocks
    .map(b => {
      if (!b || typeof b !== 'object') throw new Error(`Block must be an object, got: ${JSON.stringify(b)?.slice(0, 80)}`);
      const fn = renderers[b.type];
      if (!fn) throw new Error(`Unknown block type "${b.type}"`);
      return fn(b, ctx);
    })
    .join('\n');
}
