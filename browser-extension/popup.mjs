import {pairingLink} from './protocol.mjs';
import providers from './providers.mjs';
const $ = id => document.getElementById(id);
let descriptor;
async function status() {
  const state = await chrome.storage.session.get('status');
  if (state.status) $('status').textContent = state.status;
}
function review() {
  try {
    descriptor = pairingLink($('link').value.trim(), providers);
    const provider = providers.find(p => p.id === descriptor.plan.provider);
    $('provider').textContent = provider.name;
    $('destination').textContent = `Beeper Server handoff: ${descriptor.origin}`;
    $('fields').textContent = `Requested session fields: ${descriptor.plan.fields.map(f => f.id).join(', ')}`;
    $('preview').hidden = false;
    $('status').textContent = 'Only approve a pairing link you just requested from your Grok Bot.';
  } catch {
    descriptor = null;
    $('preview').hidden = true;
    $('status').textContent = 'This link is invalid or expired. Ask Grok for a fresh browser handoff.';
  }
}
$('review').onclick = review;
$('connect').onclick = async () => {
  if (!descriptor) return;
  const provider = providers.find(p => p.id === descriptor.plan.provider);
  const origins = [...provider.domains.map(d => `https://*.${d}/*`), descriptor.origin + '/*'];
  try {
    // Permission requests must originate directly from this user gesture.
    const granted = await chrome.permissions.request({origins});
    if (!granted) { $('status').textContent = 'Site access was not granted. Nothing was collected.'; return; }
    const result = await chrome.runtime.sendMessage({action:'start', link:$('link').value.trim()});
    $('status').textContent = result.message;
  } catch { $('status').textContent = 'Could not start the handoff. Check site permissions and try again.'; }
};
$('cancel').onclick = async () => {
  await chrome.runtime.sendMessage({action:'cancel'});
  await status();
};
chrome.storage.onChanged.addListener(status);
const [tab] = await chrome.tabs.query({active:true, currentWindow:true});
if (tab?.url?.includes('/connect#')) { $('link').value = tab.url; review(); }
await status();
