// Real process/IPC lifecycle fixture; no browser, account, or network access.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {relayWorker} from '../skills/beeper/scripts/local_browser.mjs';
const [mode, root, role] = process.argv.slice(2);
const file = fileURLToPath(import.meta.url);
const pidFile = path.join(root, 'worker-' + mode + '.pid');
const doneFile = path.join(root, 'worker-' + mode + '.done');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
if (role === 'child') {
  await writeFile(pidFile, String(process.pid));
  process.on('exit', () => writeFileSync(doneFile, 'closed'));
  process.on('SIGTERM', () => process.exit(0));
  process.send({success:true, data:{phase:'opened'}});
  if (mode === 'exit') setTimeout(() => process.exit(2), 50);
  else if (mode === 'complete') setTimeout(() => process.send({success:true, data:{state:'encrypted-transfer-ready', envelope:{fixture:true}}}), 50);
  setTimeout(() => process.exit(0), 10000);
} else if (role === 'relay') {
  const child = spawn(process.execPath, [...process.execArgv, file, mode, root, 'child'],
    {detached:true, stdio:['ignore','ignore','ignore','ipc']});
  try {
    await relayWorker(child, event => {
      process.stdout.write(JSON.stringify(event) + '\n');
      if (mode === 'cancel' && event.data?.phase === 'opened') process.kill(process.pid, 'SIGTERM');
    });
  } catch { process.exitCode = 1; }
} else {
  const parent = spawn(process.execPath, [...process.execArgv, file, mode, root, 'relay'], {stdio:['ignore','pipe','pipe']});
  let stdout = '', stderr = '', pid;
  parent.stdout.on('data', value => { stdout += value; });
  parent.stderr.on('data', value => { stderr += value; });
  const timer = setTimeout(() => parent.kill('SIGKILL'), 5000);
  try {
    const code = await new Promise(resolve => parent.once('exit', resolve));
    pid = Number(await readFile(pidFile, 'utf8'));
    if (mode === 'complete') {
      assert.equal(code, 0, stderr);
      assert.ok(stdout.includes('encrypted-transfer-ready'));
      process.kill(pid, 0); // Worker outlives the completed result command.
      await assert.rejects(readFile(doneFile), {code:'ENOENT'});
      process.kill(pid, 'SIGTERM');
    } else {
      assert.equal(code, 1, stderr);
      assert.ok(!stdout.includes('encrypted-transfer-ready'));
    }
    let closed = false;
    for (let i = 0; i < 30 && !closed; i++) {
      try { closed = (await readFile(doneFile, 'utf8')) === 'closed'; } catch { await delay(50); }
    }
    assert.ok(closed, 'Worker cleans up after cancellation/exit or completion window closure');
    process.stdout.write(JSON.stringify({passed:true, mode}) + '\n');
  } finally {
    clearTimeout(timer);
    if (pid) { try { process.kill(pid, 'SIGTERM'); } catch {} }
  }
}
