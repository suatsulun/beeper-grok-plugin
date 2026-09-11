// Called only over a private pipe by browser_login.py.
import {normalize, validatePayload} from './browser_protocol.mjs';
import {keypair, unseal} from './browser_transfer.mjs';
import providers from './providers.mjs';
let input = '';
for await (const chunk of process.stdin) { input += chunk; if (input.length > 262144) process.exit(1); }
try {
  const data = JSON.parse(input);
  let result;
  if (data.action === 'probe') {
    result = {nodeVersion:process.versions.node, browserRuntimeReady:true,
      nativeBrowserTransportReady:typeof WebSocket === 'function'};
  } else if (data.action === 'plan') {
    result = normalize(data.step, providers);
  } else if (data.action === 'validate') {
    validatePayload(data.plan, data.payload, providers);
    result = {valid:true};
  } else if (data.action === 'transfer-keypair') {
    result = keypair();
  } else if (data.action === 'transfer-open') {
    result = unseal(data.request, data.privateKey, data.envelope);
  } else throw Error();
  process.stdout.write(JSON.stringify(result));
} catch { process.stderr.write('Browser login data was invalid or unsupported.'); process.exitCode = 1; }
