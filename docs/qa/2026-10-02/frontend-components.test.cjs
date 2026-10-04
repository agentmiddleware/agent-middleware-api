// DOM/component fallback. No browser rendering claims; all fetches are stubbed.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const os = require('node:os');
const {spawnSync} = require('node:child_process');
const modules = process.env.QA_NODE_MODULES || '/private/tmp/amw-qa-browser/node_modules';
const {JSDOM} = require(`${modules}/jsdom`);
const ts = require(`${modules}/typescript`);
const root = path.resolve(__dirname, '../../..');
function page(file) {
  // Deliberately omit resources: no subresource loading is enabled.
  return new JSDOM(fs.readFileSync(path.join(root, file), 'utf8'), {
    url: 'http://127.0.0.1:8765/', runScripts: 'outside-only',
  });
}
function script(dom, file) {
  vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), dom.getInternalVMContext(), {filename: path.join(root, file)});
}

test('calculator covers empty, valid, equal, zero, invalid and overflow classes', () => {
  const dom = page('site/index.html');
  try {
    dom.window.fetch = () => {throw new Error('Unexpected network attempt');};
    script(dom, 'site/pilot-fit.js');
    const d = dom.window.document;
    const inputs = [...d.querySelectorAll('.pilot-fit input')];
    const summary = () => d.querySelector('[data-fit-summary]').textContent;
    const guidance = () => d.querySelector('[data-fit-guidance]').textContent;
    const fill = values => {values.forEach((v, i) => {inputs[i].value = String(v);}); inputs[0].dispatchEvent(new dom.window.Event('input', {bubbles: true}));};
    assert.match(summary(), /Enter the four/);
    fill([100000, .1, 50, 80, 2800]);
    assert.match(summary(), /\$4,000.00/);
    assert.match(guidance(), /exceeds.*\$1,200.00/);
    assert.equal(d.querySelector('[data-fit-next]').hidden, false);
    fill([1, 100, 1, 100, 1]);
    assert.match(guidance(), /does not exceed/);
    fill([1, 100, 1.005, 100, 1]);
    assert.match(guidance(), /exceeds.*\$0.01/);
    fill([0, 100, 50, 100, 0]);
    assert.match(guidance(), /no avoided duplicates/);
    fill([1, 100, 50, 100, '']);
    assert.match(guidance(), /fit is still unknown/);
    for (const [index, value] of [[0,-1],[0,.5],[1,-1],[1,101],[2,-1],[3,101],[4,-1]]) {
      const values = [100000,.1,50,80,2800]; values[index] = value; fill(values);
      assert.match(summary(), /Check your inputs/);
      assert.equal(inputs[index].getAttribute('aria-invalid'), 'true');
      assert.equal(d.querySelector('[data-fit-next]').hidden, true);
    }
    fill([100000, .1, 1e308, 80, 2800]);
    assert.match(summary(), /too large/);
    fill([1,100,'',100,0]);
    assert.match(summary(), /Enter the four/);
  } finally {dom.window.close();}
});

for (const failure of ['http', 'json', 'key-mismatch', 'missing-payload', null]) {
  test(`receipt component handles ${failure || 'valid artifacts'} without network`, async () => {
    const dom = page('site/proof/index.html');
    try {
      const receipt = JSON.parse(fs.readFileSync(path.join(root, 'site/proof/receipt.json'), 'utf8'));
      const keys = JSON.parse(fs.readFileSync(path.join(root, 'site/proof/trust-keys.json'), 'utf8'));
      const requests = [];
      dom.window.fetch = async (url, options) => {
        assert(['\/proof/receipt.json','\/proof/trust-keys.json'].includes(url));
        assert.equal(options.credentials, 'omit');
        requests.push(url);
        const body = url.includes('receipt') ? receipt : keys;
        if (failure === 'missing-payload') delete receipt.signing_input;
        if (failure === 'key-mismatch') keys.keys = [];
        return {ok: failure !== 'http', json: async () => {
          if (failure === 'json') throw new SyntaxError('Synthetic malformed JSON');
          return body;
        }};
      };
      script(dom, 'site/proof/proof.js');
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(requests.length, 2);
      assert.equal(dom.window.document.querySelector('[data-proof-status]').textContent,
        failure ? 'not published' : 'artifacts loaded');
      assert.match(dom.window.document.querySelector('[data-proof-message]').textContent,
        failure ? /No verification claim/ : /offline verifier/);
    } finally {dom.window.close();}
  });
}

function client() {
  const requests = [];
  let config;
  const transport = {};
  for (const method of ['get', 'post', 'delete']) transport[method] = async (...args) => {
    requests.push({method, args}); return {data: {status: 'synthetic'}};
  };
  const fakeAxios = {create(options) {config = options; return transport;}};
  const module = {exports: {}};
  const source = fs.readFileSync(path.join(root, 'awi_sdk/typescript/index.ts'), 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true}}).outputText;
  vm.runInNewContext(compiled, {exports: module.exports, module, require(name) {
    assert.equal(name, 'axios'); return fakeAxios;
  }}, {filename: 'qa-transpiled-awi-sdk.js'});
  const sdk = new module.exports.AWIClient({baseUrl: 'http://127.0.0.1:8769', apiKey: require('node:crypto').randomUUID()});
  return {sdk, requests, config};
}

test('SDK fails before transport for missing permit and invalid idempotency keys', async () => {
  const {sdk, requests, config} = client();
  assert.equal(config.maxRedirects, 0);
  for (const options of [undefined, {}, {permitId: ' '}, {permitId: 'permit', idempotencyKey: ' '}, {permitId: 'permit', idempotencyKey: 'a'.repeat(129)}]) {
    await assert.rejects(sdk.execute('session', 'get_representation', {}, options));
  }
  assert.equal(requests.length, 0);
});

test('SDK preserves retry identity, astral boundary and governed headers', async () => {
  const {sdk, requests} = client();
  const options = {permitId: ' permit ', idempotencyKey: 'a'.repeat(128)};
  await sdk.execute('session', 'get_representation', {}, options);
  await sdk.execute('session', 'get_representation', {}, options);
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[0].args[2], requests[1].args[2]);
  assert.equal(requests[0].args[2].headers['X-Permit-Id'], 'permit');
  await sdk.execute('session', 'get_representation', {}, {...options, idempotencyKey: '😀'.repeat(128)});
  assert.equal(requests.length, 3);
  await assert.rejects(sdk.execute('session', 'get_representation', {}, {...options, idempotencyKey: '😀'.repeat(129)}));
  assert.equal(requests.length, 3);
});

test('FE-001: declared SDK build produces its advertised entrypoints', {todo: 'FE-001: npm run build exits 1 because tsconfig.json is absent'}, () => {
  const target = fs.mkdtempSync(path.join(os.tmpdir(), 'amw-qa-sdk-build-'));
  // Copy tracked package source only; no credential or environment files.
  for (const name of ['index.ts', 'package.json', 'LICENSE', 'tsconfig.json']) {
    const source = path.join(root, 'awi_sdk/typescript', name);
    if (fs.existsSync(source)) fs.copyFileSync(source, path.join(target, name));
  }
  fs.symlinkSync(modules, path.join(target, 'node_modules'), 'dir');
  const result = spawnSync('npm', ['run', 'build'], {cwd: target, encoding: 'utf8', timeout: 30000,
    env: {PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: os.tmpdir(), npm_config_cache: path.join(os.tmpdir(), 'amw-qa-npm-cache')}});
  assert.equal(result.status, 0, 'Declared npm run build must succeed');
  const pkg = JSON.parse(fs.readFileSync(path.join(target, 'package.json'), 'utf8'));
  for (const entrypoint of [pkg.main, pkg.types]) assert.equal(fs.existsSync(path.join(target, entrypoint)), true);
});

test('FE-002: maxSteps=0 is not silently promoted to 100 actions', async () => {
  const {sdk, requests} = client();
  await sdk.createSession('http://127.0.0.1:8769/synthetic', {maxSteps: 0});
  assert.equal(requests.length, 1);
  assert.equal(requests[0].args[1].max_steps, 0);
});

test('FE-002: session limits default only when absent and preserve API validation boundaries', async () => {
  const {sdk, requests} = client();
  const target = 'http://127.0.0.1:8769/synthetic';
  for (const options of [undefined, {}, {maxSteps: undefined}, {maxSteps: null}]) {
    await sdk.createSession(target, options);
    assert.equal(requests.at(-1).args[1].max_steps, 100);
  }
  // Invalid values must reach the API unchanged, so its 1..1000 bounds apply.
  for (const maxSteps of [-1, 0, 0.5, 1, 1000, 1001]) {
    await sdk.createSession(target, {maxSteps, allowHumanPause: false});
    const request = requests.at(-1);
    assert.equal(request.method, 'post');
    assert.equal(request.args[0], '/v1/awi/sessions');
    assert.equal(request.args[1].max_steps, maxSteps);
    assert.equal(request.args[1].allow_human_pause, false);
  }
  assert.equal(requests.length, 10);
});
