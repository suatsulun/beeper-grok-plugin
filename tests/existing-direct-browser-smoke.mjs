// Real Chromium transport with a disposable existing profile and synthetic site.
// Does not touch the user's Chrome or automate its real permission dialog.
import assert from 'node:assert/strict';
import {readFile, access} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from '../skills/beeper/scripts/cloud_browser.mjs';
import {runDirectLocal} from '../skills/beeper/scripts/local_browser.mjs';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const options = JSON.parse(raw);
const profile = path.join(options.root, 'ordinary-fixture');
const unusedRoot = path.join(options.root, 'must-not-create-separate-profile');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(fn, message) {
  for (let i = 0; i < 120; i++) { try { const result = await fn(); if (result) return result; } catch {} await delay(50); }
  throw Error(message);
}
const owner = await openBrowser({profile, binary:options.binary, headless:true,
  extraArgs:['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1', '--host-resolver-rules=MAP *.instagram.com ~NOTFOUND']});
let delivered;
try {
  await waitFor(async () => readFile(path.join(profile, 'DevToolsActivePort'), 'utf8'), 'Fixture endpoint missing');
  const originalTabs = (await owner.send('Target.getTargets')).targetInfos.filter(t => t.type === 'page').map(t => t.targetId);
  const originalWindow = (await owner.send('Browser.getWindowForTarget', {targetId:originalTabs[0]})).windowId;
  await owner.send('Storage.setCookies', {cookies:[{name:'unrelated', value:'synthetic-unrelated', domain:'.example.com', path:'/'}]});
  for (const mode of ['saved-session','login','cancel','close','expiry','disconnect']) {
    const signal = new AbortController(), events = [], navigations = [];
    let browser, createdTarget, envelope, completion = false, finished = false, failure;
    await owner.send('Storage.clearCookies');
    await owner.send('Storage.setCookies', {cookies:[
      {name:'unrelated', value:'synthetic-unrelated', domain:'.example.com', path:'/'},
      ...(mode === 'saved-session' ? [{name:'sessionid', value:'synthetic-local-session', domain:'.instagram.com', path:'/', secure:true, httpOnly:true}] : []),
    ]});
    const request = {...options.request, ...(mode === 'expiry' ? {expires:Date.now() + 3500} : {})};
    // Omit profileMode to exercise the default. No separate browser is launched.
    const task = runDirectLocal(request, {binary:options.binary, dataDir:profile, root:unusedRoot, open:false,
      signal:signal.signal, completionLinger:30000, emit:event => events.push(event),
      onEnvelope:value => { envelope = value; }, onCompletion:() => { completion = true; },
      onBrowser:async connection => {
        browser = connection;
        const send = browser.send;
        browser.send = async (method, params, sessionId) => {
          assert.notEqual(method, 'Browser.close', 'Never close the shared browser');
          assert.notEqual(method, 'Target.createBrowserContext', 'Never create an empty/incognito context');
          if (method === 'Target.closeTarget') assert.equal(params.targetId, createdTarget, 'Never close unrelated tabs');
          if (method === 'Page.navigate') navigations.push(params.url);
          const result = await send(method, params, sessionId);
          if (method === 'Target.createTarget') {
            assert.equal(params.newWindow, true);
            assert.equal(params.browserContextId, undefined, 'Use the shared ordinary context');
            createdTarget = result.targetId;
          }
          if (method === 'Network.enable') await send('Fetch.enable', {patterns:[{urlPattern:'https://*.instagram.com/*'}]}, sessionId);
          return result;
        };
        browser.listeners.add(message => {
          if (message.method !== 'Fetch.requestPaused') return;
          const headers = [{name:'Content-Type', value:'text/html'}];
          if (new URL(message.params.request.url).pathname === '/home/') headers.push({name:'Set-Cookie', value:'sessionid=synthetic-local-session; Domain=.instagram.com; Path=/; Secure; HttpOnly'});
          void send('Fetch.fulfillRequest', {requestId:message.params.requestId, responseCode:200, responseHeaders:headers,
            body:Buffer.from('<!doctype html><h1>Synthetic login</h1><button id="signin" onclick="location.href=\'/home/\'">Sign in</button>').toString('base64')}, message.sessionId).catch(() => {});
        });
      },
    }).then(value => { finished = true; return value; }, error => { failure = error; finished = true; });
    try {
      await waitFor(() => createdTarget, 'Provider window was not created');
      assert.notEqual((await owner.send('Browser.getWindowForTarget', {targetId:createdTarget})).windowId, originalWindow);
      const {sessionId} = await owner.send('Target.attachToTarget', {targetId:createdTarget, flatten:true});
      const evaluate = async expression => (await owner.send('Runtime.evaluate', {expression, returnByValue:true}, sessionId)).result.value;
      if (mode !== 'saved-session') {
        await waitFor(() => evaluate("!!document.getElementById('signin')"), 'Provider login did not open directly');
        assert.equal(envelope, undefined);
        if (mode === 'login') await evaluate("document.getElementById('signin').click()");
        if (mode === 'cancel') signal.abort();
        if (mode === 'close') await owner.send('Target.closeTarget', {targetId:createdTarget});
        if (mode === 'disconnect') await browser.close();
      }
      if (['saved-session','login'].includes(mode)) {
        await waitFor(() => envelope && completion, 'Automatic encrypted handoff missing');
        await waitFor(() => evaluate("document.querySelector('h1')?.textContent === 'You can close this window now'"), 'Completion screen missing');
        assert.equal(finished, false, 'Ciphertext must arrive before completion window closes');
        assert.equal(navigations[0], request.plan.url);
        delivered = envelope;
        await owner.send('Target.closeTarget', {targetId:createdTarget});
        assert.equal(await task, envelope);
        assert.ok(!failure);
      } else {
        await task;
        assert.ok(failure, mode + ' must stop collection');
        assert.equal(envelope, undefined);
        assert.equal(completion, false);
      }
      const pages = (await owner.send('Target.getTargets')).targetInfos.filter(t => t.type === 'page').map(t => t.targetId);
      for (const tab of originalTabs) assert.ok(pages.includes(tab), 'Original tabs must survive');
      if (mode !== 'disconnect') assert.ok(!pages.includes(createdTarget), 'Helper window must be cleaned up');
      else await owner.send('Target.closeTarget', {targetId:createdTarget}); // Lost permission cannot authorize reconnecting just to clean up.
      const cookies = (await owner.send('Storage.getCookies')).cookies;
      assert.ok(cookies.some(cookie => cookie.name === 'unrelated' && cookie.value === 'synthetic-unrelated'));
      assert.ok(!events.some(event => event.data.approvalURL || event.data.phase === 'ready' || event.data.phase === 'chrome-setup'));
      assert.ok(events.some(event => event.data.profileMode === 'existing'));
      assert.ok(!JSON.stringify(events).includes('synthetic-local-session'));
      assert.ok(!navigations.some(url => url.startsWith('chrome:') || url.includes('127.0.0.1')));
    } finally { signal.abort(); await task; }
  }
  await assert.rejects(access(unusedRoot), 'Normal-profile login must never create a fallback profile');
} finally { await owner.close(); }
process.stdout.write(JSON.stringify({passed:true, envelope:delivered}) + '\n');
