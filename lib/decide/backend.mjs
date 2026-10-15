// lib/decide/backend.mjs -- decide: which decision backend a run talks to,
// and the exact HTTP request it sends (docs/ops/decide.md, "Setup").
//
// Two backends (the adapters behind the decision port):
//
//   cf-ai-gateway  Clef on Workers AI through Cloudflare AI Gateway, on the
//                  Cloudflare REST API: POST https://api.cloudflare.com/client
//                  /v4/accounts/<account>/ai/run/@cf/cloudflare/<model>, the
//                  run token on Authorization and the gateway named by
//                  cf-aig-gateway-id. The account and gateway come from
//                  DECIDE_GATEWAY_URL, the gateway base recorded in the
//                  token's item: https://gateway.ai.cloudflare.com/v1/
//                  <account>/<gateway>. The default.
//
//                  Not the gateway's provider-native route
//                  (<base>/workers-ai/@cf/...): with the gateway on Unified
//                  Billing it answers 401 code 10000 for every Workers AI
//                  model and every header the token could ride, while the
//                  REST route with the same token answers (Issue#512,
//                  2026-10-15). Cloudflare documents Workers AI through a
//                  gateway on the REST route only.
//   systemone      a SystemOne server (SGLang /v1/systemone, a future local
//                  decision arena): ${DECIDE_URL}/v1/systemone, no auth.
//
// Vendor names, model ids and header names live here and in bin/decide,
// never in schema.mjs or answers.mjs. Pure: the environment arrives as a
// plain object; the token is read by bin/decide and passed in.

// --- Constants --------------------------------------------------------------

/** The backends a run can use. */
export const BACKENDS = Object.freeze({ cf: 'cf-ai-gateway', systemone: 'systemone' });

/** Models the Workers AI route serves (@cf/cloudflare/<model>). */
export const CF_MODELS = Object.freeze(['clef', 'clef-flash']);

export const DEFAULT_MODEL = 'clef';
export const DEFAULT_TOOL = 'decide';
export const DEFAULT_TIMEOUT_MS = 60000;
export const DEFAULT_CONCURRENCY = 4;
export const MAX_CONCURRENCY = 16;

/** A model a SystemOne server may name. */
const SYSTEMONE_MODEL = /^[A-Za-z0-9._-]+$/;
/** The gateway's per-tool spend rule partitions on this tag. */
const TOOL_NAME = /^[a-z0-9-]{1,40}$/;
/** A 1Password secret reference to an item: op://<vault>/<item>. */
const OP_ITEM = /^op:\/\/[^/\s]+\/[^/\s]+$/;
/** A token that can travel in an HTTP header: printable ASCII, no spaces. */
const HEADER_TOKEN = /^[\x21-\x7e]+$/;
/** The gateway base's path: /v1/<account>/<gateway>, no more, no less. */
const GATEWAY_PATH = /^\/v1\/([^/\s]+)\/([^/\s]+)$/;
/** Cloudflare's API, where the AI REST route lives. */
const CF_API = 'https://api.cloudflare.com/client/v4';

// --- Pure helpers -----------------------------------------------------------

const configFailure = (message) => ({ ok: false, error: { class: 'config', message, status: null } });

const trimmed = (value) => String(value ?? '').trim();

/** A base URL without its trailing slashes. */
export const stripSlash = (url) => String(url).replace(/\/+$/, '');

function isUrl(value, { httpsOnly }) {
  const pattern = httpsOnly ? /^https:\/\/[^/\s]+(\/\S*)?$/ : /^https?:\/\/[^/\s]+(\/\S*)?$/;
  return pattern.test(value);
}

/** The account id and gateway id a gateway base names, or null: for a
 * path of another shape, and for a base the URL parser rejects (a bad
 * host or port passes isUrl's regex), which stays a config failure. */
function gatewayIds(base) {
  let pathname;
  try {
    ({ pathname } = new URL(base));
  } catch {
    return null;
  }
  const match = GATEWAY_PATH.exec(pathname);
  return match ? { accountId: match[1], gatewayId: match[2] } : null;
}

function modelProblem(backend, model) {
  if (backend === BACKENDS.cf && !CF_MODELS.includes(model)) {
    return `model "${model}" is not served on ${BACKENDS.cf}; use one of ${CF_MODELS.join(', ')}`;
  }
  if (backend === BACKENDS.systemone && !SYSTEMONE_MODEL.test(model)) return `model "${model}" does not match ${SYSTEMONE_MODEL.source}`;
  return null;
}

function parseTimeout(raw) {
  const text = trimmed(raw);
  if (text === '') return DEFAULT_TIMEOUT_MS;
  return /^[1-9][0-9]{0,8}$/.test(text) ? Number(text) : null;
}

/** The credential source for cf-ai-gateway: a literal token wins over an
 * op:// item. Returns { token } | { opItem } | a config failure. */
function credentialSource(env) {
  const token = trimmed(env.DECIDE_GATEWAY_TOKEN);
  if (token) {
    return HEADER_TOKEN.test(token) ? { token } : configFailure('DECIDE_GATEWAY_TOKEN cannot be sent as a header value');
  }
  const opItem = trimmed(env.DECIDE_GATEWAY_OP_ITEM);
  if (!opItem) return configFailure('not set: DECIDE_GATEWAY_TOKEN or DECIDE_GATEWAY_OP_ITEM (the gateway run token)');
  return OP_ITEM.test(opItem) ? { opItem } : configFailure('DECIDE_GATEWAY_OP_ITEM is not an op://<vault>/<item> reference');
}

/**
 * Resolve a run's configuration from the environment and the parsed flags
 * ({ model?, tool? }). Returns { ok: true, config } where config is
 * { backend, url, model, tool, timeoutMs, logPayload, gatewayId?, token?,
 * opItem? }, or { ok: false, error } with a config failure. `url` is the
 * full request URL.
 */
export function resolveConfig(env, flags = {}) {
  const backend = trimmed(env.DECIDE_BACKEND) || BACKENDS.cf;
  if (!Object.values(BACKENDS).includes(backend)) {
    return configFailure(`DECIDE_BACKEND "${backend}" is not one of ${Object.values(BACKENDS).join(', ')}`);
  }
  const model = trimmed(flags.model) || trimmed(env.DECIDE_MODEL) || DEFAULT_MODEL;
  const problem = modelProblem(backend, model);
  if (problem) return configFailure(problem);
  const tool = trimmed(flags.tool) || trimmed(env.DECIDE_TOOL) || DEFAULT_TOOL;
  if (!TOOL_NAME.test(tool)) return configFailure(`tool "${tool}" does not match ${TOOL_NAME.source}`);
  const timeoutMs = parseTimeout(env.DECIDE_TIMEOUT_MS);
  if (timeoutMs === null) return configFailure('DECIDE_TIMEOUT_MS is not a positive integer of milliseconds');
  const logPayload = trimmed(env.DECIDE_LOG_PAYLOAD) === '1';
  const common = { backend, model, tool, timeoutMs, logPayload };

  if (backend === BACKENDS.systemone) {
    const base = trimmed(env.DECIDE_URL);
    if (!base) return configFailure('not set: DECIDE_URL (the SystemOne server base URL)');
    if (!isUrl(base, { httpsOnly: false })) return configFailure('DECIDE_URL is not an http(s):// URL');
    return { ok: true, config: { ...common, url: `${stripSlash(base)}/v1/systemone` } };
  }

  const base = trimmed(env.DECIDE_GATEWAY_URL);
  if (!base) return configFailure('not set: DECIDE_GATEWAY_URL (the AI Gateway base URL)');
  if (!isUrl(base, { httpsOnly: true })) return configFailure('DECIDE_GATEWAY_URL is not an https:// URL');
  const ids = gatewayIds(stripSlash(base));
  if (!ids) return configFailure('DECIDE_GATEWAY_URL is not a gateway base of the form https://<host>/v1/<account>/<gateway>');
  const source = credentialSource(env);
  if (source.ok === false) return source;
  const url = `${CF_API}/accounts/${ids.accountId}/ai/run/@cf/cloudflare/${model}`;
  return { ok: true, config: { ...common, url, gatewayId: ids.gatewayId, ...source } };
}

/** The 1Password CLI argv that reads the run token from an item. */
export const opReadArgv = (opItem) => ['read', `${opItem}/password`];

/** Check a token read from 1Password: trailing newline stripped, header-safe.
 * Returns { ok: true, token } or a config failure. */
export function acceptToken(raw) {
  const token = String(raw ?? '').replace(/\r?\n$/, '').trim();
  if (!token) return configFailure('the password field of DECIDE_GATEWAY_OP_ITEM is empty');
  if (!HEADER_TOKEN.test(token)) return configFailure('the password field of DECIDE_GATEWAY_OP_ITEM cannot be sent as a header value');
  return { ok: true, token };
}

/**
 * The request headers. On cf-ai-gateway the token rides Authorization (the
 * REST route checks it against Workers AI Read, so an AI Gateway-only token
 * gets 401 code 10000), and cf-aig-gateway-id routes the request through the
 * gateway, where the spend rules and the log apply. Every request stamps the
 * tool for the per-tool spend rule, and keeps the payload (often private
 * prose) out of the gateway's logs unless DECIDE_LOG_PAYLOAD=1.
 */
export function buildHeaders(config, token) {
  const headers = { 'content-type': 'application/json' };
  if (config.backend !== BACKENDS.cf) return headers;
  headers.authorization = `Bearer ${token}`;
  headers['cf-aig-gateway-id'] = config.gatewayId;
  headers['cf-aig-metadata'] = JSON.stringify({ tool: config.tool });
  if (!config.logPayload) headers['cf-aig-collect-log-payload'] = 'false';
  return headers;
}

/** The request body: the model, then the validated request (never the id). */
export function buildBody(config, request) {
  const body = { model: config.model, state: request.state, questions: request.questions };
  if (request.images !== undefined) body.images = request.images;
  return body;
}

/** The full HTTP request: { url, headers, body } (body as a string). */
export function buildRequest(config, token, request) {
  return { url: config.url, headers: buildHeaders(config, token), body: JSON.stringify(buildBody(config, request)) };
}
