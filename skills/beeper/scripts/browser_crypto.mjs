// Private pipe only: the Python parent captures this output; never invoke with secrets in argv.
import {normalize, keypair, decrypt, complete, validatePlan} from '../../../browser-extension/protocol.mjs';
import providers from '../../../browser-extension/providers.mjs';
let input = '';
for await (const chunk of process.stdin) { input += chunk; if (input.length > 262144) process.exit(1); }
try {
  const data = JSON.parse(input);
  let result;
  if (data.action === 'plan') result = normalize(data.step, providers);
  else if (data.action === 'keypair') result = await keypair();
  else if (data.action === 'decrypt') {
    validatePlan(data.descriptor.plan, providers);
    result = await decrypt(data.descriptor, data.privateKey, data.envelope);
    if (!complete(data.descriptor.plan, result.fields, result.lastURL, providers)) throw Error();
    const ids = new Set(data.descriptor.plan.fields.map(f => f.id));
    if (Object.entries(result.fields).some(([k,v]) => !ids.has(k) || typeof v !== 'string' || v.length > 16384)) throw Error();
  } else throw Error();
  process.stdout.write(JSON.stringify(result));
} catch { process.stderr.write('Browser login data was invalid or unsupported.'); process.exitCode = 1; }
