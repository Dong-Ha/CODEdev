/* Optional DOM/HTTP integration test. Requires jsdom and a disposable server:
 * AX_CONFIG_FILE=/tmp/ax-ui/profiles.json python app.py --port 8876
 * NODE_PATH=/path/to/jsdom/node_modules node tests/test_intake_dom.cjs
 * This checks DOM behavior, not browser layout or CSS rendering.
 */
const {JSDOM, VirtualConsole} = require('jsdom');
const assert = require('node:assert/strict');
const base = process.env.AX_TEST_URL || 'http://127.0.0.1:8876';
const errors = [];
async function open() {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  const dom = await JSDOM.fromURL(base, {
    runScripts: 'dangerously', resources: 'usable', virtualConsole,
    beforeParse(window) {
      window.fetch = (url, options) => fetch(new URL(url, base), options);
      window.confirm = () => true;
    },
  });
  const document = dom.window.document;
  await until(() => document.querySelector('#agentIntakeStatus')?.textContent.includes('외부 요청 접수') && !document.querySelector('#sample').disabled);
  return dom;
}
async function until(predicate) {
  const deadline = Date.now() + 7000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('Timed out waiting for UI state');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}
function fill(dom, id, value) {
  const input = dom.window.document.getElementById(id);
  input.value = value;
  input.dispatchEvent(new dom.window.Event('input', {bubbles: true}));
}
function click(dom, id) { dom.window.document.getElementById(id).click(); }
function submit(dom, id, send=false) { dom.window.document.getElementById(id).dispatchEvent(new dom.window.SubmitEvent('submit', {bubbles: true, cancelable: true, submitter:id==='requestForm' ? dom.window.document.getElementById(send ? 'submitRequest' : 'saveRequest') : null})); }
(async () => {
  let dom = await open();
  let document = dom.window.document;
  click(dom, 'sample');
  await until(() => !document.getElementById('environmentFields').disabled);
  fill(dom, 'development_environment', 'Windows 11 + WSL Ubuntu 24.04');
  fill(dom, 'target_environment', 'Android 16 / IFPMIC charger');
  fill(dom, 'toolchain', 'Clang 18');
  fill(dom, 'editable_paths', 'drivers/power/supply/ax_ifpmic_charger.c');
  submit(dom, 'environmentForm');
  await until(() => !document.getElementById('goRequest').disabled);
  assert.match(document.getElementById('fileList').textContent, /ax_ifpmic_charger/);
  click(dom, 'goRequest');
  assert.equal(document.getElementById('requestView').hidden, false);
  fill(dom, 'sourceKind', 'jira');
  fill(dom, 'sourceRef', 'PMIC-123');
  fill(dom, 'sourceContent', '음수 입력을 거부한다. <script>alert(1)</script>');
  click(dom, 'example');
  submit(dom, 'requestForm');
  await until(() => document.getElementById('requestDetail').textContent.includes('PMIC-123'));
  await until(() => !document.getElementById('sample').disabled);
  assert.match(document.getElementById('requestDetail').textContent, /전송 대기/);
  assert.match(document.getElementById('requestDetail').textContent, /Clang 18/);
  assert.equal(document.getElementById('requestDetail').querySelector('script'), null);
  assert.match(document.getElementById('requestDetail').textContent, /전달 JSON 다운로드/);
  const count = document.getElementById('queueCount').textContent;
  // Repeating the same form submission uses the same idempotency key.
  submit(dom, 'requestForm');
  await until(() => !document.getElementById('sample').disabled);
  assert.equal(document.getElementById('queueCount').textContent, count);
  dom.window.close();

  dom = await open(); document = dom.window.document;
  click(dom, 'navQueue');
  await until(() => document.querySelector('.request-item'));
  document.querySelector('.request-item').click();
  await until(() => document.getElementById('requestDetail').textContent.includes('PMIC-123'));
  assert.match(document.getElementById('requestDetail').textContent, /Windows 11/);
  click(dom, 'navEnvironment'); fill(dom, 'toolchain', 'Clang 19'); click(dom, 'navRequest');
  assert.equal(document.getElementById('requestView').hidden, true);
  submit(dom, 'environmentForm');
  await until(() => !document.getElementById('goRequest').disabled);
  click(dom, 'navQueue');
  await until(() => document.querySelector('.request-item'));
  document.querySelector('.request-item').click();
  await until(() => document.getElementById('requestDetail').textContent.includes('접수 후 환경 설정이 변경'));
  assert.match(document.getElementById('requestDetail').textContent, /Clang 18/);
  assert.deepEqual(errors, []);
  if (process.env.AX_TEST_CLI === '1') {
    // Saved pre-change task is stale; make a new request using the current profile.
    click(dom, 'navRequest');
    fill(dom, 'instruction', '새 환경에서 입력 전류 검증 방법을 설명해줘.');
    submit(dom, 'requestForm', true);
    await until(() => document.getElementById('requestDetail').textContent.includes('Claude 응답 완료'));
    assert.match(document.querySelector('.cli-response').textContent, /소스 본문이 필요/);
    assert.equal(document.querySelector('.cli-response script'), null);
    assert.match(document.querySelector('.request-item').textContent, /Claude 응답 완료/);
    await until(() => !document.getElementById('dispatchRequest').disabled);
    click(dom, 'dispatchRequest');
    await until(() => document.getElementById('requestDetail').textContent.includes('실행 2/5') && document.getElementById('requestDetail').textContent.includes('Claude 응답 완료'));
    assert.match(document.getElementById('requestDetail').textContent, /실제 전송한 프롬프트/);
    assert.match(document.getElementById('requestDetail').textContent, /이전 전송 결과/);
  }
  dom.window.close();
  assert.deepEqual(errors, []);
  console.log('PASS: environment save, exact file scope, Jira request, safe text rendering, idempotency, reload persistence, unsaved guard, stale snapshot' + (process.env.AX_TEST_CLI === '1' ? ', direct CLI send, response polling, explicit resend.' : '.'));
})().catch(error => { console.error(error); process.exit(1); });
