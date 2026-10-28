// Execute the pricing page's JavaScript against a minimal DOM stub and a
// mocked fetch, to prove the button flow works: clicking "Upgrade to Pro"
// must call /api/v1/billing/checkout with the right plan and navigate to the
// returned Stripe URL.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, 'utf8');
const script = (html.match(/<script>([\s\S]*?)<\/script>/) || [])[1] || '';

if (!script) { console.error('NO SCRIPT FOUND'); process.exit(1); }

// ---- DOM stub -----------------------------------------------------------
const elements = {};
function mkEl(id, tag) {
  return {
    id, tagName: tag || 'div', value: '', innerText: '', textContent: '',
    className: '', classList: { add(){}, remove(){}, toggle(){}, contains(){return false;} },
    style: {}, dataset: {}, scrollIntoView(){}, focus(){},
    addEventListener(){}, querySelector(){ return null; },
    querySelectorAll(){ return []; },
  };
}
['key','plan','err','signupLink','keypanel'].forEach(id => { elements[id] = mkEl(id); });

// The page sets #plan from the query string on DOMContentLoaded.
elements.plan.value = 'pro';

const document = {
  getElementById: id => elements[id] || null,
  querySelector: sel => {
    const m = sel.match(/^#plan-(\w+) button$/);
    if (m) return { textContent: 'Upgrade to ' + m[1], disabled: false };
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: (ev, fn) => { if (ev === 'DOMContentLoaded') { try { fn(); } catch(e){} } },
  body: { innerText: '' },
  title: '',
};

const store = {};
const localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};

// ---- fetch mock ---------------------------------------------------------
let fetchCalls = [];
let navigatedTo = null;
async function fetch(url, opts) {
  fetchCalls.push({ url, opts });
  const plan = JSON.parse((opts && opts.body) || '{}').plan;
  return {
    ok: true,
    status: 200,
    json: async () => ({ url: 'https://checkout.stripe.com/c/pay/cs_test_FAKE_' + plan }),
  };
}

const window = {
  location: { href: '', search: '?plan=pro' },
  addEventListener: document.addEventListener,
};
Object.defineProperty(window.location, 'href', {
  get() { return navigatedTo || 'https://spantrail.com/pricing'; },
  set(v) { navigatedTo = v; },
});

const sandbox = {
  document, window, localStorage, fetch,
  URLSearchParams, console,
  setTimeout, clearTimeout, setInterval, clearInterval,
};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
try {
  vm.runInContext(script, sandbox, { filename: 'pricing.js' });
} catch (e) {
  console.error('SCRIPT THREW AT LOAD:', e.message);
  process.exit(1);
}
console.log('PASS: script loaded without throwing');

async function main() {
  // ---- 1. the plan field must exist ---------------------------------------
  if (!elements.plan) { console.error('FAIL: no #plan element'); process.exit(1); }
  console.log('PASS: #plan element exists, value =', elements.plan.value);

  // ---- 2. clicking Upgrade to Pro -----------------------------------------
  elements.key.value = 'spantrail_sk_testkey';
  const before = fetchCalls.length;
  await sandbox.start('pro');
  console.log('fetch calls made:', fetchCalls.length - before);
  if (fetchCalls.length === before) {
    console.error('FAIL: start() did not call fetch');
    process.exit(1);
  }
  const call = fetchCalls[fetchCalls.length - 1];
  console.log('  url  :', call.url);
  console.log('  body :', call.opts.body);
  console.log('  key  :', call.opts.headers['X-API-Key']);
  if (call.url !== '/api/v1/billing/checkout') { console.error('FAIL: wrong endpoint'); process.exit(1); }
  if (JSON.parse(call.opts.body).plan !== 'pro') { console.error('FAIL: wrong plan'); process.exit(1); }
  console.log('PASS: start("pro") called the checkout endpoint with plan=pro');

  // ---- 3. it must navigate to the Stripe URL --------------------------------
  if (!navigatedTo || !navigatedTo.includes('checkout.stripe.com')) {
    console.error('FAIL: did not navigate to the Stripe checkout URL, got:', navigatedTo);
    process.exit(1);
  }
  console.log('PASS: navigated to', navigatedTo);

  // ---- 4. team plan --------------------------------------------------------
  navigatedTo = null;
  await sandbox.start('team');
  console.log('PASS: team plan ->', navigatedTo);

  // ---- 5. no key -> must not call fetch -----------------------------------
  elements.key.value = '';
  delete store['spantrail_key'];
  const n = fetchCalls.length;
  await sandbox.start('pro');
  const added = fetchCalls.length - n;
  console.log('no-key path: fetch calls added =', added);
  console.log('  key value seen by the page:', JSON.stringify(elements.key.value));
  console.log('  localStorage had key    :', 'spantrail_key' in store);
  console.log('  err text                :', JSON.stringify(elements.err.textContent));
  if (added !== 0) {
    console.error('FAIL: the no-key path called the API', fetchCalls[fetchCalls.length - 1]);
    process.exit(1);
  }
  console.log('PASS: the no-key path does not hit the API');

}

main().catch(e => { console.error('UNCAUGHT:', e && e.message); process.exit(1); });
