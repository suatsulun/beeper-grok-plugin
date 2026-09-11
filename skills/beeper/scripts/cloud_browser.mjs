// A dedicated browser profile; Chrome debugging uses private pipes, never a port.
import {spawn} from 'node:child_process';
import {mkdir, access} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {validatePlan, providerURL, safeRegex, selectFields, complete} from '../../../browser-extension/protocol.mjs';
import providers from '../../../browser-extension/providers.mjs';

export async function openBrowser({profile, binary, headless = false, extension, extraArgs = []}) {
  if (!binary) {
    for (const candidate of [process.env.BEEPER_CHROME_BINARY, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser'].filter(Boolean)) {
      try { await access(candidate); binary = candidate; break; } catch {}
    }
  }
  if (!binary) throw Error('Chrome is unavailable.');
  await mkdir(profile, {recursive:true, mode:0o700});
  const child = spawn(binary, ['--user-data-dir=' + profile, '--remote-debugging-pipe', '--no-first-run', '--no-default-browser-check', ...(headless ? ['--headless=new'] : []), ...(extension ? ['--load-extension=' + extension] : []), ...extraArgs, 'about:blank'], {stdio:['ignore','ignore','ignore','pipe','pipe']});
  let sequence = 0, buffer = '';
  const pending = new Map(), listeners = new Set();
  child.on('error', () => { for (const call of pending.values()) call.reject(Error('Chrome failed.')); });
  child.on('exit', () => { for (const call of pending.values()) { clearTimeout(call.timer); call.reject(Error('Chrome closed.')); } pending.clear(); });
  child.stdio[4].on('data', bytes => {
    buffer += bytes.toString();
    while (buffer.includes('\0')) {
      const end = buffer.indexOf('\0');
      const raw = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      let message;
      try { message = JSON.parse(raw); } catch { continue; }
      if (message.id && pending.has(message.id)) {
        const call = pending.get(message.id); pending.delete(message.id); clearTimeout(call.timer);
        message.error ? call.reject(Error('Browser operation failed.')) : call.resolve(message.result);
      } else for (const listener of listeners) listener(message);
    }
  });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(Error('Browser timed out.')); }, 10000);
    pending.set(id, {resolve, reject, timer});
    child.stdio[3].write(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}) + '\0', error => {
      if (error) { clearTimeout(timer); pending.delete(id); reject(Error('Browser closed.')); }
    });
  });
  const close = async () => {
    for (const call of pending.values()) { clearTimeout(call.timer); call.reject(Error('Browser closed.')); }
    pending.clear();
    child.kill('SIGTERM');
    if (child.exitCode === null) await Promise.race([new Promise(resolve => child.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 3000))]);
    if (child.exitCode === null) child.kill('SIGKILL');
  };
  return {send, listeners, close};
}

export async function collectSession(browser, plan, {timeout = 600, providers:registry = providers, navigateURL} = {}) {
  const provider = validatePlan(plan, registry);
  const {targetId} = await browser.send('Target.createTarget', {url:'about:blank'});
  const {sessionId} = await browser.send('Target.attachToTarget', {targetId, flatten:true});
  const send = (method, params) => browser.send(method, params, sessionId);
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  const headers = Object.create(null), requests = new Map();
  function observe(message) {
    if (message.sessionId !== sessionId) return;
    const p = message.params;
    if (message.method === 'Network.requestWillBeSent') {
      if (requests.size > 512) requests.clear();
      requests.set(p.requestId, p.request.url);
      capture(p.request.url, p.request.headers);
    }
    if (message.method === 'Network.requestWillBeSentExtraInfo') capture(requests.get(p.requestId), p.headers);
  }
  function capture(url, values) {
    try { providerURL(url, provider); } catch { return; }
    for (const field of plan.fields) for (const source of field.sources) {
      if (source.type !== 'request_header' || (source.requestURLRegex && !safeRegex(source.requestURLRegex).test(url))) continue;
      const value = Object.entries(values).find(([k]) => k.toLowerCase() === source.name.toLowerCase())?.[1];
      if (typeof value === 'string' && value.length <= 16384) headers[field.id] = value;
    }
  }
  browser.listeners.add(observe);
  try {
    await send('Page.navigate', {url:navigateURL || plan.url});
    const deadline = Date.now() + timeout * 1000;
    while (Date.now() < deadline) {
      const page = await send('Runtime.evaluate', {expression:'location.href', returnByValue:true});
      const lastURL = page.result.value;
      let allowed = false;
      try { providerURL(lastURL, provider); allowed = true; } catch {}
      if (allowed) {
        const urls = [...new Set([lastURL, ...plan.fields.flatMap(f => f.sources.filter(s => s.type === 'cookie').map(s => 'https://' + s.domain + '/'))])];
        const {cookies} = await send('Network.getCookies', {urls});
        const names = [...new Set(plan.fields.flatMap(f => f.sources.filter(s => s.type === 'local_storage').map(s => s.name)))];
        const {result} = await send('Runtime.evaluate', {expression:`Object.fromEntries(${JSON.stringify(names)}.map(key => [key, localStorage.getItem(key)]))`, returnByValue:true});
        const fields = selectFields(plan, cookies, result.value || {}, headers);
        if (complete(plan, fields, lastURL, registry)) return {fields, lastURL};
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw Error('Provider sign-in timed out.');
  } finally { browser.listeners.delete(observe); }
}

async function main() {
  let input = '';
  for await (const chunk of process.stdin) { input += chunk; if (input.length > 65536) throw Error(); }
  const options = JSON.parse(input);
  validatePlan(options.plan, providers);
  const browser = await openBrowser({profile:path.join(options.root, 'browser-profiles', options.plan.provider)});
  const stop = () => { void browser.close().finally(() => process.exit(1)); };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  try {
    const payload = await collectSession(browser, options.plan, {timeout:Math.min(options.timeout || 600, 600)});
    // Only the Python parent reads this private pipe.
    process.stdout.write(JSON.stringify(payload));
  } finally { await browser.close(); }
}
if (process.argv[1] === fileURLToPath(import.meta.url)) main().catch(() => { process.stderr.write('Provider browser could not complete sign-in.'); process.exitCode = 1; });
