// Real Chromium, fresh profile, intercepted synthetic provider pages; no real sign-in.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser, attachBrowser, collectSession} from '../skills/beeper/scripts/cloud_browser.mjs';
import {normalize} from '../skills/beeper/scripts/browser_protocol.mjs';
import providers from '../skills/beeper/scripts/providers.mjs';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const options = JSON.parse(raw);
const sessionValue = 'synthetic-browser-session-only';
const owner = await openBrowser({profile:path.join(options.root, 'chrome'), binary:options.binary, headless:true,
  extraArgs:['--host-resolver-rules=MAP *.instagram.com ~NOTFOUND', ...(options.mode === 'native' ? ['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1'] : [])]});
let browser = owner, untouched;
if (options.mode === 'native') {
  let port;
  for (let attempt=0; attempt<50 && !port; attempt++) {
    try { port = (await readFile(path.join(options.root, 'chrome/DevToolsActivePort'), 'utf8')).split('\n')[0]; }
    catch { await new Promise(r => setTimeout(r, 100)); }
  }
  assert.ok(port, 'Test browser exposes its own loopback endpoint');
  untouched = (await owner.send('Target.createTarget', {url:'about:blank'})).targetId;
  // Stand in for Grok's approved importer, populating the receiving browser
  // before the plugin connects. This is not a test of Grok's approval feature.
  await owner.send('Storage.setCookies', {cookies:[
    {name:'sessionid', value:sessionValue, domain:'.instagram.com', path:'/', secure:true, httpOnly:true},
    {name:'unrequested', value:'do-not-transfer', domain:'.instagram.com', path:'/', secure:true},
    {name:'sessionid', value:'wrong-provider', domain:'.facebook.com', path:'/', secure:true},
  ]});
  browser = await attachBrowser('http://127.0.0.1:' + port);
}
const originalSend = browser.send;
const installed = new Set();
const syntheticPage = '<!doctype html><title>Provider test fixture</title><h1>Provider test fixture</h1><script>localStorage.setItem("test_storage","synthetic-storage"); fetch("/api/check",{headers:{"Authorization":"synthetic-header"}});</script>';
async function intercept(sessionId) {
  if (installed.has(sessionId)) return;
  installed.add(sessionId);
  await originalSend('Network.enable', {}, sessionId);
  if (options.mode !== 'native') await originalSend('Network.setCookies', {cookies:[
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
  if (options.mode === 'form') {
    const {targetId} = await originalSend('Target.createTarget', {url:'about:blank'});
    const {sessionId} = await originalSend('Target.attachToTarget', {targetId, flatten:true});
    const send = (method, params) => originalSend(method, params, sessionId);
    const evaluate = expression => send('Runtime.evaluate', {expression, returnByValue:true});
    await send('Page.enable');
    await send('Page.navigate', {url:options.url});
    let ready = false;
    for (let attempt=0; attempt<50 && !ready; attempt++) {
      ready = (await evaluate("!!document.querySelector('[name=code]')")).result.value;
      if (!ready) await new Promise(r => setTimeout(r, 100));
    }
    assert.ok(ready, 'Private form loaded');
    await evaluate("document.querySelector('[name=code]').focus()");
    await send('Input.insertText', {text:options.code});
    await evaluate("document.querySelector('button').click()");
    let body;
    for (let attempt=0; attempt<50; attempt++) {
      body = (await evaluate('document.body.innerText')).result.value;
      if (body?.includes('Submitted')) break;
      await new Promise(r => setTimeout(r, 100));
    }
    console.log(JSON.stringify({body}));
  } else if (['cloud', 'native'].includes(options.mode)) {
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
    if (options.mode === 'native') {
      assert.ok((await owner.send('Target.getTargets')).targetInfos.some(t => t.targetId === untouched), 'Other tabs survive collection');
      const targetsBefore = (await owner.send('Target.getTargets')).targetInfos.map(t => t.targetId).sort();
      const abort = new AbortController();
      const missing = normalize({type:'cookies', url:'https://www.instagram.com/', fields:[{id:'not_present', type:'cookie'}]}, providers);
      const timer = setTimeout(() => abort.abort(), 1200);
      try { await assert.rejects(collectSession(browser, missing, {timeout:12, signal:abort.signal})); }
      finally { clearTimeout(timer); }
      assert.deepEqual((await owner.send('Target.getTargets')).targetInfos.map(t => t.targetId).sort(), targetsBefore, 'Cancellation removes only the new tab');
      await browser.close();
      assert.ok((await owner.send('Target.getTargets')).targetInfos.some(t => t.targetId === untouched), 'Imported browser stays open after disconnect');
      console.log('NATIVE_BROWSER_SMOKE_OK');
    }
  } else throw Error('Unknown test mode');
} finally {
  if (browser !== owner) await browser.close();
  await owner.close();
}
