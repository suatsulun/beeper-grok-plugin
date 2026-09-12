// Run on the user's PC through Grok's approved local execution. No installs.
import {createServer} from 'node:http';
import {randomBytes, timingSafeEqual} from 'node:crypto';
import {readFile, mkdir, access, writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {openBrowser, connectBrowserWebSocket, collectSession} from './cloud_browser.mjs';
import {seal, validateRequest} from './browser_transfer.mjs';
import providers from './providers.mjs';

const html = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const equal = (a, b) => typeof a === 'string' && /^[a-f0-9]{64}$/.test(a) && timingSafeEqual(Buffer.from(a), Buffer.from(b));
export function chromeDataDir(platform = process.platform, env = process.env, home = os.homedir()) {
  if (platform === 'darwin') return path.join(home, 'Library/Application Support/Google/Chrome');
  if (platform === 'win32' && env.LOCALAPPDATA) return path.join(env.LOCALAPPDATA, 'Google/Chrome/User Data');
  if (platform === 'linux') return path.join(env.XDG_CONFIG_HOME || path.join(home, '.config'), 'google-chrome');
  throw Error('This platform needs an explicitly selected Chrome data directory.');
}
export async function findChrome() {
  const candidates = [process.env.BEEPER_CHROME_BINARY,
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ...[process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA]
      .filter(Boolean).map(root => path.join(root, 'Google/Chrome/Application/chrome.exe'))].filter(Boolean);
  for (const candidate of candidates) { try { await access(candidate); return candidate; } catch {} }
  throw Error('Existing Chrome was not found. No browser will be installed.');
}
function launch(binary, args) {
  // Never use a shell to open a URL or run a browser.
  const child = spawn(binary, args, {detached:true, stdio:'ignore'});
  child.on('error', () => {}); child.unref();
}
export async function chromeEndpoint(dataDir) {
  // This file describes Chrome's user-enabled connection; it has no cookies.
  const text = await readFile(path.join(dataDir, 'DevToolsActivePort'), 'utf8');
  if (text.length > 1024) throw Error('Invalid Chrome connection metadata.');
  const [port, endpoint] = text.trim().split(/\r?\n/);
  if (!/^\d{1,5}$/.test(port) || Number(port) < 1 || Number(port) > 65535 ||
      !/^\/devtools\/browser\/[\w-]+$/.test(endpoint)) throw Error('Invalid Chrome connection metadata.');
  return `ws://127.0.0.1:${port}${endpoint}`;
}

export async function approvalPage(request, {onState = () => {}} = {}) {
  validateRequest(request);
  const csrf = randomBytes(32).toString('hex'), route = '/connect/' + randomBytes(24).toString('hex');
  const abort = new AbortController();
  let state = 'choose', message = '', progress = {}, selectedMode, resolveStart, resolveTransfer;
  const started = new Promise(resolve => { resolveStart = resolve; });
  const approved = new Promise(resolve => { resolveTransfer = resolve; });
  const provider = providers.find(p => p.id === request.plan.provider);
  const optionalFields = request.plan.fields.filter(field => !field.required).map(field => field.id);
  const update = (next, text = '', details = {}) => { state = next; message = text; progress = details; onState(next, details); };
  const stop = reason => { update(reason); abort.abort(); resolveStart(null); resolveTransfer(false); };
  const server = createServer(async (req, res) => {
    const origin = `http://127.0.0.1:${server.address().port}`;
    const respond = (status, body, headers = {}) => {
      res.writeHead(status, {'Content-Type':'text/html; charset=utf-8', 'Cache-Control':'no-store',
        'Referrer-Policy':'same-origin', 'X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'", ...headers});
      res.end(body);
    };
    if (req.headers.host !== new URL(origin).host) return respond(403, 'Invalid request.');
    if (Date.now() >= request.expires && !['done','denied','expired','failed'].includes(state)) stop('expired');
    if (req.method === 'GET' && req.url === route) {
      const form = content => `<form method="post" action="${route}"><input type="hidden" name="csrf" value="${csrf}">${content}</form>`;
      let content;
      if (state === 'choose') content = `<h1>Connect ${html(provider.name)}</h1><p>Sign in on this PC, then approve sending the required session to Beeper Server on Grok.</p>` +
        form('<label><input type="radio" name="mode" value="existing" checked> Use my open Chrome profile</label><p class="hint">Chrome chooses the shared profile. Check the account on the provider website before approving the transfer. Chrome 144+ and its built-in connection approval are required.</p><label><input type="radio" name="mode" value="fresh"> Open a separate login window on this PC</label><p class="hint">Use your PC clipboard to sign in. This window does not automatically inherit your normal Chrome profile or extensions.</p><button name="action" value="open">Open provider website</button>') +
        '<p class="hint">Chrome grants a browser debugging connection. This helper only reads the selected provider’s requested fields in its own tab. Nothing is transferred until you approve below.</p>';
      else if (state === 'ready') content = `<h1>Approve this transfer</h1><p>Check the account in the ${html(provider.name)} tab on this PC. Connect that account to Beeper Server on Grok?</p>` +
        '<p>The requested sign-in session is sent encrypted. Passwords and session values are not displayed in chat. Approval applies to this transfer only.</p>' +
        form('<button name="action" value="transfer">Approve this transfer</button>');
      else if (state === 'sending') content = '<h1>Preparing your approved session</h1><p>Keep the provider tab open while the helper refreshes and encrypts this session. No further click is needed.</p>';
      else if (state === 'opening') content = '<h1>Opening the provider website</h1><p>Sign in there if needed, then return to this Beeper tab to approve the connection.</p>';
      else if (state === 'done') content = '<h1>Session prepared</h1><p>The encrypted session is ready for Grok to deliver to Beeper Server. Return to Grok to check whether the network connected.</p>';
      else if (state === 'denied') content = '<h1>Cancelled</h1><p>No session will be transferred.</p>';
      else if (state === 'expired') content = '<h1>This request expired</h1><p>Keep your provider account signed in. Return to Grok for a new request and approval; signing in again is usually unnecessary.</p>';
      else if (state === 'failed') content = '<h1>Connection did not finish</h1><p>No session was transferred. Return to Grok to inspect the pending connection.</p>';
      else content = `<h1>${state === 'permission' ? 'Allow the Chrome connection' : 'Finish signing in'}</h1><p>${html(message || 'Use the provider website on this PC. This page will ask for your approval when the session is ready.')}</p>`;
      if (optionalFields.length) content += `<p class="hint">Missing optional fields will not block your transfer approval.</p><details class="hint"><summary>Optional connection details</summary>Optional session fields: ${html(optionalFields.join(', '))}. Some signed-in sessions do not have these.</details>`;
      if (state === 'collecting' && progress.missingRequiredFields?.length) content += `<details class="hint"><summary>What is the helper waiting for?</summary>Required session fields: ${html(progress.missingRequiredFields.join(', '))}. Optional fields are not included here.</details>`;
      if (state === 'collecting' && progress.waitingForFinalPage) content += '<p class="hint">The provider has not yet reached the page required by its login flow. Complete any sign-in or verification on the provider tab.</p>';
      if (!['done','denied','expired','failed'].includes(state)) content += form('<button class="secondary" name="action" value="cancel">Cancel</button>');
      const refresh = ['opening','permission','collecting','sending'].includes(state) ? '<meta http-equiv="refresh" content="2">' : '';
      return respond(200, `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${refresh}<title>Beeper — ${html(provider.name)}</title><style>body{font:17px system-ui;color:#152237;background:#f4f6fa;margin:0;padding:44px 20px}main{max-width:580px;margin:auto;padding:32px;background:white;border:1px solid #dde4ed;border-radius:18px}h1{font-size:28px}p{line-height:1.55}label{display:block;margin:18px 0 4px}button{border:0;border-radius:9px;padding:13px 20px;background:#1769e0;color:white;font:inherit;cursor:pointer}.secondary{margin-top:14px;background:#eaf0f8;color:#152237}.hint{color:#536275;font-size:14px}.brand{font-weight:700;color:#1769e0}</style><main><div class="brand">Beeper</div>${content}<p class="hint">Provider: ${html(new URL(request.plan.url).hostname)}</p></main></html>`);
    }
    if (req.method !== 'POST' || req.url !== route) return respond(404, 'Not found.');
    if (req.headers.origin !== origin || req.headers['content-type']?.split(';')[0] !== 'application/x-www-form-urlencoded') return respond(403, 'Submit from this approval page.');
    let body = '';
    try { for await (const chunk of req) { body += chunk; if (body.length > 4096) return respond(413, 'Request too large.'); } }
    catch { return respond(400, 'Invalid request.'); }
    const values = new URLSearchParams(body);
    if (!equal(values.get('csrf'), csrf)) return respond(403, 'Invalid approval.');
    const action = values.get('action');
    if (action === 'cancel' && !['done','denied','expired','failed','sending'].includes(state)) stop('denied');
    else if (action === 'open' && state === 'choose' && ['existing','fresh'].includes(values.get('mode'))) {
      selectedMode = values.get('mode'); update('opening'); resolveStart(selectedMode);
    } else if (action === 'transfer' && state === 'ready') { update('sending'); resolveTransfer(true); }
    else return respond(409, 'This action is no longer available.');
    respond(303, '', {Location:route});
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  server.on('clientError', (_, socket) => socket.destroy());
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const expiry = setTimeout(() => stop('expired'), Math.max(1, request.expires - Date.now()));
  return {url:`http://127.0.0.1:${server.address().port}${route}`, started, signal:abort.signal,
    update, cancel:() => stop('denied'),
    async approveTransfer() { update('ready'); if (!await approved || abort.signal.aborted) throw Error('Transfer not approved.'); },
    close() { clearTimeout(expiry); server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); }};
}

export async function runLocal(request, options = {}) {
  validateRequest(request);
  const binary = options.binary || await findChrome();
  const consent = await approvalPage(request, {onState:(state, details) => {
    options.onState?.(state, details);
    options.emit?.({success:true, data:{state:'local-browser-progress', phase:state, ...details,
      ...(state === 'ready' ? {instruction:'The session is ready. Ask the user to return to the Beeper tab and click Approve this transfer. Do not click it yourself.'} : {})}});
  }});
  let browser;
  const stop = () => consent.cancel();
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  try {
    options.onPage?.(consent);
    if (options.open !== false) launch(binary, [consent.url]);
    options.emit?.({success:true, data:{state:'local-approval-required', approvalURL:consent.url}});
    const mode = await consent.started;
    if (!mode || consent.signal.aborted) throw Error('Cancelled.');
    if (mode === 'existing') {
      const directory = options.dataDir || chromeDataDir();
      let endpoint;
      try { endpoint = await chromeEndpoint(directory); } catch {}
      if (!endpoint) {
        consent.update('permission', 'In Chrome 144+, open chrome://inspect/#remote-debugging and enable its connection setting yourself. Then approve Chrome’s connection prompt. No extension is needed.');
        if (options.open !== false) launch(binary, ['chrome://inspect/#remote-debugging']);
        while (!endpoint && !consent.signal.aborted) {
          await sleep(500);
          try { endpoint = await chromeEndpoint(directory); } catch {}
        }
      }
      if (consent.signal.aborted) throw Error('Cancelled.');
      consent.update('permission', 'Approve the connection prompt in your Chrome browser. You will approve the session transfer separately after checking the provider account.');
      browser = await connectBrowserWebSocket(endpoint, {connectTimeout:Math.min(120000, request.expires - Date.now()), signal:consent.signal});
    } else {
      const root = options.root || path.join(os.homedir(), '.beeper-browser');
      await mkdir(root, {recursive:true, mode:0o700});
      browser = await openBrowser({profile:path.join(root, 'profiles', request.plan.provider), binary,
        headless:options.headless || false, extraArgs:options.extraArgs || []});
    }
    if (consent.signal.aborted) throw Error('Cancelled.');
    await options.onBrowser?.(browser, mode);
    consent.update('collecting');
    const payload = await collectSession(browser, request.plan, {signal:consent.signal,
      timeout:Math.max(1, Math.floor((request.expires - Date.now()) / 1000)),
      onProgress:status => consent.update('collecting', '', status),
      onReady:() => consent.approveTransfer()});
    if (consent.signal.aborted) throw Error('Cancelled.');
    const envelope = seal(request, payload);
    payload.fields = {}; payload.lastURL = '';
    consent.update('done');
    return envelope;
  } catch {
    if (!consent.signal.aborted) consent.update('failed');
    throw Error('Local browser login did not complete. No session was transferred. Check Chrome permissions and request expiry.');
  } finally {
    if (browser) await browser.close();
    process.removeListener('SIGTERM', stop); process.removeListener('SIGINT', stop);
    // Let the approval tab refresh to its final message before closing HTTP.
    await sleep(options.linger ?? 2500);
    await consent.close();
  }
}

async function main() {
  const [command, requestPath] = process.argv.slice(2);
  if (command === 'check') {
    let chromeAvailable = false;
    try { await findChrome(); chromeAvailable = true; } catch {}
    process.stdout.write(JSON.stringify({success:true, data:{platform:process.platform, nodeVersion:process.versions.node,
      browserAvailable:chromeAvailable, websocketAvailable:typeof WebSocket === 'function', downloadsPerformed:false}}) + '\n');
    return;
  }
  if (command !== 'connect' || !requestPath) throw Error('Use check or connect REQUEST.json.');
  const text = await readFile(requestPath, 'utf8');
  if (text.length > 32768) throw Error('Invalid request.');
  const request = JSON.parse(text);
  const envelope = await runLocal(request, {emit:value => process.stdout.write(JSON.stringify(value) + '\n')});
  const output = path.resolve(requestPath) + '.encrypted.json';
  await writeFile(output, JSON.stringify(envelope), {mode:0o600, flag:'wx'});
  process.stdout.write(JSON.stringify({success:true, data:{state:'encrypted-transfer-ready', encryptedFile:output, envelope}}) + '\n');
}
if (process.argv[1] === fileURLToPath(import.meta.url)) main().catch(() => {
  process.stderr.write('Local browser connection did not finish. Check local execution, browser approval, and request expiry. No credentials were printed.\n');
  process.exitCode = 1;
});
