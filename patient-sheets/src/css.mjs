/**
 * The East Neurology house style, expressed once.
 * Every sheet in this project renders through this stylesheet — change a token
 * in content/theme.json (or a rule here) and all sheets update on next build.
 */
export function buildCss(theme) {
  const vars = Object.entries(theme.colors)
    .map(([k, v]) => `  --${k}: ${v};`)
    .join('\n');

  return `
:root {
${vars}
  --gradient-primary: ${theme.gradients.primary};
  --gradient-warm: ${theme.gradients.warm};
  --font-heading: ${theme.fonts.headingStack};
  --font-body: ${theme.fonts.bodyStack};
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--font-body);
  line-height: 1.7;
  color: var(--text-dark);
  background: var(--bg-cream);
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3, h4, h5 { font-family: var(--font-heading); font-weight: 700; line-height: 1.2; }

a { color: var(--primary); text-decoration: none; border-bottom: 1px solid rgba(26,95,122,.3); transition: all .2s ease; }
a:hover { color: var(--accent); border-bottom-color: var(--accent); }

.container { max-width: 900px; margin: 0 auto; padding: 0 1.5rem; }

/* ---------- Skip link (accessibility) ---------- */
.skip-link {
  position: absolute; left: -9999px; top: 0; background: #fff; color: var(--primary);
  padding: .75rem 1.25rem; z-index: 100; border-radius: 0 0 8px 0; font-weight: 600;
}
.skip-link:focus { left: 0; }

/* ---------- Header ---------- */
.hero {
  background: var(--gradient-primary);
  color: #fff;
  padding: 5rem 1.5rem 6rem;
  text-align: center;
  position: relative;
  overflow: hidden;
}
.hero::before {
  content: ''; position: absolute; inset: 0;
  background:
    radial-gradient(circle at 20% 30%, rgba(255,255,255,.10) 0%, transparent 45%),
    radial-gradient(circle at 80% 70%, rgba(230,126,34,.18) 0%, transparent 45%);
  pointer-events: none;
}
.hero-inner { position: relative; max-width: 820px; margin: 0 auto; }
.hero .eyebrow {
  display: inline-block; font-size: .8rem; letter-spacing: .14em; text-transform: uppercase;
  font-weight: 600; opacity: .9; margin-bottom: 1rem;
  border: 1px solid rgba(255,255,255,.35); border-radius: 50px; padding: .4rem 1rem;
  animation: fadeInUp .8s ease both;
}
.hero h1 {
  font-size: clamp(2.5rem, 5vw, 4rem);
  margin-bottom: 1.25rem;
  animation: fadeInUp .8s ease both;
}
.hero p {
  font-size: clamp(1.05rem, 2vw, 1.25rem);
  opacity: .95; max-width: 640px; margin: 0 auto;
  animation: fadeInUp .8s ease .2s both;
}

@keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: none; } }

/* ---------- Intro card ---------- */
.intro {
  background: #fff;
  max-width: 820px;
  margin: -3rem auto 3rem;
  padding: 2.5rem 2.5rem 2.5rem 3rem;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(26,95,122,.08);
  position: relative;
  overflow: hidden;
}
.intro::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  background: var(--gradient-warm);
}
.intro p { font-size: 1.125rem; line-height: 1.8; color: var(--text-medium); }
.intro p + p { margin-top: 1rem; }

/* ---------- Section shell ---------- */
section { margin-bottom: 3.5rem; }
.section-title {
  font-size: clamp(1.6rem, 3vw, 2.1rem);
  color: var(--primary);
  margin-bottom: .75rem;
}
.section-lede { color: var(--text-medium); margin-bottom: 2rem; font-size: 1.05rem; }

/* ---------- Phase banner ---------- */
.phase-banner {
  border-radius: 16px; padding: 2rem 1.5rem; text-align: center; margin-bottom: 2.25rem;
  border: 2px solid; background: var(--bg-light);
}
.phase-banner h2 { font-size: clamp(1.5rem, 3vw, 2rem); margin-bottom: .5rem; }
.phase-banner p { color: var(--text-medium); max-width: 620px; margin: 0 auto; }
.phase-a { border-color: rgba(26,95,122,.25); background: linear-gradient(135deg, #f2f8fa 0%, #e8f1f5 100%); }
.phase-a h2 { color: var(--primary); }
.phase-b { border-color: rgba(41,128,185,.25); background: linear-gradient(135deg, #f1f7fc 0%, #e4eff9 100%); }
.phase-b h2 { color: var(--phase-b); }
.phase-c { border-color: rgba(142,68,173,.22); background: linear-gradient(135deg, #f8f3fb 0%, #f0e6f7 100%); }
.phase-c h2 { color: var(--phase-c); }
.phase-warm { border-color: rgba(230,126,34,.25); background: linear-gradient(135deg, #fff6ec 0%, #ffeeda 100%); }
.phase-warm h2 { color: var(--accent); }

/* ---------- Pathway / numbered step cards ---------- */
.pathway { position: relative; padding-left: .5rem; }
.pathway::before {
  content: ''; position: absolute; left: 22px; top: 12px; bottom: 12px; width: 3px;
  background: linear-gradient(180deg, var(--primary) 0%, var(--accent) 100%);
  opacity: .3; border-radius: 3px;
}
.step-card {
  position: relative;
  background: #fff;
  border-radius: 16px;
  padding: 1.75rem 1.75rem 1.75rem 5rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 4px 20px rgba(0,0,0,.06);
  border-top: 3px solid var(--primary);
  transition: transform .25s ease, box-shadow .25s ease;
}
.step-card:hover { transform: translateY(-4px); box-shadow: 0 12px 32px rgba(26,95,122,.12); }
.step-card.type-accent { border-top-color: var(--accent); }
.step-card.type-success { border-top-color: var(--success); }
.step-card.type-purple { border-top-color: var(--phase-c); }
.step-card.type-blue { border-top-color: var(--phase-b); }
.step-number {
  position: absolute; left: 1rem; top: 1.6rem;
  width: 44px; height: 44px; border-radius: 50%;
  background: var(--gradient-primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-heading); font-weight: 700; font-size: 1.25rem;
}
.step-card.type-accent .step-number { background: var(--gradient-warm); }
.step-card.type-success .step-number { background: linear-gradient(135deg, #27ae60 0%, #2ecc71 100%); }
.step-card.type-purple .step-number { background: linear-gradient(135deg, #8e44ad 0%, #a569bd 100%); }
.step-card.type-blue .step-number { background: linear-gradient(135deg, #2980b9 0%, #5dade2 100%); }
.step-card h3 { color: var(--primary); font-size: 1.3rem; margin-bottom: .6rem; }
.step-card p { color: var(--text-medium); }
.step-card p + p { margin-top: .75rem; }
.evidence-badge {
  display: inline-block; background: var(--gradient-warm); color: #fff;
  font-size: .68rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
  padding: .25rem .7rem; border-radius: 50px; margin-bottom: .6rem;
}

/* ---------- Card grids ---------- */
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.75rem; }
.info-card {
  background: #fff; border-radius: 12px; padding: 1.5rem;
  border-top: 4px solid var(--primary);
  box-shadow: 0 4px 16px rgba(0,0,0,.05);
  transition: transform .25s ease, box-shadow .25s ease;
}
.info-card:hover { transform: translateY(-4px); box-shadow: 0 12px 28px rgba(26,95,122,.12); }
.info-card h4 { color: var(--primary); font-size: 1.1rem; margin-bottom: .5rem; }
.info-card p { color: var(--text-medium); font-size: .97rem; }
.info-card.type-accent { border-top-color: var(--accent); }
.info-card.type-accent h4 { color: var(--accent); }
.info-card.type-success { border-top-color: var(--success); }
.info-card.type-success h4 { color: var(--success); }
.info-card.type-purple { border-top-color: var(--phase-c); }
.info-card.type-purple h4 { color: var(--phase-c); }
.info-card.type-blue { border-top-color: var(--phase-b); }
.info-card.type-blue h4 { color: var(--phase-b); }
.info-card.type-danger { border-top-color: var(--danger); }
.info-card.type-danger h4 { color: var(--danger); }

/* Side-bordered variant (used for tests / options lists) */
.side-grid .info-card { border-top: none; border-left: 4px solid var(--primary); }
.side-grid .info-card.type-accent { border-left-color: var(--accent); }
.side-grid .info-card.type-success { border-left-color: var(--success); }
.side-grid .info-card.type-purple { border-left-color: var(--phase-c); }
.side-grid .info-card.type-blue { border-left-color: var(--phase-b); }
.side-grid .info-card.type-danger { border-left-color: var(--danger); }

/* ---------- Exercise cards ---------- */
.exercise-card {
  background: #fff; border-radius: 16px; padding: 1.75rem;
  box-shadow: 0 4px 20px rgba(0,0,0,.06);
  border-top: 3px solid var(--accent);
  margin-bottom: 1.5rem;
}
.exercise-head { display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap; margin-bottom: .35rem; }
.exercise-card h3 { color: var(--primary); font-size: 1.25rem; }
.exercise-card .purpose { color: var(--text-medium); font-style: italic; margin-bottom: 1rem; }
.exercise-card ol { margin: 0 0 1rem 1.2rem; color: var(--text-medium); }
.exercise-card ol li { margin-bottom: .45rem; padding-left: .2rem; }
.exercise-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: .75rem; margin-top: 1rem; }
.meta-item {
  background: var(--bg-light); border-radius: 10px; padding: .8rem 1rem;
  font-size: .92rem; color: var(--text-medium);
}
.meta-item strong { display: block; color: var(--primary); font-size: .72rem; letter-spacing: .09em; text-transform: uppercase; margin-bottom: .25rem; }
.meta-item.safety { background: #fdf3ef; }
.meta-item.safety strong { color: var(--accent); }
.dose-pill {
  display: inline-block; background: rgba(26,95,122,.09); color: var(--primary);
  border-radius: 50px; padding: .25rem .8rem; font-size: .82rem; font-weight: 600;
}

/* ---------- Boxes ---------- */
.highlight-box {
  background: linear-gradient(135deg, #fff5e6 0%, #ffe8cc 100%);
  border-left: 4px solid var(--accent);
  border-radius: 0 12px 12px 0;
  padding: 1.25rem 1.5rem; margin: 1.5rem 0;
  font-style: italic; color: var(--text-dark);
}
.reassurance-box {
  background: linear-gradient(135deg, #e8f8f0 0%, #d5f5e3 100%);
  border-left: 4px solid var(--success);
  border-radius: 0 12px 12px 0;
  padding: 1.25rem 1.5rem; margin: 1.5rem 0;
  color: var(--text-dark);
}
.warning-box {
  background: linear-gradient(135deg, #fdecea 0%, #fadbd8 100%);
  border-left: 4px solid var(--danger);
  border-radius: 0 12px 12px 0;
  padding: 1.25rem 1.5rem; margin: 1.5rem 0;
  color: var(--text-dark);
}
.box-title { display: block; font-family: var(--font-heading); font-weight: 700; font-size: 1.05rem; margin-bottom: .4rem; font-style: normal; }
.highlight-box .box-title { color: var(--accent); }
.reassurance-box .box-title { color: var(--success); }
.warning-box .box-title { color: var(--danger); }
.research-note {
  background: var(--bg-light); border-radius: 10px; padding: 1rem 1.25rem;
  font-size: .9rem; color: var(--text-light); font-style: italic; margin: 1.25rem 0;
}
.content-card {
  background: #fff; border-radius: 16px; padding: 1.75rem 1.75rem 1.75rem 2.25rem;
  box-shadow: 0 4px 20px rgba(0,0,0,.06); position: relative; overflow: hidden; margin-bottom: 1.5rem;
}
.content-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--gradient-warm); }
.content-card h3 { color: var(--primary); margin-bottom: .6rem; }
.content-card p { color: var(--text-medium); }
.content-card p + p { margin-top: .75rem; }

/* ---------- Science / info section ---------- */
.science-section {
  background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
  border-radius: 16px; padding: 3rem 2rem;
}
.science-section > h2 { text-align: center; color: var(--primary); font-size: clamp(1.5rem, 3vw, 2rem); margin-bottom: .6rem; }
.science-section > .section-lede { text-align: center; max-width: 640px; margin: 0 auto 2rem; }
.science-section .info-card { box-shadow: 0 2px 12px rgba(0,0,0,.06); }

/* ---------- Lists ---------- */
.check-list { list-style: none; }
.check-list li { position: relative; padding: .7rem 0 .7rem 2rem; border-bottom: 1px solid var(--border); color: var(--text-medium); }
.check-list li:last-child { border-bottom: none; }
.check-list li::before { content: '✓'; position: absolute; left: 0; top: .7rem; color: var(--success); font-weight: 700; }
.check-list.cross li::before { content: '✕'; color: var(--danger); }
.check-list.arrow li::before { content: '→'; color: var(--accent); }
.check-list li strong { color: var(--text-dark); }

/* ---------- Weekly plan table ---------- */
.table-wrap { overflow-x: auto; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,.06); background: #fff; }
table.plan { width: 100%; border-collapse: collapse; min-width: 520px; }
table.plan th, table.plan td { padding: .9rem 1rem; text-align: left; border-bottom: 1px solid var(--border); font-size: .95rem; }
table.plan thead th { background: var(--gradient-primary); color: #fff; font-family: var(--font-heading); font-size: .95rem; letter-spacing: .02em; }
table.plan tbody tr:nth-child(even) { background: var(--bg-light); }
table.plan tbody tr:last-child td { border-bottom: none; }
table.plan td { color: var(--text-medium); }
table.plan td:first-child { color: var(--text-dark); font-weight: 600; }

/* ---------- FAQ ---------- */
.faq details {
  background: #fff; border-radius: 12px; padding: 1.1rem 1.4rem; margin-bottom: .9rem;
  box-shadow: 0 3px 14px rgba(0,0,0,.05); border-left: 4px solid var(--primary-light);
}
.faq summary { cursor: pointer; font-family: var(--font-heading); font-weight: 700; color: var(--primary); font-size: 1.05rem; }
.faq summary::-webkit-details-marker { display: none; }
.faq summary::after { content: '+'; float: right; color: var(--accent); font-size: 1.3rem; line-height: 1; }
.faq details[open] summary::after { content: '–'; }
.faq details p { color: var(--text-medium); margin-top: .8rem; }
.faq details p + p { margin-top: .6rem; }

/* ---------- CTA ---------- */
.cta {
  background: var(--gradient-primary); color: #fff; border-radius: 16px;
  padding: 3rem 2rem; text-align: center; position: relative; overflow: hidden;
}
.cta::before {
  content: ''; position: absolute; inset: 0;
  background: radial-gradient(circle at 75% 25%, rgba(230,126,34,.22) 0%, transparent 50%);
}
.cta > * { position: relative; }
.cta h2 { font-size: clamp(1.5rem, 3vw, 2rem); margin-bottom: .75rem; }
.cta p { opacity: .95; max-width: 560px; margin: 0 auto 1.75rem; }
.btn-row { display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; }
.btn {
  display: inline-block; background: #fff; color: var(--primary);
  padding: .85rem 1.9rem; border-radius: 50px; font-weight: 600; border: none;
  transition: transform .2s ease, box-shadow .2s ease;
}
.btn:hover { transform: translateY(-3px); box-shadow: 0 10px 24px rgba(0,0,0,.2); color: var(--primary); border: none; }
.btn.ghost { background: transparent; color: #fff; border: 2px solid rgba(255,255,255,.7); }
.btn.ghost:hover { background: rgba(255,255,255,.12); color: #fff; }

/* ---------- Related sheets ---------- */
.related { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1.25rem; }
.related a {
  display: block; background: #fff; border-radius: 12px; padding: 1.25rem 1.4rem;
  border: 1px solid var(--border); border-left: 4px solid var(--accent);
  box-shadow: 0 3px 14px rgba(0,0,0,.05); transition: transform .2s ease, box-shadow .2s ease;
}
.related a:hover { transform: translateY(-3px); box-shadow: 0 10px 24px rgba(26,95,122,.12); }
.related a strong { display: block; font-family: var(--font-heading); color: var(--primary); font-size: 1.05rem; margin-bottom: .25rem; }
.related a span { color: var(--text-medium); font-size: .92rem; }

/* ---------- Footer ---------- */
footer {
  text-align: center; color: var(--text-light); font-size: .92rem;
  padding: 3rem 1.5rem 4rem; border-top: 1px solid var(--border); margin-top: 3rem;
}
footer p + p { margin-top: .5rem; }
footer .practice { font-family: var(--font-heading); color: var(--primary); font-size: 1.05rem; }
footer .fineprint { font-size: .82rem; max-width: 620px; margin: 1rem auto 0; }

/* ---------- Responsive ---------- */
@media (max-width: 768px) {
  .hero { padding: 3.5rem 1.25rem 4.5rem; }
  .intro { margin: -2.5rem 1rem 2.5rem; padding: 1.75rem 1.5rem 1.75rem 2rem; }
  .step-card { padding: 1.5rem 1.25rem 1.5rem 4.5rem; }
  .step-number { width: 36px; height: 36px; font-size: 1.05rem; left: .8rem; top: 1.4rem; }
  .pathway::before { left: 17px; }
  .science-section { padding: 2rem 1.25rem; }
  .cta { padding: 2.25rem 1.25rem; }
  .exercise-card { padding: 1.4rem; }
}

/* ---------- Print (these sheets get handed out on paper) ---------- */
@media print {
  body { background: #fff; font-size: 11pt; }
  .hero { padding: 1.5rem 0; background: none; color: var(--primary); }
  .hero::before, .cta::before, .intro::before { display: none; }
  .hero .eyebrow { border-color: var(--border); color: var(--text-medium); }
  .hero p { color: var(--text-medium); }
  .intro, .step-card, .info-card, .exercise-card, .content-card, .faq details { box-shadow: none; border: 1px solid var(--border); }
  .cta { background: none; color: var(--text-dark); border: 1px solid var(--border); }
  .cta h2 { color: var(--primary); }
  .btn { border: 1px solid var(--border); color: var(--primary); }
  .step-card, .exercise-card, .info-card, .highlight-box, .reassurance-box, .warning-box { break-inside: avoid; }
  .faq details { break-inside: avoid; }
  .faq details summary::after { display: none; }
  section { margin-bottom: 1.5rem; }
  a { border-bottom: none; }
}
`.trim();
}
