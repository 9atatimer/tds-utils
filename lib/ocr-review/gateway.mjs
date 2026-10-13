// lib/ocr-review/gateway.mjs -- OCR on Demand: the review job's road to the
// model (docs/design/OCR-ON-DEMAND.DESIGN.md: Review job table, G5;
// docs/design/OLLAMA-GATEWAY.DESIGN.md: API / Interface, Credential
// contract).
//
// Three sub-components, each pure rules plus at most one flow function
// taking its ports:
//
//   configuration  the owner-scoped secret and variables, and the model
//                  (the override applies to a dispatch only);
//   credentials    the gateway's caller item read through 1Password, every
//                  value masked the moment it is read;
//   probe          a minimal chat completion, classified by the gateway's
//                  response contract; only the deadline answer is retried,
//                  for at most COLD_MODEL_LIMIT_MS.
//
// The public workflow names no hostname, vault or item: they arrive as
// variables, and no message here echoes the item reference (a public
// repo's logs are world-readable).

// --- Constants --------------------------------------------------------------

/**
 * The gateway's status codes a caller can tell apart (gateway API /
 * Interface, in evaluation order). Access's 302/403 are fixed by
 * Cloudflare. `tunnelDown` is Cloudflare's answer when the tunnel has no
 * connector (530, error 1033); `proxyDown` is the connector's 502 when
 * nothing listens on the deadline proxy's port. `ollamaDown` and `deadline`
 * are chosen by the deadline proxy (the LMDE proxy layer's route
 * ollama-gateway, routes/ollama-gateway.cfg) and MUST equal its
 * configuration: 503 is HAProxy's answer when its hold hop cannot reach
 * ollama; 507 Model Not Ready is the errorfile it serves for its own
 * server timeout (ollama-gateway.deadline.http). `deadline` is the only
 * retryable answer and is distinct from every other code here.
 */
export const GATEWAY_STATUS = Object.freeze({
  tunnelDown: 530,
  proxyDown: 502,
  ollamaDown: 503,
  deadline: 507,
});

const ACCESS_REFUSALS = new Set([302, 403]);
const GATEWAY_DOWN = new Set([GATEWAY_STATUS.tunnelDown, GATEWAY_STATUS.proxyDown, GATEWAY_STATUS.ollamaDown]);

/** How long the deadline answer is retried before the run fails cold-model (G5). */
export const COLD_MODEL_LIMIT_MS = 6 * 60 * 1000;

/** Pause between a deadline answer and the next attempt. The proxy itself
 * holds each attempt for up to its deadline, so this only spaces fast ones. */
export const RETRY_PAUSE_MS = 10 * 1000;

/** The chat-completions path, relative to the gateway base URL. */
export const COMPLETIONS_PATH = '/v1/chat/completions';

/** The credential contract's field layout (tds-internal edge record):
 * header names are fields, so a caller never hardcodes them. */
const ITEM_FIELDS = Object.freeze([
  { key: 'idHeader', field: 'access/client id header' },
  { key: 'idValue', field: 'access/client id' },
  { key: 'secretHeader', field: 'access/client secret header' },
  { key: 'secretValue', field: 'password' },
]);

/** An HTTP header name (RFC 9110 token). */
const HEADER_NAME = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
/** A value that can travel both as an HTTP header and inside ocr's
 * comma-separated K=V list: printable ASCII, no comma, no quote. */
const HEADER_VALUE = /^[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?$/;

// --- Configuration ----------------------------------------------------------

/** The model: a dispatch's non-blank override, else the configured one. */
export function resolveModel({ trigger, override, configured }) {
  const chosen = trigger === 'dispatch' && String(override ?? '').trim() ? String(override).trim() : String(configured ?? '').trim();
  return chosen || null;
}

const configurationFailure = (detail) => ({ ok: false, cause: 'configuration', detail });

/**
 * Validate the secret and variables the caller provides. Values are passed
 * in; `token` is only checked for presence. Returns { ok, url, model } or
 * { ok: false, cause: 'configuration', detail }.
 */
export function resolveGatewayConfig({ token, item, url, configuredModel, override, trigger }) {
  const missing = [];
  if (!token) missing.push('secret OLLAMA_GATEWAY_OP_SA_TOKEN');
  if (!item) missing.push('variable OLLAMA_GATEWAY_OP_ITEM');
  if (!url) missing.push('variable OLLAMA_GATEWAY_URL');
  const model = resolveModel({ trigger, override, configured: configuredModel });
  if (!model) missing.push('variable OLLAMA_GATEWAY_MODEL');
  if (missing.length > 0) return configurationFailure(`not set: ${missing.join(', ')}`);
  if (!/^op:\/\/[^/]+\/[^/]+$/.test(item)) {
    return configurationFailure('OLLAMA_GATEWAY_OP_ITEM is not an op://<vault>/<item> reference');
  }
  if (!/^https:\/\/[^/\s]+(\/[^\s]*)?$/.test(url)) return configurationFailure('OLLAMA_GATEWAY_URL is not an https:// URL');
  return { ok: true, url: url.replace(/\/+$/, ''), model };
}

// --- Credentials ------------------------------------------------------------

/** The secret references to read, one per field of the credential contract. */
export function itemReferences(item) {
  return ITEM_FIELDS.map(({ key, field }) => ({ key, field, ref: `${item}/${field}` }));
}

/** The K=V,K=V form ocr's llm_extra_headers input takes. */
export function extraHeadersValue(headers) {
  return Object.entries(headers)
    .map(([name, value]) => `${name}=${value}`)
    .join(',');
}

function headersFromFields(values) {
  for (const { key, field } of ITEM_FIELDS) {
    if (!values[key]) return configurationFailure(`the item in OLLAMA_GATEWAY_OP_ITEM has an empty field "${field}"`);
  }
  for (const key of ['idHeader', 'secretHeader']) {
    if (!HEADER_NAME.test(values[key])) {
      const { field } = ITEM_FIELDS.find((f) => f.key === key);
      return configurationFailure(`field "${field}" of the item in OLLAMA_GATEWAY_OP_ITEM is not a header name`);
    }
  }
  for (const key of ['idValue', 'secretValue']) {
    if (!HEADER_VALUE.test(values[key]) || /[,"]/.test(values[key])) {
      const { field } = ITEM_FIELDS.find((f) => f.key === key);
      return configurationFailure(`field "${field}" of the item in OLLAMA_GATEWAY_OP_ITEM cannot be sent as a header value`);
    }
  }
  return { ok: true, headers: { [values.idHeader]: values.idValue, [values.secretHeader]: values.secretValue } };
}

/**
 * Read the caller item and build its headers. `vault.readSecret(ref)`
 * resolves a value or throws an error whose `kind` is 'token' when the
 * service-account token itself was refused; `vault.mask(value)` registers a
 * value for log masking and is called before anything else happens with it.
 */
export async function resolveCredentials(item, { readSecret, mask }) {
  const values = {};
  for (const { key, field, ref } of itemReferences(item)) {
    let value;
    try {
      value = await readSecret(ref);
    } catch (error) {
      if (error?.kind === 'token') {
        return configurationFailure('1Password refused the service-account token in OLLAMA_GATEWAY_OP_SA_TOKEN');
      }
      return configurationFailure(`field "${field}" of the item in OLLAMA_GATEWAY_OP_ITEM could not be read`);
    }
    value = String(value ?? '').replace(/\r?\n$/, '');
    if (value) mask(value);
    values[key] = value;
  }
  return headersFromFields(values);
}

// --- Probe ------------------------------------------------------------------

const isCompletion = (body) => {
  try {
    const parsed = JSON.parse(body);
    return Array.isArray(parsed?.choices);
  } catch {
    return false;
  }
};

/**
 * Classify one probe answer: { status, body } from an HTTP answer, or
 * { error } when there was none (DNS, TLS, connect, timeout). Returns
 * { kind: 'ready' | 'retry' | 'fail', cause, detail }. A detail never
 * carries the response body.
 */
export function classifyProbeAnswer(answer) {
  if (answer.error !== undefined) {
    return { kind: 'fail', cause: 'gateway-down', detail: `no HTTP answer from the gateway (${answer.error})` };
  }
  const { status } = answer;
  const fail = (cause, why) => ({ kind: 'fail', cause, detail: `HTTP ${status} from the gateway: ${why}` });
  if (status >= 200 && status < 300) {
    return isCompletion(answer.body ?? '')
      ? { kind: 'ready', cause: null, detail: `HTTP ${status}: the model answered` }
      : fail('unexpected', 'a 2xx that is not a chat completion');
  }
  if (ACCESS_REFUSALS.has(status)) return fail('credential', 'refused by Access');
  if (status === GATEWAY_STATUS.deadline) {
    return { kind: 'retry', cause: null, detail: `HTTP ${status}: no first byte before the deadline` };
  }
  if (GATEWAY_DOWN.has(status)) return fail('gateway-down', 'the tunnel, the deadline proxy or the sandboxed ollama is down');
  if (status >= 400 && status < 500) return fail('model-not-found', 'the gateway does not serve the model');
  return fail('unexpected', 'an answer outside the gateway contract');
}

/** The probe request: the smallest chat completion the model can answer. */
function probeRequest({ url, model, headers }) {
  return {
    url: `${url}${COMPLETIONS_PATH}`,
    headers,
    body: { model, messages: [{ role: 'user', content: 'Reply with OK.' }], max_tokens: 1, stream: false },
  };
}

/**
 * The probe behavior (G5). `gateway.post(request)` resolves an answer as
 * classifyProbeAnswer reads it; `clock` is { now(), sleep(ms) }. Retries the
 * deadline answer until the model answers; no attempt starts once
 * COLD_MODEL_LIMIT_MS has passed since the first. Returns { ok, attempts }
 * or { ok: false, cause, detail, attempts }.
 */
export async function probeGateway(target, { post, clock }) {
  const request = probeRequest(target);
  const started = clock.now();
  let attempts = 0;
  for (;;) {
    attempts += 1;
    const verdict = classifyProbeAnswer(await post(request));
    if (verdict.kind === 'ready') return { ok: true, attempts, detail: verdict.detail };
    if (verdict.kind === 'fail') return { ok: false, cause: verdict.cause, detail: verdict.detail, attempts };
    const left = COLD_MODEL_LIMIT_MS - (clock.now() - started);
    if (left <= 0) break;
    await clock.sleep(Math.min(RETRY_PAUSE_MS, left));
    if (clock.now() - started >= COLD_MODEL_LIMIT_MS) break;
  }
  return {
    ok: false,
    cause: 'cold-model',
    detail: `the deadline answer persisted for ${COLD_MODEL_LIMIT_MS / 60000} minutes (${attempts} attempts)`,
    attempts,
  };
}
