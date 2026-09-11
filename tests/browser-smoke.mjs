// Real Chromium, fresh profile, intercepted synthetic provider pages; no real sign-in.
import assert from 'node:assert/strict';
import {cp, readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser, collectSession} from '../skills/beeper/scripts/cloud_browser.mjs';
import {normalize} from '../browser-extension/protocol.mjs';
import providers from '../browser-extension/providers.mjs';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const options = JSON.parse(raw);
const sessionValue = 'synthetic-browser-session-only';
const extension = path.join(options.root, 'extension');
if (options.mode === 'extension') {
  await cp(new URL('../browser-extension', import.meta.url), extension, {recursive:true});
  const manifest = JSON.parse(await readFile(path.join(extension, 'manifest.json')));
  // Pregrant only synthetic test sites in this throwaway profile. Production
  // keeps optional permissions and asks for them from the popup's user gesture.
  manifest.host_permissions = ['https://*.instagram.com/*', 'http://127.0.0.1/*', ...(options.link ? [new URL(options.link).origin + '/*'] : [])];
  await writeFile(path.join(extension, 'manifest.json'), JSON.stringify(manifest));
}
const browser = await openBrowser({profile:path.join(options.root, 'chrome'), binary:options.binary, headless:true, extension:options.mode === 'extension' ? extension : undefined, extraArgs:['--host-resolver-rules=MAP *.instagram.com ~NOTFOUND']});
const originalSend = browser.send;
const installed = new Set();
const syntheticPage = '<!doctype html><title>Provider test fixture</title><h1>Provider test fixture</h1><script>localStorage.setItem("test_storage","synthetic-storage"); fetch("/api/check",{headers:{"Authorization":"synthetic-header"}});</script>';
async function intercept(sessionId) {
  if (installed.has(sessionId)) return;
  installed.add(sessionId);
  await originalSend('Network.enable', {}, sessionId);
  await originalSend('Network.setCookies', {cookies:[
    {name:'sessionid', value:sessionValue, domain:'.instagram.com', path:'/', secure:true, httpOnly:true},
    {name:'unrequested', value:'do-not-transfer', domain:'.instagram.com', path:'/', secure:true},
    {name:'sessionid', value:'wrong-provider', domain:'.facebook.com', path:'/', secure:true},
  ]}, sessionId);
  await originalSend('Fetch.enable', {patterns:[{urlPattern:'https://*.instagram.com/*', requestStage:'Request'}]}, sessionId);
}
browser.listeners.add(message => {
  if (message.method === 'Fetch.requestPaused') {
    const html = message.params.request.url.includes('/api/') ? '{}' : syntheticPage;
    void originalSend('Fetch.fulfillRequest', {requestId:message.params.requestId, responseCode:200, responseHeaders:[{name:'Content-Type',value:html === '{}' ? 'application/json' : 'text/html'}], body:Buffer.from(html).toString('base64')}, message.sessionId).catch(() => {});
  }
});
try {
  if (options.mode === 'cloud') {
    browser.send = async (method, params, sessionId) => {
      const result = await originalSend(method, params, sessionId);
      if (method === 'Network.enable') await intercept(sessionId);
      return result;
    };
    const plan = normalize({type:'cookies', url:'https://www.instagram.com/', fields:[
      {id:'sessionid', type:'cookie'},
      {id:'storage', type:'local_storage', name:'test_storage'},
      {id:'header', sources:[{type:'request_header',name:'Authorization',requestURLRegex:'/api/'}]},
    ]}, providers);
    const result = await collectSession(browser, plan, {timeout:12});
    assert.deepEqual({...result.fields}, {sessionid:sessionValue, storage:'synthetic-storage', header:'synthetic-header'});
    console.log('CLOUD_BROWSER_SMOKE_OK');
  } else {
    let worker;
    for (let attempt=0; attempt<30 && !worker; attempt++) {
      const {targetInfos} = await originalSend('Target.getTargets');
      worker = targetInfos.find(t => t.type === 'service_worker' && t.url.includes('background.mjs'));
      if (!worker) await new Promise(r => setTimeout(r, 100));
    }
    assert.ok(worker, 'Extension service worker loaded');
    // URL.origin is "null" for chrome-extension in Node; preserve its authority.
    const extensionBase = 'chrome-extension://' + new URL(worker.url).hostname;
    const {targetId} = await originalSend('Target.createTarget', {url:extensionBase + '/popup.html'});
    const {sessionId} = await originalSend('Target.attachToTarget', {targetId, flatten:true});
    await new Promise(r => setTimeout(r, 800));
    const evaluate = expression => originalSend('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true, userGesture:true}, sessionId);
    await evaluate(`document.getElementById('link').value=${JSON.stringify(options.link)}; document.getElementById('review').click(); document.getElementById('connect').click();`);
    let providerTab;
    for (let attempt=0; attempt<30 && !providerTab; attempt++) {
      providerTab = (await originalSend('Target.getTargets')).targetInfos.find(t => t.type === 'page' && t.url.startsWith('https://www.instagram.com/'));
      if (!providerTab) await new Promise(r => setTimeout(r, 100));
    }
    assert.ok(providerTab, 'The extension opened the selected provider website');
    const attached = await originalSend('Target.attachToTarget', {targetId:providerTab.targetId, flatten:true});
    await intercept(attached.sessionId);
    await originalSend('Page.navigate', {url:'https://www.instagram.com/'}, attached.sessionId);
    let status;
    for (let attempt=0; attempt<140; attempt++) {
      const result = await evaluate('chrome.storage.session.get("status").then(s => s.status)');
      status = result.result.value;
      if (status?.startsWith('Session submitted')) break;
      if (status?.includes('rejected') || status?.includes('could not be confirmed')) break;
      await new Promise(r => setTimeout(r, 250));
    }
    if (!status?.startsWith('Session submitted')) {
      const state = await evaluate('(async()=>{const {job}=await chrome.storage.session.get("job"); const tabs=await chrome.tabs.query({}); const stores=await chrome.cookies.getAllCookieStores(); const cookies=await chrome.cookies.getAll({name:"sessionid",domain:"instagram.com"});return {jobTab:job?.tabId,tabs:tabs.map(t=>({id:t.id,url:t.url})),stores,cookieNames:cookies.map(c=>({name:c.name,domain:c.domain,storeId:c.storeId}))};})()');
      console.error(JSON.stringify(state.result.value));
    }
    assert.ok(status?.startsWith('Session submitted'), 'Extension completion: ' + status);
    console.log('EXTENSION_BROWSER_SMOKE_OK');
  }
} finally { await browser.close(); }
