// Exercise extension permission, cancellation and header scoping with synthetic
// Chrome events. Native browser collection is covered separately.
import assert from 'node:assert/strict';
import {normalize, keypair, b64, decrypt} from '../browser-extension/protocol.mjs';
import providers from '../browser-extension/providers.mjs';
const event = () => ({listeners:[], addListener(fn) { this.listeners.push(fn); }});
const state = {};
let granted = false, sent;
const onMessage = event(), onHeaders = event();
globalThis.chrome = {
  runtime:{id:'synthetic-extension', onMessage},
  storage:{session:{get:async key => ({[key]:structuredClone(state[key])}), set:async data => Object.assign(state, structuredClone(data)), remove:async key => { delete state[key]; }}},
  permissions:{contains:async () => granted},
  tabs:{create:async () => ({id:7}), get:async () => ({id:7,url:'https://discord.com/channels/@me'}), remove:async () => {}, onUpdated:event(), onRemoved:event()},
  cookies:{getAllCookieStores:async () => [{id:'0',tabIds:[7]}], getAll:async () => [], onChanged:event()},
  alarms:{create:async () => {}, clear:async () => {}, onAlarm:event()},
  webRequest:{onBeforeSendHeaders:onHeaders},
};
globalThis.fetch = async (url, options) => { sent = {url, options}; return {ok:true, status:200}; };
await import('../browser-extension/background.mjs');
const pair = await keypair();
const plan = normalize({type:'cookies',url:'https://discord.com/login',fields:[{id:'auth',sources:[{type:'request_header',name:'Authorization',requestURLRegex:'/api/'}]}]}, providers);
const descriptor = {version:1,id:'a'.repeat(24),capability:'b'.repeat(43),origin:'https://synthetic.trycloudflare.com',expires:Date.now()+600000,publicKey:pair.publicKey,plan};
const link = descriptor.origin + '/connect#' + b64(new TextEncoder().encode(JSON.stringify(descriptor)));
const message = data => new Promise(resolve => onMessage.listeners[0](data, {id:chrome.runtime.id}, resolve));
const headers = (tabId, url) => onHeaders.listeners[0]({tabId,url,requestHeaders:[{name:'Authorization',value:'synthetic-header-secret'},{name:'Unrelated',value:'do-not-collect'}]});
await message({action:'start',link});
assert.equal(state.job, undefined, 'Permission denial cannot begin collection');
granted = true;
await message({action:'start',link});
await headers(999, 'https://discord.com/api/me');
await headers(7, 'https://discord.com.attacker.example/api/me');
await headers(7, 'https://discord.com/not-the-request');
assert.equal(sent, undefined, 'Unrelated tabs, hosts and requests cannot supply session fields');
await message({action:'cancel'});
await headers(7, 'https://discord.com/api/me');
assert.equal(sent, undefined, 'Cancellation prevents collection');
await message({action:'start',link});
await headers(7, 'https://discord.com/api/me');
for (let attempt=0; attempt<100 && !sent; attempt++) await new Promise(r => setTimeout(r, 10));
assert.ok(sent, 'Selected provider header was transferred');
assert.ok(!sent.options.body.includes('synthetic-header-secret'));
assert.deepEqual(await decrypt(descriptor, pair.privateKey, JSON.parse(sent.options.body)), {fields:{auth:'synthetic-header-secret'},lastURL:'https://discord.com/channels/@me'});
assert.equal(state.job, undefined, 'The job is consumed before submission');
console.log('EXTENSION_EVENT_TESTS_OK');
