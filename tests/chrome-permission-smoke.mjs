// Exercise missing setup and denied connections without using a real profile.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir, writeFile, access} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {runDirectLocal} from '../skills/beeper/scripts/local_browser.mjs';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const options = JSON.parse(raw);
const unused = path.join(options.root, 'no-fallback');
const events = [];
let connected = false, returned = false;
await assert.rejects(runDirectLocal({...options.request, expires:Date.now() + 1000}, {
  binary:'/must-not-launch-chrome', dataDir:path.join(options.root, 'missing-profile'), root:unused, open:false,
  emit:event => events.push(event), onBrowser:() => { connected = true; }, onEnvelope:() => { returned = true; },
}), error => error.code === 'chrome_setup_required');
assert.ok(events.some(event => event.data.phase === 'chrome-setup'));
assert.equal(connected, false); assert.equal(returned, false);
await assert.rejects(access(unused));
const server = createServer();
server.on('upgrade', (_, socket) => socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'));
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
try {
  const config = path.join(options.root, 'synthetic-config'), dataDir = path.join(config, 'google-chrome');
  await mkdir(dataDir, {recursive:true});
  await writeFile(path.join(dataDir, 'DevToolsActivePort'), `${server.address().port}\n/devtools/browser/synthetic-denied\n`);
  const requestFile = path.join(options.root, 'permission-request.json');
  await writeFile(requestFile, JSON.stringify(options.request));
  // Actual CLI parent + worker: the default must connect to the ordinary
  // profile, preserve the specific failure and never spawn a separate Chrome.
  const child = spawn(process.execPath, [...process.execArgv, 'skills/beeper/scripts/local_browser.mjs', 'connect', requestFile, '--transfer-on-login'],
    {env:{...process.env, XDG_CONFIG_HOME:config, BEEPER_CHROME_BINARY:process.execPath}, stdio:['ignore','pipe','pipe']});
  let output = '', errorOutput = '';
  child.stdout.on('data', data => { output += data; });
  child.stderr.on('data', data => { errorOutput += data; });
  const timer = setTimeout(() => child.kill('SIGKILL'), 10000);
  let exit;
  try { exit = await new Promise(resolve => child.once('exit', resolve)); }
  finally { clearTimeout(timer); }
  assert.equal(exit, 1, output + errorOutput);
  const messages = output.trim().split('\n').map(line => JSON.parse(line));
  assert.ok(messages.some(message => message.data?.phase === 'chrome-permission'));
  assert.ok(messages.some(message => message.error?.code === 'chrome_connection_failed'));
  assert.ok(!messages.some(message => message.data?.state === 'encrypted-transfer-ready' || message.data?.profileMode === 'separate'));
  await assert.rejects(access(requestFile + '.encrypted.json'));
} finally { await new Promise(resolve => server.close(resolve)); }
process.stdout.write(JSON.stringify({passed:true}) + '\n');
