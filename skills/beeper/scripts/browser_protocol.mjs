// Validate provider requirements and collect only named fields. Never run bridge-supplied JavaScript.
const encoder = new TextEncoder();
// Compare plans independently of object insertion order.
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
export const inDomain = (host, domain) => host === domain || host.endsWith('.' + domain);
function check(ok) { if (!ok) throw new Error('Unsupported or invalid browser login requirements.'); }
export function safeRegex(pattern) {
  if (!pattern) return null;
  // Conservative subset: optional groups are allowed; repeated groups are not.
  check(typeof pattern === 'string' && pattern.length <= 512 && !/\)[*+{]|\\[1-9]|\(\?(?!:)/.test(pattern));
  return new RegExp(pattern);
}
export function providerURL(raw, provider) {
  const url = new URL(raw);
  check(url.protocol === 'https:' && !url.username && !url.password && !url.port && provider.domains.some(d => inDomain(url.hostname, d)));
  return url;
}
export function normalize(step, providers) {
  check(step?.type === 'cookies');
  const host = new URL(step.url).hostname;
  const provider = providers.find(p => p.domains.some(d => inDomain(host, d)));
  check(provider);
  const url = providerURL(step.url, provider);
  check(Array.isArray(step.fields) && step.fields.length > 0 && step.fields.length <= 32);
  safeRegex(step.expectedFinalURLRegex);
  const fields = step.fields.map(field => {
    check(typeof field.id === 'string' && /^[\w.-]{1,100}$/.test(field.id) && !['__proto__','constructor','prototype'].includes(field.id));
    safeRegex(field.pattern);
    const raw = field.sources?.length ? field.sources : [{type: field.type === 'header' ? 'request_header' : field.type === 'local_storage' ? 'local_storage' : 'cookie', name: field.name || field.id, cookieDomain: field.cookieDomain}];
    check(Array.isArray(raw) && raw.length <= 8);
    const sources = raw.flatMap(source => {
      if (!['cookie','local_storage','request_header'].includes(source.type)) return [];
      check(typeof source.name === 'string' && source.name.length > 0 && source.name.length <= 200 && !/[\r\n]/.test(source.name));
      const s = {type:source.type, name:source.name};
      if (source.type === 'cookie') {
        s.domain = (source.cookieDomain || source.domain || provider.domains.find(d => inDomain(url.hostname, d))).replace(/^\./, '').toLowerCase();
        check(provider.domains.some(d => inDomain(s.domain, d)));
      }
      if (source.type === 'request_header') {
        safeRegex(source.requestURLRegex);
        s.requestURLRegex = source.requestURLRegex || '';
      }
      return [s];
    });
    const required = field.required ?? !field.optional;
    check(!required || sources.length > 0);
    return {id:field.id, required, pattern:field.pattern || '', sources};
  }).filter(f => f.sources.length);
  check(fields.some(f => f.required) && new Set(fields.map(f => f.id)).size === fields.length);
  const plan = {provider:provider.id, url:url.href, expectedFinalURLRegex:step.expectedFinalURLRegex || '', fields};
  check(encoder.encode(JSON.stringify(plan)).length <= 16000);
  return plan;
}
export function validatePlan(plan, providers) {
  const reconstructed = normalize({type:'cookies', ...plan}, providers);
  check(JSON.stringify(canonical(reconstructed)) === JSON.stringify(canonical(plan)));
  return providers.find(p => p.id === plan.provider);
}
export function complete(plan, fields, lastURL, providers) {
  const provider = providers.find(p => p.id === plan.provider);
  try { providerURL(lastURL, provider); } catch { return false; }
  if (plan.expectedFinalURLRegex && !safeRegex(plan.expectedFinalURLRegex).test(lastURL)) return false;
  return plan.fields.every(f => !f.required || (typeof fields[f.id] === 'string' && fields[f.id].length > 0 && fields[f.id].length <= 16384 && (!f.pattern || safeRegex(f.pattern).test(fields[f.id]))));
}
export function selectFields(plan, cookies, storage = {}, headers = {}) {
  const fields = Object.create(null);
  for (const f of plan.fields) for (const s of f.sources) {
    let value;
    if (s.type === 'cookie') value = cookies.find(c => !c.partitionKey && c.name === s.name && inDomain(c.domain.replace(/^\./, ''), s.domain))?.value;
    if (s.type === 'local_storage') value = storage[s.name];
    if (s.type === 'request_header') value = headers[f.id];
    if (typeof value === 'string' && value.length > 0 && value.length <= 16384 && (!f.pattern || safeRegex(f.pattern).test(value))) { fields[f.id] = value; break; }
  }
  return fields;
}
