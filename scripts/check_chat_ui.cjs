/**
 * scripts/check_chat_ui.cjs
 * Browser regression check for Synchrono chat UI against POST /chat contract.
 * Uses native Node child_process/assert and agent-browser CLI.
 *
 * ponytail: evaluate-driven mock stream used; upgrade to CDP Fetch domain if worker interception needed.
 */
const { execFileSync } = require('child_process');
const assert = require('assert');

const baseUrl = process.argv[2] || process.env.BASE_URL || 'http://127.0.0.1:8000';
const session = 'check-ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);

const run = (args, input) => execFileSync('agent-browser', ['--session', session, ...args], {
  encoding: 'utf8', input: input || undefined, stdio: ['pipe', 'pipe', 'pipe']
});

const evalFn = (code) => {
  const res = JSON.parse(run(['eval', '--json', '--stdin'], code));
  assert.strictEqual(res.success, true, res.error ? (res.error.message || JSON.stringify(res.error)) : 'eval failed');
  return res.data && res.data.result;
};

const waitFn = (cond) => run(['wait', '--fn', cond]);

const submit = (q, pii = true) => evalFn(`(() => {
  const t = document.getElementById("toggle-pii");
  if (t) { t.checked = ${JSON.stringify(pii)}; t.dispatchEvent(new Event("change")); }
  const i = document.getElementById("chat-input");
  i.value = ${JSON.stringify(q)};
  document.getElementById("chat-form").dispatchEvent(new Event("submit", { cancelable: true }));
})()`);

async function check() {
  try {
    run(['open', baseUrl]);
    run(['wait', '#chat-form']);

    // Isolate: block all /chat to backend from start; record calls
    evalFn(`(() => {
      window.__h = { calls: [], handler: null, pending: null, abortCtrl: null };
      const orig = window.fetch.bind(window);
      window.fetch = async (url, opts) => {
        const u = String(url);
        if (u.includes("/chat")) {
          const rec = { url: u, method: opts?.method || "GET", opts, json: opts?.body ? JSON.parse(opts.body) : null };
          window.__h.calls.push(rec);
          if (window.__h.handler) return window.__h.handler(u, opts, rec);
          return new Response(JSON.stringify({ detail: "Blocked by harness" }), { status: 500, headers: { "Content-Type": "application/json" } });
        }
        return orig(url, opts);
      };
    })()`);

    // 1. Initial load: no legacy /api/v1 calls
    const initUrls = evalFn(`performance.getEntriesByType("resource").map(r => r.name)`);
    assert.ok(initUrls.every(u => !u.includes('/api/v1')), 'Legacy /api/v1 called on init');

    // 2. Direct chat behavior: query submits immediately without connection ID prompt
    evalFn(`window.__h.handler = () => new Response(new ReadableStream({
      start(c) {
        const enc = new TextEncoder();
        c.enqueue(enc.encode('data: {"step":"START"}\\n\\ndata: {"step":"TOOL_CALL"}\\n\\n'));
        c.enqueue(enc.encode('data: {"step":"AIMessageChunk","content":"Halo '));
        c.enqueue(enc.encode('dunia"}\\n\\ndata: {"step":"TITLE","content":"Judul Valid"}\\n\\n'));
        c.enqueue(enc.encode('data: {"step":"END","content":"Halo dunia"}\\n\\n'));
        c.close();
      }
    }), { headers: { "Content-Type": "text/event-stream" } })`);

    submit('Tanya status batch', true);
    waitFn(`document.body.innerText.includes("Halo dunia") && !document.getElementById("chat-input").disabled`);
    assert.strictEqual(evalFn(`window.__h.calls.length`), 1, 'Chat query dispatches directly to /chat');
    assert.strictEqual(evalFn(`document.getElementById("input-connection-id") === null`), true, 'Connection ID input element removed');

    // 3. Exact POST /chat contract: url, method, exact keys, PII true/false, user/thread format & stability, framing-split SSE
    // 3a. Submit with PII enabled (default)
    const s3a = evalFn(`({ req: window.__h.calls.pop(), title: document.getElementById("current-chat-title").innerText })`);
    assert.strictEqual(s3a.req.url, '/chat');
    assert.strictEqual(s3a.req.method, 'POST');
    assert.deepStrictEqual(Object.keys(s3a.req.json).sort(), ['enable_pii', 'question', 'thread_id', 'user_id']);
    assert.strictEqual(s3a.req.json.question, 'Tanya status batch');
    assert.strictEqual(s3a.req.json.enable_pii, true);
    assert.ok(s3a.req.json.user_id && s3a.req.json.user_id.length <= 36);
    assert.ok(s3a.req.json.thread_id && s3a.req.json.thread_id.length <= 36);
    assert.strictEqual(s3a.title, 'Judul Valid');
    const stableThread = s3a.req.json.thread_id;

    // 3b. Submit with PII disabled; assert thread stability
    submit('Tanya PII off', false);
    waitFn(`document.body.innerText.includes("Halo dunia") && !document.getElementById("chat-input").disabled`);
    const s3bReq = evalFn(`window.__h.calls.pop()`);
    assert.strictEqual(s3bReq.json.enable_pii, false);
    assert.strictEqual(s3bReq.json.question, 'Tanya PII off');
    assert.strictEqual(s3bReq.json.thread_id, stableThread, 'Thread must remain stable across queries');

    // 4. END with empty content shows server empty error
    evalFn(`window.__h.handler = () => new Response(new ReadableStream({
      start(c) { c.enqueue(new TextEncoder().encode('data: {"step":"START"}\\n\\ndata: {"step":"END","content":""}\\n\\n')); c.close(); }
    }), { headers: { "Content-Type": "text/event-stream" } })`);
    submit('Tes respons kosong');
    waitFn(`document.body.innerText.includes("respons kosong") && !document.getElementById("chat-input").disabled`);

    // 5. Controlled stream rejection after partial keeps partial response and shows error
    evalFn(`window.__h.handler = () => new Response(new ReadableStream({
      start(c) { window.__h.abortCtrl = c; c.enqueue(new TextEncoder().encode('data: {"step":"AIMessageChunk","content":"Teks terselamatkan"}\\n\\n')); }
    }), { headers: { "Content-Type": "text/event-stream" } })`);
    submit('Tes partial abort');
    waitFn(`document.body.innerText.includes("Teks terselamatkan")`);
    evalFn(`window.__h.abortCtrl.error(new Error("Jaringan putus"))`);
    waitFn(`document.body.innerText.includes("Jaringan putus") && !document.getElementById("chat-input").disabled`);

    // 6. HTTP 422 with literal HTML safely text-escaped
    evalFn(`window.__h.handler = () => new Response(JSON.stringify({ detail: "<b>Unprocessable Detail</b>" }), {
      status: 422, headers: { "Content-Type": "application/json" }
    })`);
    submit('Tes 422 literal tag');
    waitFn(`document.body.innerText.includes("Unprocessable Detail") && !document.getElementById("chat-input").disabled`);
    assert.strictEqual(evalFn(`document.querySelector("#messages-container b") !== null`), false, 'Literal HTML in 422 must not create raw DOM elements');

    // 7. New-session guarded during pending stream (no timers); changes thread when idle
    evalFn(`window.__h.handler = () => new Response(new ReadableStream({
      start(c) { window.__h.pending = c; }
    }), { headers: { "Content-Type": "text/event-stream" } })`);
    submit('Tes delay guard');
    evalFn(`document.getElementById("btn-toggle-history").click()`);
    waitFn(`document.getElementById("btn-new-chat")?.disabled === true`);
    assert.strictEqual(evalFn(`document.getElementById("chat-input").disabled`), true);
    // Release pending stream explicitly
    evalFn(`(() => { window.__h.pending.enqueue(new TextEncoder().encode('data: {"step":"END","content":"selesai"}\\n\\n')); window.__h.pending.close(); })()`);
    waitFn(`!document.getElementById("chat-input").disabled`);

    const getThread = () => evalFn(`(document.getElementById("conversation-list")?.textContent || "").match(/Thread ID:\\s*([^\\s]+)/)?.[1]`);
    const threadBefore = getThread();
    assert.strictEqual(threadBefore, stableThread, 'Initial thread matches conversation drawer');
    evalFn(`(() => {
      if (!document.getElementById("history-drawer")?.classList.contains("open")) {
        document.getElementById("btn-toggle-history").click();
      }
      document.getElementById("btn-new-chat").click();
    })()`);
    waitFn(`document.getElementById("current-chat-title").innerText.includes("Percakapan Baru")`);
    const threadAfter = getThread();
    assert.ok(threadBefore && threadAfter && threadBefore !== threadAfter, 'New chat must update thread ID');

    // Verify zero legacy /api/v1 throughout all calls
    const allUrls = evalFn(`window.__h.calls.map(c => c.url)`);
    assert.ok(allUrls.every(u => !u.includes('/api/v1')), 'Legacy /api/v1 found in requests');
  } finally {
    try { run(['close']); } catch (_) {}
  }
}

check().catch(e => { console.error(e); process.exit(1); });
