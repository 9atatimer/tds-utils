// lib/decide/failure.mjs -- decide: the failure classes a decision can end
// in, their exit codes, and how an HTTP answer or a transport error maps
// onto them (docs/ops/decide.md, "Failure classes").
//
// Pure: values in, values out. The callers (bin/decide) own the I/O.

// --- Constants --------------------------------------------------------------

/** Failure class -> process exit code. The CLI contract; never renumber. */
export const EXIT_CODES = Object.freeze({
  config: 2,
  rejected: 3,
  unavailable: 4,
  auth: 5,
  malformed: 6,
});

/** The classes, as names, for callers that must not spell them twice. */
export const FAILURE = Object.freeze({
  config: 'config',
  rejected: 'rejected',
  unavailable: 'unavailable',
  auth: 'auth',
  malformed: 'malformed',
});

/** HTTP statuses that mean the input itself was refused. */
const REJECTED_STATUSES = new Set([400, 413, 422]);
/** HTTP statuses that mean the credential was refused. */
const AUTH_STATUSES = new Set([401, 403]);
/** The answers worth one retry: the gateway or upstream hiccuped. */
const RETRYABLE_STATUSES = new Set([502, 503, 504]);

/** How much of a vendor error message a failure may carry. */
const VENDOR_MESSAGE_LIMIT = 200;

// --- Predicates -------------------------------------------------------------

/** A 2xx answer: the body is the decision (or a malformed one). */
export const isSuccessStatus = (status) => Number.isInteger(status) && status >= 200 && status < 300;

/** One retry is allowed after a network error or a 502/503/504. A timeout
 * is not retried: it already spent the whole request budget. */
export function shouldRetry(attempt) {
  if (attempt.error) return attempt.error.kind === 'network';
  return RETRYABLE_STATUSES.has(attempt.status);
}

// --- Pure helpers -----------------------------------------------------------

/** A failure value: { class, message, status }. */
export function failure(cls, message, status = null) {
  return { class: cls, message, status };
}

/** The exit code for a failure class; 1 for anything outside the contract. */
export const exitCodeFor = (cls) => EXIT_CODES[cls] ?? 1;

/** Replace every occurrence of `secret` in `text` with [redacted]. */
export function redact(text, secret) {
  const value = String(text ?? '');
  if (!secret) return value;
  return value.split(secret).join('[redacted]');
}

/** The first human-readable error message in a vendor error body, if any:
 * Workers AI's { errors: [{ message }] }, or { error: "..." | { message } }. */
export function vendorMessage(body) {
  if (!body || typeof body !== 'object') return '';
  const first = Array.isArray(body.errors) ? body.errors.find((e) => e && typeof e.message === 'string') : null;
  const raw = first?.message ?? (typeof body.error === 'string' ? body.error : body.error?.message) ?? '';
  const text = String(raw).replace(/\s+/g, ' ').trim();
  return text.length > VENDOR_MESSAGE_LIMIT ? `${text.slice(0, VENDOR_MESSAGE_LIMIT)}...` : text;
}

/**
 * Classify a non-2xx HTTP answer. `body` is the parsed JSON body or null.
 * Returns a failure value carrying the status.
 */
export function classifyHttpFailure(status, body = null) {
  const said = vendorMessage(body);
  const suffix = said ? `: ${said}` : '';
  if (REJECTED_STATUSES.has(status)) return failure(FAILURE.rejected, `the backend rejected the request (HTTP ${status})${suffix}`, status);
  if (AUTH_STATUSES.has(status)) return failure(FAILURE.auth, `the backend refused the credential (HTTP ${status})${suffix}`, status);
  if (status === 429) return failure(FAILURE.unavailable, `spend limit or rate limit (HTTP 429)${suffix}`, status);
  if (status === 402) return failure(FAILURE.unavailable, `the account's credit is exhausted (HTTP 402)${suffix}`, status);
  if (status === 404) return failure(FAILURE.config, `the backend has no such endpoint or model (HTTP 404); check the URL and --model${suffix}`, status);
  if (status >= 500 && status <= 599) return failure(FAILURE.unavailable, `the backend failed (HTTP ${status})${suffix}`, status);
  if (status >= 400 && status <= 499) return failure(FAILURE.rejected, `the backend refused the request (HTTP ${status})${suffix}`, status);
  return failure(FAILURE.malformed, `unexpected HTTP status ${status} from the backend`, status);
}

/** Classify a request that got no HTTP answer: { kind: 'timeout' | 'network', message }. */
export function classifyTransportError(error, timeoutMs) {
  if (error.kind === 'timeout') return failure(FAILURE.unavailable, `no answer within ${timeoutMs} ms (DECIDE_TIMEOUT_MS)`);
  return failure(FAILURE.unavailable, `network error: ${error.message}`);
}
