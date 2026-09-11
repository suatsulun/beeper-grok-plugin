// Synthetic provider/account only; each approval is a native Chromium form POST.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from '../skills/beeper/scripts/cloud_browser.mjs';
import {runLocal} from '../skills/beeper/scripts/local_browser.mjs';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const options = JSON.parse(raw);
const secret = 'synthetic-local-session';
const ownerProfile = path.join(options.root, 'existing-chrome');
const owner = await openBrowser({profile:ownerProfile, binary:options.binary, headless:true,
  extraArgs:['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1', '--host-resolver-rules=MAP *.instagram.com ~NOTFOUND']});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(fn, description) {
  for (let i=0; i<100; i++) { const value = await fn(); if (value) return value; await delay(100); }
  throw Error(description);
}
try {
  await waitFor(async () => { try { return await readFile(path.join(ownerProfile, 'DevToolsActivePort'), 'utf8'); } catch {} }, 'Fixture Chrome did not start');
  const originalTab = (await owner.send('Target.createTarget', {url:'about:blank'})).targetId;
  await owner.send('Storage.setCookies', {cookies:[
    {name:'sessionid', value:secret, domain:'.instagram.com', path:'/', secure:true, httpOnly:true},
    {name:'unrequested', value:'not-for-transfer', domain:'.instagram.com', path:'/', secure:true},
    {name:'sessionid', value:'wrong-provider', domain:'.facebook.com', path:'/', secure:true},
  ]});
  let delivered;
  for (const mode of ['existing', 'fresh', 'deny', 'cancel-ready']) {
    let consent, completed = false, outcome, browserOpened = false, activeSession = 'synthetic-stale-session';
    const task = runLocal(options.request, {binary:options.binary, root:path.join(options.root, 'local-helper'),
      dataDir:ownerProfile, open:false, headless:true, linger:0,
      extraArgs:['--host-resolver-rules=MAP *.instagram.com ~NOTFOUND'],
      onPage:page => { consent = page; },
      onBrowser:async browser => {
        browserOpened = true;
        const send = browser.send;
        browser.send = async (method, params, sessionId) => {
          const result = await send(method, params, sessionId);
          if (method === 'Network.enable') await send('Fetch.enable', {patterns:[{urlPattern:'https://*.instagram.com/*', requestStage:'Request'}]}, sessionId);
          return result;
        };
        browser.listeners.add(message => {
          if (message.method !== 'Fetch.requestPaused') return;
          // Simulates completing a provider-site login in the fresh profile.
          void send('Fetch.fulfillRequest', {requestId:message.params.requestId, responseCode:200,
            responseHeaders:[{name:'Content-Type', value:'text/html'},
              {name:'Set-Cookie', value:'sessionid=' + activeSession + '; Domain=.instagram.com; Path=/; Secure; HttpOnly'}],
            body:Buffer.from('<!doctype html><h1>Synthetic provider account</h1>').toString('base64')}, message.sessionId).catch(() => {});
        });
      }}).then(value => { outcome = value; completed = true; }, () => { completed = true; });
    await waitFor(() => consent, 'Local approval page missing');
    // Even a matching CSRF value cannot authorize from another origin.
    const pageHTML = await (await fetch(consent.url)).text();
    const csrf = pageHTML.match(/name="csrf" value="([a-f0-9]+)"/)[1];
    const forbidden = await fetch(consent.url, {method:'POST', redirect:'manual', headers:{Origin:'https://example.invalid', 'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({csrf, action:'open', mode:'existing'})});
    assert.equal(forbidden.status, 403);
    assert.equal(browserOpened, false);
    const {targetId} = await owner.send('Target.createTarget', {url:'about:blank'});
    const {sessionId} = await owner.send('Target.attachToTarget', {targetId, flatten:true});
    const send = (method, params) => owner.send(method, params, sessionId);
    const evaluate = async expression => (await send('Runtime.evaluate', {expression, returnByValue:true})).result.value;
    await send('Page.enable');
    await send('Page.navigate', {url:consent.url});
    await waitFor(() => evaluate("!!document.querySelector('button[value=open]')"), 'Initial approval form missing');
    if (mode === 'deny') {
      await evaluate("document.querySelector('button[value=cancel]').click()");
      await task;
      assert.equal(outcome, undefined);
      assert.equal(browserOpened, false);
    } else {
      const browserMode = mode === 'cancel-ready' ? 'existing' : mode;
      await evaluate(`document.querySelector('input[value=${browserMode}]').checked=true; document.querySelector('button[value=open]').click()`);
      await waitFor(() => evaluate("!!document.querySelector('button[value=transfer]')"), 'Transfer approval never appeared');
      assert.equal(completed, false, 'Ready session must wait for a new explicit approval');
      assert.equal(outcome, undefined);
      // The user may select another provider account while reviewing approval.
      // The returned session must reflect the post-approval page, not a snapshot.
      activeSession = secret;
      await evaluate(`document.querySelector('button[value=${mode === 'cancel-ready' ? 'cancel' : 'transfer'}]').click()`);
      await task;
      if (mode === 'cancel-ready') assert.equal(outcome, undefined, 'Ready credentials cannot transfer after denial');
      else {
        assert.ok(outcome?.ciphertext, 'Approved transfer emits encrypted data');
        assert.ok(!JSON.stringify(outcome).includes(secret));
        delivered = outcome;
      }
    }
    await owner.send('Target.closeTarget', {targetId});
    assert.ok((await owner.send('Target.getTargets')).targetInfos.some(t => t.targetId === originalTab), 'Existing browser and unrelated tab survive');
  }
  process.stdout.write(JSON.stringify({existingApproved:true, freshApproved:true, deniedWithoutTransfer:true, envelope:delivered}));
} finally { await owner.close(); }
