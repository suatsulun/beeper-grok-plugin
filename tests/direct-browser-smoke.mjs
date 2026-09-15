// A synthetic Instagram site in disposable owned Chrome profiles only.
import assert from 'node:assert/strict';
import path from 'node:path';
import {runDirectLocal} from '../skills/beeper/scripts/local_browser.mjs';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const options = JSON.parse(raw);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(fn, message) {
  for (let i = 0; i < 100; i++) { try { const value = await fn(); if (value) return value; } catch {} await delay(50); }
  throw Error(message);
}
let delivered;
for (const mode of ['success','cancel','closed','expiry','pre-cancel']) {
  const signal = new AbortController(), events = [], navigations = [];
  let browser, envelope, finished = false, completion = false, failure;
  if (mode === 'pre-cancel') signal.abort();
  const request = {...options.request, ...(mode === 'expiry' ? {expires:Date.now() + 4000} : {})};
  const task = runDirectLocal(request, {
    binary:options.binary, root:path.join(options.root, 'direct-' + mode), headless:true,
    extraArgs:['--host-resolver-rules=MAP *.instagram.com ~NOTFOUND'], signal:signal.signal,
    completionLinger:30000, emit:event => events.push(event),
    onEnvelope:value => { envelope = value; },
    onCompletion:() => { completion = true; },
    onBrowser:async connection => {
      browser = connection;
      const send = browser.send;
      browser.send = async (method, params, sessionId) => {
        if (method === 'Page.navigate') navigations.push(params.url);
        assert.notEqual(method, 'Target.createTarget', 'Direct login reuses its only owned window');
        const result = await send(method, params, sessionId);
        if (method === 'Network.enable') await send('Fetch.enable', {patterns:[{urlPattern:'https://*.instagram.com/*'}]}, sessionId);
        return result;
      };
      browser.listeners.add(message => {
        if (message.method !== 'Fetch.requestPaused') return;
        const ready = new URL(message.params.request.url).pathname === '/home/';
        const responseHeaders = [{name:'Content-Type', value:'text/html'}];
        if (ready) for (const [name, value] of Object.entries({sessionid:'synthetic-local-session',csrftoken:'synthetic-csrf',ds_user_id:'123'})) {
          responseHeaders.push({name:'Set-Cookie', value:`${name}=${value}; Domain=.instagram.com; Path=/; Secure`});
        }
        const content = ready ? '<h1>Synthetic home</h1>' : '<h1>Synthetic provider login</h1><button id="signin" onclick="location.href=\'/home/\'">Sign in</button>';
        void send('Fetch.fulfillRequest', {requestId:message.params.requestId, responseCode:200,
          responseHeaders, body:Buffer.from(content).toString('base64')}, message.sessionId).catch(() => {});
      });
    },
  }).then(value => { finished = true; return value; }, error => { finished = true; failure = error; });
  if (mode === 'pre-cancel') {
    await task;
    assert.ok(failure); assert.equal(browser, undefined); assert.equal(envelope, undefined);
    continue;
  }
  try {
    await waitFor(() => browser, 'Owned browser did not open');
    const targetId = await waitFor(async () => (await browser.send('Target.getTargets')).targetInfos.find(t => t.type === 'page')?.targetId, 'Provider tab missing');
    const {sessionId} = await browser.send('Target.attachToTarget', {targetId, flatten:true});
    const evaluate = async expression => (await browser.send('Runtime.evaluate', {expression, returnByValue:true}, sessionId)).result.value;
    await waitFor(() => evaluate("document.getElementById('signin') !== null"), 'First page must be provider login');
    assert.equal(navigations[0], request.plan.url);
    assert.equal(envelope, undefined, 'No session before provider login');
    assert.ok(!events.some(e => e.data.approvalURL || e.data.phase === 'ready' || e.data.phase === 'permission'));
    if (mode === 'success') {
      await evaluate("document.getElementById('signin').click()");
      await waitFor(() => envelope && completion, 'Login did not trigger automatic transfer and completion');
      await waitFor(() => evaluate("document.querySelector('h1')?.textContent === 'You can close this window now'"), 'Completion screen missing');
      assert.equal(finished, false, 'Encrypted result is available while completion window remains open');
      assert.ok(navigations.at(-1).startsWith('data:text/html'));
      assert.equal((await browser.send('Target.getTargets')).targetInfos.filter(t => t.type === 'page').length, 1);
      assert.ok(!JSON.stringify(events).includes('synthetic-local-session'));
      delivered = envelope;
      await browser.close();
      assert.equal(await task, envelope);
    } else {
      if (mode === 'cancel') signal.abort();
      if (mode === 'closed') await browser.close();
      await task;
      assert.ok(failure, mode + ' must cancel');
      assert.equal(envelope, undefined, 'Cancelled or expired login cannot transfer');
      assert.equal(completion, false);
    }
    assert.ok(!navigations.some(url => url.startsWith('chrome:') || url.includes('127.0.0.1')));
  } finally { signal.abort(); await task; }
}
process.stdout.write(JSON.stringify({passed:true, envelope:delivered}) + '\n');
