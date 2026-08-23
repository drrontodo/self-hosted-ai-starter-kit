/**
 * Reference + interpolation layer.
 *
 * This is what makes the sheets "soft-coded": a page is a list of blocks, and any
 * block, exercise or prose fragment can be pulled from a shared library instead of
 * being rewritten. Overlapping content (solo-exercise safety, hurt-vs-harm, red
 * flags, sit-to-stand, tandem gait...) is authored ONCE and referenced everywhere.
 *
 * Reference forms accepted anywhere in a sheet's JSON:
 *   "@fragment:solo-safety"                     -> the block(s) stored under that id
 *   "@exercise:sit-to-stand"                    -> the exercise object
 *   "@text:acceptable-soreness"                 -> a shared prose snippet (string)
 *   { "$ref": "exercise:tandem-gait",
 *     "set":    { "dose": "..." },              -> replace these fields
 *     "append": { "how_to": ["..."],            -> append to these array fields
 *                 "safety": " Extra sentence." } -> or concatenate onto a string
 *   }
 */

const REF_RE = /^@([a-z]+):([a-z0-9-]+)$/i;

export function makeResolver({ library, globals }) {
  const seen = [];

  function lookup(kind, id) {
    const bucket = library[kind];
    if (!bucket) throw new Error(`Unknown reference kind "${kind}" (in @${kind}:${id})`);
    if (!(id in bucket)) throw new Error(`Unknown ${kind} reference "${id}"`);
    seen.push(`${kind}:${id}`);
    return bucket[id];
  }

  /** {{practice.name}} / {{links.stress}} / {{sheet.title}} */
  function interpolate(str, scope) {
    return str.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (whole, path) => {
      const val = path.split('.').reduce((acc, k) => (acc == null ? acc : acc[k]), { ...globals, ...scope });
      if (val == null) throw new Error(`Unresolved token ${whole}`);
      return String(val);
    });
  }

  function applyPatch(base, patch) {
    const out = structuredClone(base);
    for (const [k, v] of Object.entries(patch.set ?? {})) out[k] = v;
    for (const [k, v] of Object.entries(patch.append ?? {})) {
      if (Array.isArray(out[k]) && Array.isArray(v)) out[k] = [...out[k], ...v];
      else if (typeof out[k] === 'string' && typeof v === 'string') out[k] = out[k] + v;
      else if (out[k] === undefined) out[k] = v;
      else throw new Error(`Cannot append ${typeof v} onto ${typeof out[k]} for field "${k}"`);
    }
    for (const [k, v] of Object.entries(patch.merge ?? {})) out[k] = { ...(out[k] ?? {}), ...v };
    return out;
  }

  function resolve(node, scope = {}, depth = 0) {
    if (depth > 24) throw new Error('Reference nesting too deep — is there a cycle?');

    if (typeof node === 'string') {
      const m = node.match(REF_RE);
      if (m) return resolve(lookup(m[1], m[2]), scope, depth + 1);
      return interpolate(node, scope);
    }
    if (Array.isArray(node)) return node.flatMap(n => {
      const r = resolve(n, scope, depth + 1);
      // A fragment may expand to several blocks; splice them into the parent list.
      return Array.isArray(r) && !Array.isArray(n) ? r : [r];
    });
    if (node && typeof node === 'object') {
      if (typeof node.$ref === 'string') {
        const [kind, id] = node.$ref.split(':');
        const base = resolve(lookup(kind, id), scope, depth + 1);
        const { $ref, ...patch } = node;
        return resolve(applyPatch(base, patch), scope, depth + 1);
      }
      const out = {};
      for (const [k, v] of Object.entries(node)) out[k] = resolve(v, scope, depth + 1);
      return out;
    }
    return node;
  }

  return { resolve, usage: () => seen.slice() };
}
