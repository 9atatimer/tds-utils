// test/decide_backend.test.mjs -- decide: backend resolution from the
// environment, URL and header construction, the request body
// (lib/decide/backend.mjs). Values only; no fakes, no network.
// Run: node --test test/decide_backend.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BACKENDS, acceptToken, buildBody, buildHeaders, buildRequest, opReadArgv, resolveConfig } from '../lib/decide/backend.mjs';

const BASE = 'https://gateway.example/v1/acct/gw';
/** The REST route the base resolves to: Cloudflare's API, the base's account, the model. */
const REST = 'https://api.cloudflare.com/client/v4/accounts/acct/ai/run/@cf/cloudflare';
const TOKEN = 'run-token-abc123';
const cfEnv = (over) => ({ DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_TOKEN: TOKEN, ...over });
const configOf = (env, flags) => {
  const resolved = resolveConfig(env, flags);
  assert.equal(resolved.ok, true, JSON.stringify(resolved));
  return resolved.config;
};
const configError = (env, flags) => {
  const resolved = resolveConfig(env, flags);
  assert.equal(resolved.ok, false);
  assert.equal(resolved.error.class, 'config');
  return resolved.error.message;
};

// --- Backend and URL ---------------------------------------------------------

test('cf-ai-gateway is the default backend and the URL is the REST route for the model, on the account named by the gateway base', () => {
  const config = configOf(cfEnv());
  assert.equal(config.backend, BACKENDS.cf);
  assert.equal(config.model, 'clef');
  assert.equal(config.url, `${REST}/clef`);
  assert.equal(config.gatewayId, 'gw');
});

test('a trailing slash on the gateway base is stripped', () => {
  assert.equal(configOf(cfEnv({ DECIDE_GATEWAY_URL: `${BASE}//` })).url, `${REST}/clef`);
});

test('a gateway base whose path is not /v1/<account>/<gateway> is a config failure naming that shape', () => {
  for (const base of ['https://gateway.example', 'https://gateway.example/v1/acct', 'https://gateway.example/v1/acct/gw/extra', 'https://gateway.example/v2/acct/gw']) {
    assert.match(configError(cfEnv({ DECIDE_GATEWAY_URL: base })), /\/v1\/<account>\/<gateway>/);
  }
});

test('systemone posts to ${DECIDE_URL}/v1/systemone and needs no token', () => {
  const config = configOf({ DECIDE_BACKEND: 'systemone', DECIDE_URL: 'http://127.0.0.1:30000/' });
  assert.equal(config.url, 'http://127.0.0.1:30000/v1/systemone');
  assert.equal(config.token, undefined);
  assert.equal(config.opItem, undefined);
});

test('an unknown backend, or a missing or non-URL base, is a config failure', () => {
  assert.match(configError({ DECIDE_BACKEND: 'ollama' }), /DECIDE_BACKEND "ollama"/);
  assert.match(configError({ DECIDE_GATEWAY_TOKEN: TOKEN }), /not set: DECIDE_GATEWAY_URL/);
  assert.match(configError(cfEnv({ DECIDE_GATEWAY_URL: 'http://gateway.example' })), /not an https/);
  assert.match(configError({ DECIDE_BACKEND: 'systemone' }), /not set: DECIDE_URL/);
  assert.match(configError({ DECIDE_BACKEND: 'systemone', DECIDE_URL: 'localhost:30000' }), /not an http/);
});

// --- Model -------------------------------------------------------------------

test('the model comes from --model, else DECIDE_MODEL, else clef', () => {
  assert.equal(configOf(cfEnv({ DECIDE_MODEL: 'clef-flash' })).model, 'clef-flash');
  assert.equal(configOf(cfEnv({ DECIDE_MODEL: 'clef-flash' }), { model: 'clef' }).model, 'clef');
  assert.equal(configOf(cfEnv({ DECIDE_MODEL: 'clef-flash' })).url, `${REST}/clef-flash`);
});

test('cf-ai-gateway serves clef and clef-flash only; systemone takes any plain model name', () => {
  assert.match(configError(cfEnv(), { model: 'llama' }), /not served on cf-ai-gateway/);
  assert.equal(configOf({ DECIDE_BACKEND: 'systemone', DECIDE_URL: 'http://h' }, { model: 'jev-1.2_b' }).model, 'jev-1.2_b');
  assert.match(configError({ DECIDE_BACKEND: 'systemone', DECIDE_URL: 'http://h' }, { model: 'org/model' }), /does not match/);
});

// --- Credentials -------------------------------------------------------------

test('DECIDE_GATEWAY_TOKEN wins over DECIDE_GATEWAY_OP_ITEM', () => {
  const config = configOf(cfEnv({ DECIDE_GATEWAY_OP_ITEM: 'op://v/i' }));
  assert.equal(config.token, TOKEN);
  assert.equal(config.opItem, undefined);
});

test('with no token, the op:// item is the source', () => {
  const config = configOf({ DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'op://vault/item' });
  assert.equal(config.opItem, 'op://vault/item');
  assert.deepEqual(opReadArgv(config.opItem), ['read', 'op://vault/item/password']);
});

test('neither credential, or a malformed one, is a config failure', () => {
  assert.match(configError({ DECIDE_GATEWAY_URL: BASE }), /DECIDE_GATEWAY_TOKEN or DECIDE_GATEWAY_OP_ITEM/);
  assert.match(configError({ DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'vault/item' }), /op:\/\/<vault>\/<item>/);
  assert.match(configError({ DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'op://vault/item/password' }), /op:\/\/<vault>\/<item>/);
  assert.match(configError(cfEnv({ DECIDE_GATEWAY_TOKEN: 'two words' })), /cannot be sent as a header/);
});

test('a token read from 1Password loses its trailing newline; an empty one is refused', () => {
  assert.deepEqual(acceptToken(`${TOKEN}\n`), { ok: true, token: TOKEN });
  assert.equal(acceptToken('\n').ok, false);
  assert.equal(acceptToken('a b').ok, false);
});

// --- Tool, timeout, payload logging ------------------------------------------

test('the tool comes from --tool, else DECIDE_TOOL, else decide, and must match ^[a-z0-9-]{1,40}$', () => {
  assert.equal(configOf(cfEnv()).tool, 'decide');
  assert.equal(configOf(cfEnv({ DECIDE_TOOL: 'ocrinator' })).tool, 'ocrinator');
  assert.equal(configOf(cfEnv({ DECIDE_TOOL: 'ocrinator' }), { tool: 'triage-bot' }).tool, 'triage-bot');
  assert.equal(configOf(cfEnv(), { tool: 'a'.repeat(40) }).tool, 'a'.repeat(40));
  assert.match(configError(cfEnv(), { tool: 'a'.repeat(41) }), /does not match/);
  assert.match(configError(cfEnv(), { tool: 'Upper' }), /does not match/);
  assert.match(configError(cfEnv(), { tool: 'a"b' }), /does not match/);
});

test('DECIDE_TIMEOUT_MS defaults to 60000 and must be a positive integer', () => {
  assert.equal(configOf(cfEnv()).timeoutMs, 60000);
  assert.equal(configOf(cfEnv({ DECIDE_TIMEOUT_MS: '1500' })).timeoutMs, 1500);
  for (const bad of ['0', '-5', '1.5', 'soon']) assert.match(configError(cfEnv({ DECIDE_TIMEOUT_MS: bad })), /DECIDE_TIMEOUT_MS/);
});

// --- Headers and body --------------------------------------------------------

test('cf-ai-gateway headers carry the token on Authorization, the gateway id, the tool tag, and no payload logging', () => {
  assert.deepEqual(buildHeaders(configOf(cfEnv()), TOKEN), {
    'content-type': 'application/json',
    authorization: `Bearer ${TOKEN}`,
    'cf-aig-gateway-id': 'gw',
    'cf-aig-metadata': '{"tool":"decide"}',
    'cf-aig-collect-log-payload': 'false',
  });
});

test('the tool flag reaches cf-aig-metadata', () => {
  const headers = buildHeaders(configOf(cfEnv(), { tool: 'ocrinator' }), TOKEN);
  assert.deepEqual(JSON.parse(headers['cf-aig-metadata']), { tool: 'ocrinator' });
});

test('DECIDE_LOG_PAYLOAD=1 drops the no-payload header; any other value keeps it', () => {
  assert.equal('cf-aig-collect-log-payload' in buildHeaders(configOf(cfEnv({ DECIDE_LOG_PAYLOAD: '1' })), TOKEN), false);
  assert.equal(buildHeaders(configOf(cfEnv({ DECIDE_LOG_PAYLOAD: 'yes' })), TOKEN)['cf-aig-collect-log-payload'], 'false');
});

test('systemone sends no auth headers', () => {
  const config = configOf({ DECIDE_BACKEND: 'systemone', DECIDE_URL: 'http://h' });
  assert.deepEqual(buildHeaders(config, null), { 'content-type': 'application/json' });
});

test('the body is the model plus state, questions and images, never the id', () => {
  const config = configOf(cfEnv({ DECIDE_MODEL: 'clef-flash' }));
  const questions = { q: { type: 'noul', instructions: 'x' } };
  assert.deepEqual(buildBody(config, { state: 's', questions }), { model: 'clef-flash', state: 's', questions });
  assert.deepEqual(buildBody(config, { state: 's', questions, images: ['b64'] }), { model: 'clef-flash', state: 's', questions, images: ['b64'] });
  const request = buildRequest(config, TOKEN, { state: 's', questions });
  assert.equal(request.url, `${REST}/clef-flash`);
  assert.deepEqual(JSON.parse(request.body), { model: 'clef-flash', state: 's', questions });
});
