// Called only over a private pipe by browser_login.py.
import {normalize, complete, validatePlan} from './browser_protocol.mjs';
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
    validatePlan(data.plan, providers);
    const {fields, lastURL} = data.payload;
    const ids = new Set(data.plan.fields.map(field => field.id));
    if (!complete(data.plan, fields, lastURL, providers) ||
        Object.entries(fields).some(([k,v]) => !ids.has(k) || typeof v !== 'string' || v.length > 16384)) throw Error();
    result = {valid:true};
  } else throw Error();
  process.stdout.write(JSON.stringify(result));
} catch { process.stderr.write('Browser login data was invalid or unsupported.'); process.exitCode = 1; }
