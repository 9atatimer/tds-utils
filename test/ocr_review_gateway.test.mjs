// test/ocr_review_gateway.test.mjs -- OCR on Demand, the review job's road
// to the model (docs/design/OCR-ON-DEMAND.DESIGN.md: Review job table, G5;
// OLLAMA-GATEWAY.DESIGN.md: API / Interface, Credential contract).
// Configuration, credential resolution with masking, and the probe. Fakes
// for 1Password, the gateway and the clock; no network, no sleeps.
// Run: node --test test/ocr_review_gateway.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  BACKENDS,
  COLD_MODEL_LIMIT_MS,
  GATEWAY_STATUS,
  backendProfile,
  classifyProbeAnswer,
  extraHeadersValue,
  itemReferences,
  probeGateway,
  resolveCredentials,
  resolveBackend,
  resolveGatewayConfig,
  resolveModel,
  variablePrefix,
} from '../lib/ocr-review/gateway.mjs';

const ITEM = 'op://vault-uuid/item-title';
const config = (over) => ({
  token: 'set',
  item: ITEM,
  url: 'https://gateway.example',
  configuredModel: 'qwen3.6:latest',
  override: '',
  trigger: 'dispatch',
  backend: 'ollama-gateway',
  ...over,
});

// --- Model and configuration -------------------------------------------------

test('the model override applies to a dispatch only', () => {
  assert.equal(resolveModel({ trigger: 'dispatch', override: 'gemma4:27b', configured: 'qwen3.6:latest' }), 'gemma4:27b');
  assert.equal(resolveModel({ trigger: 'comment', override: 'gemma4:27b', configured: 'qwen3.6:latest' }), 'qwen3.6:latest');
  assert.equal(resolveModel({ trigger: 'dispatch', override: '  ', configured: 'qwen3.6:latest' }), 'qwen3.6:latest');
  assert.equal(resolveModel({ trigger: 'dispatch', override: '', configured: '' }), null);
});

test('a complete configuration resolves the url and model', () => {
  const c = resolveGatewayConfig(config());
  assert.equal(c.ok, true);
  assert.equal(c.url, 'https://gateway.example');
  assert.equal(c.model, 'qwen3.6:latest');
});

test('a trailing slash on the url is dropped', () => {
  assert.equal(resolveGatewayConfig(config({ url: 'https://gateway.example/' })).url, 'https://gateway.example');
});

test('each missing secret or variable fails configuration, naming it', () => {
  for (const [field, name] of [
    ['token', 'OLLAMA_GATEWAY_OP_SA_TOKEN'],
    ['item', 'OLLAMA_GATEWAY_OP_ITEM'],
    ['url', 'OLLAMA_GATEWAY_URL'],
    ['configuredModel', 'OLLAMA_GATEWAY_MODEL'],
  ]) {
    const c = resolveGatewayConfig(config({ [field]: '' }));
    assert.equal(c.ok, false, field);
    assert.equal(c.cause, 'configuration');
    assert.match(c.detail, new RegExp(name));
  }
});

test('the model is still resolved when only a dispatch override names one', () => {
  const c = resolveGatewayConfig(config({ configuredModel: '', override: 'gemma4:27b' }));
  assert.equal(c.ok, true);
  assert.equal(c.model, 'gemma4:27b');
});

test('a non-https url or a non-op:// item reference is a configuration failure', () => {
  assert.equal(resolveGatewayConfig(config({ url: 'http://gateway.example' })).cause, 'configuration');
  assert.equal(resolveGatewayConfig(config({ item: 'vault/item' })).cause, 'configuration');
});

test('a configuration failure never echoes the item reference', () => {
  const c = resolveGatewayConfig(config({ url: '' }));
  assert.doesNotMatch(c.detail, /vault-uuid|item-title/);
});

// --- Credentials -------------------------------------------------------------

test('the item is read at the four fields of the credential contract', () => {
  assert.deepEqual(
    itemReferences(ITEM).map((r) => r.ref),
    [`${ITEM}/access/client id header`, `${ITEM}/access/client id`, `${ITEM}/access/client secret header`, `${ITEM}/password`],
  );
});

/** A 1Password reader answering from a table; records reads and masks in one log. */
function fakeVault(values, { failOn = null, failKind = 'item' } = {}) {
  const log = [];
  return {
    log,
    readSecret: async (ref) => {
      log.push(['read', ref]);
      if (failOn && ref.endsWith(failOn)) {
        const error = new Error('op failed');
        error.kind = failKind;
        throw error;
      }
      return values[ref.slice(ITEM.length + 1)];
    },
    mask: (value) => log.push(['mask', value]),
  };
}

const ITEM_VALUES = {
  'access/client id header': 'CF-Access-Client-Id',
  'access/client id': 'id-123.access',
  'access/client secret header': 'CF-Access-Client-Secret',
  password: 'secret-456',
};

test('credentials resolve to the header names and values the item carries', async () => {
  const vault = fakeVault(ITEM_VALUES);
  const r = await resolveCredentials(ITEM, vault);
  assert.equal(r.ok, true);
  assert.deepEqual(r.headers, { 'CF-Access-Client-Id': 'id-123.access', 'CF-Access-Client-Secret': 'secret-456' });
});

test('every resolved value is masked as soon as it is read, before the next read', async () => {
  const vault = fakeVault(ITEM_VALUES);
  await resolveCredentials(ITEM, vault);
  for (const [i, entry] of vault.log.entries()) {
    if (entry[0] !== 'read') continue;
    const value = ITEM_VALUES[entry[1].slice(ITEM.length + 1)];
    assert.deepEqual(vault.log[i + 1], ['mask', value], `value read at ${entry[1]} is masked next`);
  }
  assert.equal(vault.log.filter((e) => e[0] === 'mask').length, 4);
});

test('an invalid token fails configuration, saying the token was refused', async () => {
  const r = await resolveCredentials(ITEM, fakeVault(ITEM_VALUES, { failOn: 'client id header', failKind: 'token' }));
  assert.equal(r.ok, false);
  assert.equal(r.cause, 'configuration');
  assert.match(r.detail, /OLLAMA_GATEWAY_OP_SA_TOKEN/);
});

test('an unreadable item field fails configuration, naming the field but not the item', async () => {
  const r = await resolveCredentials(ITEM, fakeVault(ITEM_VALUES, { failOn: 'password' }));
  assert.equal(r.cause, 'configuration');
  assert.match(r.detail, /password/);
  assert.match(r.detail, /OLLAMA_GATEWAY_OP_ITEM/);
  assert.doesNotMatch(r.detail, /vault-uuid|item-title/);
});

test('an empty field, or a header name or value that cannot travel as a header, fails configuration', async () => {
  for (const [field, bad] of [
    ['password', ''],
    ['access/client id header', 'Bad Header'],
    ['access/client id', 'a,b'],
    ['password', 'line\nbreak'],
  ]) {
    const r = await resolveCredentials(ITEM, fakeVault({ ...ITEM_VALUES, [field]: bad }));
    assert.equal(r.cause, 'configuration', `${field}=${JSON.stringify(bad)}`);
    if (bad) assert.doesNotMatch(r.detail, new RegExp(bad.replace(/\n/, '\\n')));
  }
});

test('headers travel to ocr as K=V pairs joined by commas', () => {
  assert.equal(extraHeadersValue({ A: '1', B: '2' }), 'A=1,B=2');
});

// --- Probe classification (G5) ---------------------------------------------

test('an Access refusal (302 or 403) is credential', () => {
  for (const status of [302, 403]) assert.deepEqual(classifyProbeAnswer({ status }).cause, 'credential');
});

test('tunnel down, connector 502, proxy ollama-down, or no HTTP answer is gateway-down', () => {
  for (const status of [GATEWAY_STATUS.tunnelDown, GATEWAY_STATUS.proxyDown, GATEWAY_STATUS.ollamaDown]) {
    assert.equal(classifyProbeAnswer({ status }).cause, 'gateway-down', String(status));
  }
  assert.equal(classifyProbeAnswer({ error: 'getaddrinfo ENOTFOUND' }).cause, 'gateway-down');
});

test('the deadline answer is the one retryable answer', () => {
  const c = classifyProbeAnswer({ status: GATEWAY_STATUS.deadline });
  assert.equal(c.kind, 'retry');
});

test('the deadline answer is the proxy\'s 507 Model Not Ready; ollama down is its 503', () => {
  // lmde proxy layer, routes/ollama-gateway.cfg and ollama-gateway.deadline.http.
  assert.equal(GATEWAY_STATUS.deadline, 507);
  assert.equal(GATEWAY_STATUS.ollamaDown, 503);
  assert.equal(classifyProbeAnswer({ status: 507 }).kind, 'retry');
  assert.equal(classifyProbeAnswer({ status: 504 }).cause, 'unexpected');
});

test('the deadline status is distinct from every other documented status', () => {
  const others = [GATEWAY_STATUS.tunnelDown, GATEWAY_STATUS.proxyDown, GATEWAY_STATUS.ollamaDown];
  assert.ok(!others.includes(GATEWAY_STATUS.deadline));
});

test('a non-Access 4xx is model-not-found', () => {
  for (const status of [400, 401, 404, 422]) assert.equal(classifyProbeAnswer({ status }).cause, 'model-not-found', String(status));
});

test('an undocumented 5xx, another 3xx, or a 200 that is not a completion is unexpected', () => {
  assert.equal(classifyProbeAnswer({ status: 500 }).cause, 'unexpected');
  assert.equal(classifyProbeAnswer({ status: 524 }).cause, 'unexpected');
  assert.equal(classifyProbeAnswer({ status: 301 }).cause, 'unexpected');
  assert.equal(classifyProbeAnswer({ status: 200, body: '<html>login</html>' }).cause, 'unexpected');
  assert.equal(classifyProbeAnswer({ status: 200, body: '{"choices":"no"}' }).cause, 'unexpected');
});

test('a 200 carrying a chat completion is ready', () => {
  const c = classifyProbeAnswer({ status: 200, body: JSON.stringify({ choices: [{ message: { content: 'OK' } }] }) });
  assert.equal(c.kind, 'ready');
});

test('a failure detail never carries the response body', () => {
  const c = classifyProbeAnswer({ status: 500, body: 'secret-ish upstream text' });
  assert.doesNotMatch(c.detail, /secret-ish/);
});

// --- Probe loop ----------------------------------------------------------------

/** A clock that only moves when the code under test sleeps or a request takes time. */
function fakeClock() {
  let t = 0;
  return {
    now: () => t,
    sleep: async (ms) => {
      t += ms;
    },
    advance: (ms) => {
      t += ms;
    },
  };
}

/** A gateway that answers from a script; each answer may take time. */
function fakeGateway(clock, answers, { takesMs = 0 } = {}) {
  const requests = [];
  return {
    requests,
    post: async (request) => {
      requests.push(request);
      clock.advance(takesMs);
      return answers[Math.min(requests.length - 1, answers.length - 1)];
    },
  };
}

const COMPLETION = { status: 200, body: JSON.stringify({ choices: [{ message: { content: 'OK' } }] }) };
const DEADLINE = { status: GATEWAY_STATUS.deadline, body: '' };
const target = { url: 'https://gateway.example', model: 'qwen3.6:latest', headers: { H: 'v' } };

test('a warm model is ready on the first probe, sent to the completions path with the headers', async () => {
  const clock = fakeClock();
  const gw = fakeGateway(clock, [COMPLETION]);
  const r = await probeGateway(target, { post: gw.post, clock });
  assert.equal(r.ok, true);
  assert.equal(gw.requests.length, 1);
  assert.equal(gw.requests[0].url, 'https://gateway.example/v1/chat/completions');
  assert.deepEqual(gw.requests[0].headers, { H: 'v' });
  assert.equal(gw.requests[0].body.model, 'qwen3.6:latest');
});

test('a cold model is retried through deadline answers until it answers', async () => {
  const clock = fakeClock();
  const gw = fakeGateway(clock, [DEADLINE, DEADLINE, COMPLETION], { takesMs: 90_000 });
  const r = await probeGateway(target, { post: gw.post, clock });
  assert.equal(r.ok, true);
  assert.equal(gw.requests.length, 3);
});

test('deadline answers for 6 minutes fail cold-model, and no attempt starts after the limit', async () => {
  const clock = fakeClock();
  const gw = fakeGateway(clock, [DEADLINE], { takesMs: 90_000 });
  const r = await probeGateway(target, { post: gw.post, clock });
  assert.equal(r.ok, false);
  assert.equal(r.cause, 'cold-model');
  // Attempts start at 0, 90+p, ... and none at or after the 6-minute mark.
  assert.ok(gw.requests.length >= 3);
  assert.ok(clock.now() <= COLD_MODEL_LIMIT_MS + 90_000);
});

test('a terminal answer fails at once, without a retry', async () => {
  for (const answer of [{ status: 403 }, { status: GATEWAY_STATUS.proxyDown }, { status: 404 }, { error: 'ECONNREFUSED' }]) {
    const clock = fakeClock();
    const gw = fakeGateway(clock, [answer, COMPLETION]);
    const r = await probeGateway(target, { post: gw.post, clock });
    assert.equal(r.ok, false, JSON.stringify(answer));
    assert.equal(gw.requests.length, 1);
    assert.ok(clock.now() < 60_000, 'decided within a minute');
  }
});

// --- Backends: the laptop's Ollama Gateway, or Cloudflare AI Gateway (Issue#481)

test('the backend: a dispatch override, else the configured one, else the Ollama Gateway', () => {
  assert.equal(resolveBackend({ trigger: 'dispatch', override: 'cf-ai-gateway', configured: '' }), BACKENDS.cf);
  assert.equal(resolveBackend({ trigger: 'comment', override: 'cf-ai-gateway', configured: '' }), BACKENDS.ollama);
  assert.equal(resolveBackend({ trigger: 'comment', override: '', configured: 'cf-ai-gateway' }), BACKENDS.cf);
  assert.equal(resolveBackend({ trigger: 'dispatch', override: ' ', configured: '' }), BACKENDS.ollama);
  assert.equal(resolveBackend({ trigger: 'dispatch', override: 'bogus', configured: '' }), null);
});

test('an unknown backend is a configuration failure naming the choices', () => {
  const c = resolveGatewayConfig(config({ backend: null }));
  assert.equal(c.cause, 'configuration');
  assert.match(c.detail, /ollama-gateway.*cf-ai-gateway/);
});

test('each backend names its own variables when one is missing', () => {
  for (const [field, name] of [
    ['item', 'CF_AI_GATEWAY_OP_ITEM'],
    ['url', 'CF_AI_GATEWAY_URL'],
    ['configuredModel', 'CF_AI_GATEWAY_MODEL'],
  ]) {
    const c = resolveGatewayConfig(config({ backend: BACKENDS.cf, [field]: '' }));
    assert.equal(c.cause, 'configuration', field);
    assert.match(c.detail, new RegExp(name));
    assert.doesNotMatch(c.detail, /OLLAMA_GATEWAY_(OP_ITEM|URL|MODEL)/);
  }
});

test('the OpenAI-compatible base: /v1 on the Ollama Gateway, /compat on Cloudflare AI Gateway', () => {
  assert.equal(resolveGatewayConfig(config()).apiBase, 'https://gateway.example/v1');
  const cf = resolveGatewayConfig(config({ backend: BACKENDS.cf, url: 'https://gateway.ai.cloudflare.com/v1/acct/personal/', configuredModel: 'workers-ai/@cf/x/y' }));
  assert.equal(cf.apiBase, 'https://gateway.ai.cloudflare.com/v1/acct/personal/compat');
  assert.equal(cf.backend, BACKENDS.cf);
});

test('the request profile: the Ollama body turns reasoning off; Cloudflare streams and has no placeholder bearer', () => {
  const ollama = backendProfile(BACKENDS.ollama);
  assert.equal(JSON.parse(ollama.extraBody).reasoning_effort, 'none');
  assert.equal(JSON.parse(ollama.extraBody).stream, true);
  assert.equal(ollama.authToken, 'ollama');
  const cf = backendProfile(BACKENDS.cf);
  assert.deepEqual(JSON.parse(cf.extraBody), { stream: true });
  // The gateway refuses a placeholder Authorization for Workers AI (401,
  // Issue#489): ocr's bearer is the run token, from the credential.
  assert.equal(cf.authToken, null);
});

test('a Cloudflare credential is the run token in password: an authorization header, the tool tag, and no payload logging', async () => {
  const masked = [];
  const read = [];
  const c = await resolveCredentials(
    ITEM,
    { readSecret: async (ref) => (read.push(ref), 'tok-123'), mask: (v) => masked.push(v) },
    BACKENDS.cf,
  );
  assert.equal(c.ok, true);
  assert.deepEqual(read, [`${ITEM}/password`]);
  assert.equal(c.authToken, 'tok-123', "ocr's bearer is the run token (Issue#489)");
  assert.deepEqual(c.headers, {
    'cf-aig-authorization': 'Bearer tok-123',
    'cf-aig-metadata': '{"tool":"ocr-review"}',
    'cf-aig-collect-log-payload': 'false',
  });
  assert.ok(masked.includes('tok-123'));
});

test('a Cloudflare run token that cannot travel as a header, or an empty one, is a configuration failure', async () => {
  for (const value of ['', 'a,b', 'a"b']) {
    const c = await resolveCredentials(ITEM, { readSecret: async () => value, mask: () => {} }, BACKENDS.cf);
    assert.equal(c.cause, 'configuration', JSON.stringify(value));
  }
});

test('the header list ocr parses keeps the tool tag JSON whole', () => {
  assert.equal(
    extraHeadersValue({ 'cf-aig-authorization': 'Bearer t', 'cf-aig-metadata': '{"tool":"ocr-review"}' }),
    'cf-aig-authorization=Bearer t,cf-aig-metadata={"tool":"ocr-review"}',
  );
});

test('Cloudflare answers: a completion is ready; 401/403 credential; 402 budget; 429 limited; other 4xx model-not-found; 5xx gateway-down', () => {
  const cf = (answer) => classifyProbeAnswer(answer, BACKENDS.cf);
  assert.equal(cf(COMPLETION).kind, 'ready');
  for (const status of [401, 403]) assert.equal(cf({ status }).cause, 'credential', String(status));
  // 402 is the credit balance; 429 is a spend limit OR the unified-billing
  // request rate (200/min), which the status alone cannot tell apart.
  assert.equal(cf({ status: 402 }).cause, 'budget');
  assert.equal(cf({ status: 429 }).cause, 'limited');
  for (const status of [400, 404]) assert.equal(cf({ status }).cause, 'model-not-found', String(status));
  for (const status of [500, 502, 503, 504]) assert.equal(cf({ status }).cause, 'gateway-down', String(status));
  assert.equal(cf({ error: 'ENOTFOUND' }).cause, 'gateway-down');
  assert.equal(cf({ status: 507 }).kind, 'fail', 'no cold-model retry on a hosted gateway');
});

test('a Cloudflare probe goes to the /compat completions path and is never retried', async () => {
  const clock = fakeClock();
  const gw = fakeGateway(clock, [{ status: 429 }, COMPLETION]);
  const r = await probeGateway(
    { url: 'https://gateway.ai.cloudflare.com/v1/acct/personal', apiBase: 'https://gateway.ai.cloudflare.com/v1/acct/personal/compat', backend: BACKENDS.cf, model: 'workers-ai/@cf/x', headers: { H: 'v' } },
    { post: gw.post, clock },
  );
  assert.equal(r.ok, false);
  assert.equal(r.cause, 'limited');
  assert.equal(gw.requests.length, 1);
  assert.equal(gw.requests[0].url, 'https://gateway.ai.cloudflare.com/v1/acct/personal/compat/chat/completions');
});

test('Cloudflare AI Gateway takes Workers AI models only: ocr always sends an Authorization header, which the gateway forwards to a third-party provider', () => {
  assert.equal(resolveGatewayConfig(config({ backend: BACKENDS.cf, configuredModel: 'workers-ai/@cf/moonshotai/kimi-k2.7-code' })).ok, true);
  for (const model of ['openai/gpt-5.5', 'anthropic/claude-x', '@cf/moonshotai/kimi-k2.6']) {
    const c = resolveGatewayConfig(config({ backend: BACKENDS.cf, configuredModel: model }));
    assert.equal(c.cause, 'configuration', model);
    assert.match(c.detail, /workers-ai\//);
  }
  const overridden = resolveGatewayConfig(config({ backend: BACKENDS.cf, configuredModel: 'workers-ai/@cf/a/b', override: 'openai/gpt-5.5' }));
  assert.equal(overridden.cause, 'configuration', 'a dispatch override is held to the same rule');
});

test('Cloudflare reasoning: CF_AI_GATEWAY_REASONING rides the body as reasoning_effort; unset sends none, so the model default applies', () => {
  assert.deepEqual(JSON.parse(backendProfile(BACKENDS.cf, { reasoning: 'none' }).extraBody), { stream: true, reasoning_effort: 'none' });
  assert.deepEqual(JSON.parse(backendProfile(BACKENDS.cf, { reasoning: '' }).extraBody), { stream: true });
  assert.deepEqual(JSON.parse(backendProfile(BACKENDS.cf).extraBody), { stream: true });
  // The Ollama profile is fixed: its reasoning is always off (Issue#479).
  assert.equal(JSON.parse(backendProfile(BACKENDS.ollama, { reasoning: 'high' }).extraBody).reasoning_effort, 'none');
});

test('a reasoning value that is not a single lowercase word is a configuration failure', () => {
  for (const reasoning of ['high, max', 'NONE"', 'x y']) {
    const c = resolveGatewayConfig(config({ backend: BACKENDS.cf, configuredModel: 'workers-ai/@cf/a/b', reasoning }));
    assert.equal(c.cause, 'configuration', reasoning);
    assert.match(c.detail, /CF_AI_GATEWAY_REASONING/);
  }
  assert.equal(resolveGatewayConfig(config({ backend: BACKENDS.cf, configuredModel: 'workers-ai/@cf/a/b', reasoning: 'none' })).ok, true);
});

// --- the Anthropic API backend ---------------------------------------------

test('the Anthropic backend: its own variables, the base URL as the API base, and no Workers AI rule', () => {
  assert.equal(variablePrefix(BACKENDS.anthropic), 'ANTHROPIC');
  assert.equal(variablePrefix(BACKENDS.cf), 'CF_AI_GATEWAY');
  assert.equal(variablePrefix(null), 'OLLAMA_GATEWAY');
  assert.equal(resolveBackend({ trigger: 'comment', override: '', configured: 'anthropic' }), BACKENDS.anthropic);
  const c = resolveGatewayConfig(config({ backend: BACKENDS.anthropic, url: 'https://api.anthropic.com/', configuredModel: 'claude-sonnet-5-5' }));
  assert.equal(c.ok, true);
  // ocr's Anthropic client appends /v1/messages itself.
  assert.equal(c.apiBase, 'https://api.anthropic.com');
  for (const field of ['item', 'url', 'configuredModel']) {
    const missing = resolveGatewayConfig(config({ backend: BACKENDS.anthropic, [field]: '' }));
    assert.match(missing.detail, /ANTHROPIC_/, field);
  }
});

test('the Anthropic profile: protocol anthropic, the key on x-api-key, no placeholder, an empty body', () => {
  const p = backendProfile(BACKENDS.anthropic, { reasoning: 'none' });
  assert.equal(p.protocol, 'anthropic');
  assert.equal(p.authHeader, 'x-api-key');
  assert.equal(p.authToken, null);
  assert.deepEqual(JSON.parse(p.extraBody), {}, 'CF_AI_GATEWAY_REASONING never reaches the Anthropic body');
  for (const backend of [BACKENDS.ollama, BACKENDS.cf]) {
    assert.equal(backendProfile(backend).protocol, 'openai');
    assert.equal(backendProfile(backend).authHeader, '');
  }
});

test('an Anthropic credential is the key in credential (an API Credential item): x-api-key, the API version, masked', async () => {
  const masked = [];
  const read = [];
  const c = await resolveCredentials(
    ITEM,
    { readSecret: async (ref) => (read.push(ref), 'sk-ant-api03-key'), mask: (v) => masked.push(v) },
    BACKENDS.anthropic,
  );
  assert.equal(c.ok, true);
  assert.deepEqual(read, [`${ITEM}/credential`]);
  assert.equal(c.authToken, 'sk-ant-api03-key');
  assert.deepEqual(c.headers, { 'x-api-key': 'sk-ant-api03-key', 'anthropic-version': '2023-06-01' });
  assert.ok(masked.includes('sk-ant-api03-key'));
  for (const value of ['', 'a,b', 'a"b']) {
    const bad = await resolveCredentials(ITEM, { readSecret: async () => value, mask: () => {} }, BACKENDS.anthropic);
    assert.equal(bad.cause, 'configuration', JSON.stringify(value));
  }
  const refused = await resolveCredentials(
    ITEM,
    { readSecret: async () => { throw Object.assign(new Error('x'), { kind: 'token' }); }, mask: () => {} },
    BACKENDS.anthropic,
  );
  assert.match(refused.detail, /OLLAMA_GATEWAY_OP_SA_TOKEN/);
});

const MESSAGE = { status: 200, body: JSON.stringify({ type: 'message', content: [{ type: 'text', text: 'OK' }] }) };
const apiError = (status, message) => ({ status, body: JSON.stringify({ type: 'error', error: { message } }) });

test('Anthropic answers: a message is ready; 401/403 credential; spent credits budget; a spend or rate limit limited; 404 model-not-found; 5xx down', () => {
  const an = (answer) => classifyProbeAnswer(answer, BACKENDS.anthropic);
  assert.equal(an(MESSAGE).kind, 'ready');
  assert.equal(an(COMPLETION).cause, 'unexpected', 'a chat completion is not a Messages answer');
  for (const status of [401, 403]) assert.equal(an({ status }).cause, 'credential', String(status));
  const spent = an(apiError(400, 'Your credit balance is too low to access the Anthropic API.'));
  assert.equal(spent.cause, 'budget');
  assert.doesNotMatch(spent.detail, /too low to access/, 'the body is never echoed');
  assert.equal(an(apiError(400, 'You have reached your specified workspace API usage limits.')).cause, 'limited');
  assert.equal(an(apiError(429, 'rate_limit_error')).cause, 'limited');
  assert.equal(an(apiError(404, 'model: claude-x')).cause, 'model-not-found');
  assert.equal(an(apiError(400, 'max_tokens: field required')).cause, 'unexpected');
  for (const status of [500, 529]) assert.equal(an({ status }).cause, 'gateway-down', String(status));
  assert.equal(an({ error: 'ENOTFOUND' }).cause, 'gateway-down');
  assert.equal(an({ status: 507 }).kind, 'fail', 'no cold-model retry');
});

test('an Anthropic probe goes to /v1/messages with the headers and is never retried', async () => {
  const clock = fakeClock();
  const gw = fakeGateway(clock, [{ status: 529 }, MESSAGE]);
  const r = await probeGateway(
    { url: 'https://api.anthropic.com', apiBase: 'https://api.anthropic.com', backend: BACKENDS.anthropic, model: 'claude-sonnet-5-5', headers: { 'x-api-key': 'k' } },
    { post: gw.post, clock },
  );
  assert.equal(r.cause, 'gateway-down');
  assert.equal(gw.requests.length, 1);
  assert.equal(gw.requests[0].url, 'https://api.anthropic.com/v1/messages');
  assert.deepEqual(gw.requests[0].headers, { 'x-api-key': 'k' });
  assert.equal(gw.requests[0].body.max_tokens, 1);
});
