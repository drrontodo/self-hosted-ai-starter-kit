/** Escape HTML, then apply a tiny, safe inline-markdown subset so content JSON stays readable. */
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
}

/** Escape only what must be escaped in text content — keeps apostrophes readable in <title>. */
export function escText(s) {
  return String(s ?? '').replace(/[&<>]/g, c => ESC[c]);
}

/**
 * Supported in content strings:
 *   **bold**  *italic*  `code`  [label](https://url)  --  (en dash)
 */
export function md(s) {
  let out = esc(s);
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|[^)\s]+\.html)\)/g, '<a href="$2">$1</a>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[\s(])\*([^*]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  return out;
}

/** Render an array (or single string) of paragraphs. */
export function paras(input, cls = '') {
  const list = Array.isArray(input) ? input : input ? [input] : [];
  const c = cls ? ` class="${cls}"` : '';
  return list.map(p => `<p${c}>${md(p)}</p>`).join('\n');
}

/** slugify for anchors/ids */
export function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}
