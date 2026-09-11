// Shared by the extension and the receiver. No bridge-supplied JavaScript runs.
const encoder = new TextEncoder();
// Chrome's session storage can reorder object keys. Authentication must bind
// the same descriptor regardless of object insertion order.
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
export const label = 'beeper-browser-handoff-v1';
export const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
export const unb64 = text => Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/')), c => c.charCodeAt(0));
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
export async function context(descriptor) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(JSON.stringify(canonical(descriptor)))));
}
async function aesKey(privateKey, publicKey, salt) {
  const secret = await crypto.subtle.deriveBits({name:'ECDH', public:publicKey}, privateKey, 256);
  const material = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey({name:'HKDF', hash:'SHA-256', salt, info:encoder.encode(label)}, material, {name:'AES-GCM', length:256}, false, ['encrypt','decrypt']);
}
export async function keypair() {
  const pair = await crypto.subtle.generateKey({name:'ECDH', namedCurve:'P-256'}, true, ['deriveBits']);
  return {privateKey:await crypto.subtle.exportKey('jwk', pair.privateKey), publicKey:b64(await crypto.subtle.exportKey('raw', pair.publicKey))};
}
export async function encrypt(descriptor, payload) {
  check(encoder.encode(JSON.stringify(payload)).length <= 65536);
  const pair = await crypto.subtle.generateKey({name:'ECDH', namedCurve:'P-256'}, false, ['deriveBits']);
  const receiver = await crypto.subtle.importKey('raw', unb64(descriptor.publicKey), {name:'ECDH', namedCurve:'P-256'}, false, []);
  const binding = await context(descriptor);
  const key = await aesKey(pair.privateKey, receiver, binding);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  return {publicKey:b64(await crypto.subtle.exportKey('raw', pair.publicKey)), iv:b64(iv), ciphertext:b64(await crypto.subtle.encrypt({name:'AES-GCM', iv, additionalData:binding}, key, encoder.encode(JSON.stringify(payload))))};
}
export async function decrypt(descriptor, privateJWK, envelope) {
  const privateKey = await crypto.subtle.importKey('jwk', privateJWK, {name:'ECDH', namedCurve:'P-256'}, false, ['deriveBits']);
  const sender = await crypto.subtle.importKey('raw', unb64(envelope.publicKey), {name:'ECDH', namedCurve:'P-256'}, false, []);
  const binding = await context(descriptor);
  const key = await aesKey(privateKey, sender, binding);
  return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM', iv:unb64(envelope.iv), additionalData:binding}, key, unb64(envelope.ciphertext))));
}
export function pairingLink(raw, providers) {
  const url = new URL(raw);
  check((url.protocol === 'https:' && /^[a-z0-9-]+\.trycloudflare\.com$/.test(url.hostname) && !url.port) || (url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port));
  check(!url.username && !url.password && url.pathname === '/connect' && !url.search && url.hash.length < 32768);
  const descriptor = JSON.parse(new TextDecoder().decode(unb64(url.hash.slice(1))));
  check(descriptor.version === 1 && descriptor.origin === url.origin && /^[\w-]{40,64}$/.test(descriptor.capability) && /^[\w-]{20,64}$/.test(descriptor.id));
  check(descriptor.expires > Date.now() && descriptor.expires <= Date.now() + 660000);
  check(unb64(descriptor.publicKey).length === 65);
  validatePlan(descriptor.plan, providers);
  return descriptor;
}
