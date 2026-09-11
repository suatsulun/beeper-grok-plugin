// Authenticated encryption across Grok's ordinary local/cloud tool transport.
// Only the cloud receiver keeps a private key. The local helper emits ciphertext.
import {generateKeyPairSync, createPublicKey, createPrivateKey, diffieHellman,
  hkdfSync, createHash, randomBytes, createCipheriv, createDecipheriv} from 'node:crypto';
import {validatePlan, validatePayload} from './browser_protocol.mjs';
import providers from './providers.mjs';

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ?
  Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const context = request => Buffer.from(JSON.stringify(canonical(request)));
const decode = value => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) throw Error('Invalid transfer.');
  return Buffer.from(value, 'base64url');
};
export function validateRequest(request, now = Date.now()) {
  if (request.version !== 1 || request.destination !== 'Beeper Server on Grok' ||
      !/^[\w-]{24,64}$/.test(request.id) || !Number.isSafeInteger(request.expires) ||
      request.expires <= now || request.expires > now + 610000 ||
      JSON.stringify(request).length > 32768) throw Error('Invalid or expired transfer request.');
  validatePlan(request.plan, providers);
  const key = createPublicKey({key:decode(request.publicKey), format:'der', type:'spki'});
  if (key.asymmetricKeyType !== 'x25519') throw Error('Invalid transfer key.');
  return request;
}
export function keypair() {
  const {publicKey, privateKey} = generateKeyPairSync('x25519');
  return {publicKey:publicKey.export({format:'der', type:'spki'}).toString('base64url'),
    privateKey:privateKey.export({format:'der', type:'pkcs8'}).toString('base64url')};
}
function aesKey(privateKey, publicKey, request) {
  const shared = diffieHellman({privateKey:createPrivateKey({key:decode(privateKey), format:'der', type:'pkcs8'}),
    publicKey:createPublicKey({key:decode(publicKey), format:'der', type:'spki'})});
  const key = hkdfSync('sha256', shared, createHash('sha256').update(context(request)).digest(), 'beeper-local-transfer-v1', 32);
  shared.fill(0);
  return key;
}
export function seal(request, payload) {
  validateRequest(request);
  validatePayload(request.plan, payload, providers);
  const pair = keypair(), iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', aesKey(pair.privateKey, request.publicKey, request), iv);
  cipher.setAAD(context(request));
  const plaintext = Buffer.from(JSON.stringify(payload));
  if (plaintext.length > 131072) throw Error('Transfer too large.');
  try {
    return {version:1, id:request.id, publicKey:pair.publicKey, iv:iv.toString('base64url'),
      ciphertext:Buffer.concat([cipher.update(plaintext), cipher.final()]).toString('base64url'),
      tag:cipher.getAuthTag().toString('base64url')};
  } finally { plaintext.fill(0); }
}
export function unseal(request, privateKey, envelope) {
  validateRequest(request);
  if (envelope.version !== 1 || envelope.id !== request.id || JSON.stringify(envelope).length > 200000) throw Error('Wrong transfer.');
  const iv = decode(envelope.iv), tag = decode(envelope.tag);
  if (iv.length !== 12 || tag.length !== 16) throw Error('Invalid transfer.');
  const decipher = createDecipheriv('aes-256-gcm', aesKey(privateKey, envelope.publicKey, request), iv);
  decipher.setAAD(context(request)); decipher.setAuthTag(tag);
  const plaintext = Buffer.concat([decipher.update(decode(envelope.ciphertext)), decipher.final()]);
  try { return validatePayload(request.plan, JSON.parse(plaintext.toString()), providers); }
  finally { plaintext.fill(0); }
}
