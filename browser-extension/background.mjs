import {pairingLink, providerURL, safeRegex, selectFields, complete, encrypt} from './protocol.mjs';
import providers from './providers.mjs';
let busy = false;
let queued = false;
let generation = 0;
let starting = false;
let observedHeaders = Object.create(null);
async function finish(status) {
  observedHeaders = Object.create(null);
  await chrome.storage.session.remove('job');
  await chrome.storage.session.set({status});
  await chrome.alarms.clear('beeper-connect');
}
async function collect() {
  if (busy) { queued = true; return; }
  busy = true;
  const startedGeneration = generation;
  try {
    const {job} = await chrome.storage.session.get('job');
    if (!job) return;
    const {descriptor, tabId} = job;
    if (Date.now() >= descriptor.expires) return await finish('Handoff expired. Ask Grok for a new link.');
    const plan = descriptor.plan;
    const provider = providers.find(p => p.id === plan.provider);
    const tab = await chrome.tabs.get(tabId);
    try { providerURL(tab.url, provider); } catch { return; }
    const stores = await chrome.cookies.getAllCookieStores();
    const storeId = stores.find(s => s.tabIds.includes(tabId))?.id;
    if (!storeId) return;
    const cookies = [];
    for (const field of plan.fields) for (const source of field.sources) {
      if (source.type === 'cookie') {
        // URL scoping excludes another workspace/subdomain's host-only cookies.
        for (const url of new Set([tab.url, 'https://' + source.domain + '/'])) {
          cookies.push(...await chrome.cookies.getAll({name:source.name, domain:source.domain, url, storeId}));
        }
      }
    }
    const names = [...new Set(plan.fields.flatMap(f => f.sources.filter(s => s.type === 'local_storage').map(s => s.name)))];
    let storage = {};
    if (names.length) {
      const results = await chrome.scripting.executeScript({target:{tabId}, func: keys => Object.fromEntries(keys.map(key => [key, localStorage.getItem(key)])), args:[names]});
      storage = results[0]?.result || {};
    }
    const fields = selectFields(plan, cookies, storage, observedHeaders);
    if (!complete(plan, fields, tab.url, providers)) return;
    // Cancellation or replacement during collection invalidates this attempt.
    const latest = (await chrome.storage.session.get('job')).job;
    if (!latest || latest.descriptor.id !== descriptor.id) return;
    const envelope = await encrypt(descriptor, {fields, lastURL:tab.url});
    if (startedGeneration !== generation) return;
    // Forget the job before sending: do not automatically retry an ambiguous POST.
    await finish('Sending encrypted session to Beeper…');
    if (startedGeneration !== generation) return;
    try {
      const response = await fetch(descriptor.origin + '/handoff/' + descriptor.id, {
        method:'POST', headers:{'Content-Type':'application/json', 'X-Beeper-Pairing':descriptor.capability},
        body:JSON.stringify(envelope), credentials:'omit', redirect:'error', referrerPolicy:'no-referrer', signal:AbortSignal.timeout(45000)
      });
      await chrome.storage.session.set({status:response.ok ? 'Session submitted. Return to Grok to check the connection.' : `The handoff was rejected (HTTP ${response.status}). Ask Grok to check network-show before retrying.`});
    } catch { await chrome.storage.session.set({status:'Delivery could not be confirmed. Ask Grok to check network-show and accounts before retrying.'}); }
  } catch { await chrome.storage.session.set({status:'Waiting for the provider page and site permissions. Complete sign-in there, then reload the page if needed.'}); }
  finally {
    busy = false;
    if (queued) { queued = false; queueMicrotask(collect); }
  }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message.action === 'start' && starting) { respond({message:'A connection is already starting.'}); return; }
  if (message.action === 'start') starting = true;
  const requestGeneration = generation;
  (async () => {
    if (message.action === 'cancel') { generation++; await finish('Handoff cancelled. If submission already began, ask Grok to check network-show.'); return {message:'Cancelled.'}; }
    if (message.action !== 'start') return {message:'Unknown action.'};
    if (busy || (await chrome.storage.session.get('job')).job) return {message:'A handoff is already active. Finish or cancel it first.'};
    const descriptor = pairingLink(message.link, providers);
    const provider = providers.find(p => p.id === descriptor.plan.provider);
    if (!await chrome.permissions.contains({origins:[...provider.domains.map(d => `https://*.${d}/*`), descriptor.origin + '/*']})) return {message:'Grant the requested site access first.'};
    if (requestGeneration !== generation) return {message:'Handoff cancelled.'};
    observedHeaders = Object.create(null);
    const tab = await chrome.tabs.create({url:descriptor.plan.url, active:true});
    if (requestGeneration !== generation) { await chrome.tabs.remove(tab.id); return {message:'Handoff cancelled.'}; }
    await chrome.storage.session.set({job:{descriptor, tabId:tab.id}, status:'Sign in on the provider website. The required session will be sent automatically when ready.'});
    await chrome.alarms.create('beeper-connect', {periodInMinutes:0.5});
    await collect();
    return {message:'Provider website opened. Complete sign-in there, then return to Grok.'};
  })().then(result => { if (message.action === 'start') starting = false; respond(result); }, () => { if (message.action === 'start') starting = false; respond({message:'Invalid or expired pairing link.'}); });
  return true;
});
chrome.tabs.onUpdated.addListener(() => { void collect(); });
chrome.tabs.onRemoved.addListener(async tabId => {
  const {job} = await chrome.storage.session.get('job');
  if (job?.tabId === tabId) { generation++; await finish('Provider tab closed. Handoff cancelled.'); }
});
chrome.cookies.onChanged.addListener(() => { void collect(); });
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'beeper-connect') void collect(); });
// Restrict header observation to the selected tab and supported provider hosts.
chrome.webRequest.onBeforeSendHeaders.addListener(async details => {
  const requestGeneration = generation;
  const {job} = await chrome.storage.session.get('job');
  if (requestGeneration !== generation || !job || job.tabId !== details.tabId || Date.now() >= job.descriptor.expires) return;
  const plan = job.descriptor.plan;
  const provider = providers.find(p => p.id === plan.provider);
  try { providerURL(details.url, provider); } catch { return; }
  for (const field of plan.fields) for (const source of field.sources) {
    if (source.type !== 'request_header' || (source.requestURLRegex && !safeRegex(source.requestURLRegex).test(details.url))) continue;
    const value = details.requestHeaders?.find(h => h.name.toLowerCase() === source.name.toLowerCase())?.value;
    if (value && value.length <= 16384) observedHeaders[field.id] = value;
  }
  void collect();
}, {urls:providers.flatMap(p => p.domains.map(d => `https://*.${d}/*`))}, ['requestHeaders', 'extraHeaders']);
