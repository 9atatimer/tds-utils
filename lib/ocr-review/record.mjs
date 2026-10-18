// lib/ocr-review/record.mjs -- OCR on Demand: how a run ended, its run
// record, and this workflow's summary comment
// (docs/design/OCR-ON-DEMAND.DESIGN.md: State Machine, Data Model, Report
// job). The pinned upstream action posts its own sticky summary too, which
// cannot be turned off and names each finding that failed to post; ours
// carries the run's outcome and cause and links to it (Key Decisions,
// summary comment owner: owner ruling "option A").
//
// The report job owns this: it runs after authorize and review whatever
// their outcome, references no secret, and writes the record BEFORE the
// comment so a failed post cannot lose it. Everything here is pure; the
// report job's I/O (job summary, artifact, the comment) is bin/ocr-review.
//
// The cause set is closed. A step that fails says why by declaring one of
// its causes; a failure nobody declared -- a setup step, a job timeout, an
// undocumented probe answer -- is `unexpected` and names the job and step,
// so no non-skipped run ends causeless (Key Decisions, closed cause set).

// --- Constants --------------------------------------------------------------

/** Schema version of the run record; bump on any field change (Data Model). */
export const RECORD_VERSION = 2;

/** Every cause the State Machine names: the closed set. */
export const CAUSES = Object.freeze([
  'pr-not-open',
  'fork',
  'configuration',
  'credential',
  'gateway-down',
  'model-not-found',
  'cold-model',
  'budget',
  'limited',
  'runner-tool-missing',
  'unexpected',
  'engine-error',
  'reviewed-nothing',
  'nothing-reviewable',
  'cancelled',
]);

/** Causes the authorize job ends a run with. */
const AUTHORIZE_CAUSES = new Set(['pr-not-open', 'fork']);

/** Causes a review-job step may declare when it fails. `unexpected` is not
 * one: it is assigned here, with the failing step named. */
const STEP_FAILURE_CAUSES = new Set([
  'runner-tool-missing',
  'configuration',
  'credential',
  'gateway-down',
  'model-not-found',
  'cold-model',
  'budget',
  'limited',
  'engine-error',
  'reviewed-nothing',
]);

/** Causes a successful run may carry (besides null). */
const SUCCESS_CAUSES = new Set(['nothing-reviewable']);

/** Causes with which the run reached JUDGED, so its counts are known. */
const JUDGED_CAUSES = new Set([null, 'nothing-reviewable', 'reviewed-nothing']);

/** The first line of every summary comment this workflow posts. */
export const SUMMARY_MARKER = '<!-- ocr-review-summary -->';

/** The line that opens a review mark: the summary posted as a review on
 * the head it reviewed, which review-settled counts as the `ocr`
 * reviewer (lib/review-settled.mjs). Keep the two in step. */
const markLine = (sha) => `<!-- ocr-review-mark sha=${sha} -->`;

const NO_FAILED_STEP = '(no step failed: job timeout or runner lost)';

/** What each failure means, and where to look next. */
const CAUSE_TEXT = {
  'pr-not-open': 'the pull request does not exist, is closed, or is an issue.',
  fork: 'the head branch is in another repository; reviewing it would run with this repository\'s secret.',
  configuration: 'the gateway secret or a gateway variable is missing or unreadable. Run `bin/seed-ocr-review status` in tds-utils.',
  credential: 'the gateway refused the credential (the Ollama Gateway: Access 302/403; Cloudflare AI Gateway: 401/403; the Anthropic API: 401/403, a revoked or wrong key). Check the item the service account reads.',
  'gateway-down':
    'the gateway did not answer. The Ollama Gateway: the laptop, its tunnel, the deadline proxy or the sandboxed ollama is down. Cloudflare AI Gateway: it or its upstream provider failed (5xx). The Anthropic API: it failed or is overloaded (5xx, 529).',
  budget:
    'refused for money. Cloudflare AI Gateway: the prepaid credit balance is exhausted (402); add credits (auto top-up is off by design). The Anthropic API: the Console organization\'s credit balance is spent (the monthly API credits refresh each billing cycle); buy credits or wait.',
  limited:
    "Cloudflare AI Gateway refused with 429: either a spend limit (the gateway's total or OCR's per-tool cap) or the unified-billing request rate (200 requests a minute). The gateway's dashboard says which; a rate limit clears in a minute, a spend limit at the end of its window (tds-internal ops/terraform/ai-gateway). The Anthropic API: the key's workspace spend limit, the organization's monthly spend cap, or a rate limit; the Claude Console's limits page says which.",
  'model-not-found': 'the gateway does not serve the configured model.',
  'cold-model': 'the model did not answer within 6 minutes of retries; it may still be loading. Re-run.',
  'runner-tool-missing':
    'the runner lacks a host tool the review job needs (named in the detail): git always, and gpg and unzip when the 1Password CLI is not on the runner and must be installed. Add it to the runner image.',
  unexpected: 'a step failed in a way no other cause covers.',
  'engine-error': "ocr failed, its result lacked the resolved range or the per-file reviewed list, or the action's post counts were missing, unparseable or inconsistent with ocr's findings.",
  'reviewed-nothing': 'there were reviewable files and ocr reviewed none of them.',
  cancelled: 'the run was cancelled.',
};

// --- Predicates -------------------------------------------------------------

/** True when the run reached JUDGED, so its file and finding counts exist. */
export function isJudged(end) {
  if (!end || end.outcome === 'cancelled') return false;
  return JUDGED_CAUSES.has(end.cause ?? null) && (end.outcome === 'success' || end.cause === 'reviewed-nothing');
}

/**
 * The head a run's summary marks as reviewed, or null. A mark says OCR
 * finished a whole review of that commit: the run succeeded, every
 * reviewable file was reviewed, and every finding reached the PR (an
 * unposted finding has no thread to resolve, so a mark would hide it).
 * Nothing reviewable is a whole review too. Findings do not withhold the
 * mark; their threads do, until each is resolved.
 */
export function markSha(record) {
  if (record.outcome !== 'success' || !record.head_sha) return null;
  if (record.cause === 'nothing-reviewable') return record.head_sha;
  if (record.cause !== null) return null;
  const whole = record.files_reviewable !== null && record.files_reviewed === record.files_reviewable && record.findings_failed === 0;
  return whole ? record.head_sha : null;
}

/** Every terminal state comments except pr-not-open (there may be no PR). */
export function shouldComment(record) {
  return record.cause !== 'pr-not-open';
}

// --- Pure helpers: how the run ended ----------------------------------------

/** The end of a job that did not succeed, read from its steps. */
function jobFailure(jobName, job) {
  const failed = (job.steps ?? []).find((step) => step.outcome === 'failure');
  if (!failed) return { outcome: 'failure', cause: 'unexpected', failingStep: `${jobName} / ${NO_FAILED_STEP}` };
  if (STEP_FAILURE_CAUSES.has(failed.cause)) return { outcome: 'failure', cause: failed.cause, failingStep: null };
  return { outcome: 'failure', cause: 'unexpected', failingStep: `${jobName} / ${failed.name}` };
}

/**
 * The State Machine's terminal state for a run that was not skipped.
 * `authorize` and `review` are { result, decision?, cause?, steps: [{ name,
 * outcome, cause }] } in declaration order; `runCancelled` is the
 * workflow's own cancellation. Returns { outcome, cause, failingStep }.
 */
export function endOfRun({ runCancelled, authorize, review }) {
  if (runCancelled) return { outcome: 'cancelled', cause: 'cancelled', failingStep: null };
  if (authorize.decision === 'fail' && AUTHORIZE_CAUSES.has(authorize.cause)) {
    return { outcome: 'failure', cause: authorize.cause, failingStep: null };
  }
  if (authorize.decision !== 'approve' || authorize.result !== 'success') return jobFailure('authorize', authorize);
  if (review.result !== 'success') return jobFailure('review', review);
  const declared = (review.steps ?? []).map((step) => step.cause).find((cause) => SUCCESS_CAUSES.has(cause));
  return { outcome: 'success', cause: declared ?? null, failingStep: null };
}

// --- Pure helpers: the run record -------------------------------------------

const rangeText = (range) => (range ? `${range.base}..${range.head}` : null);
const countOrNull = (value) => (Number.isInteger(value) && value >= 0 ? value : null);

/**
 * The run record (Data Model). `approved` says the run got past AUTHORIZED;
 * `range` is the range ocr resolved (null until REVIEWING resolved it);
 * `judged` is the verdict's counts, used only when the run reached JUDGED.
 */
export function buildRecord({ repo, pr, trigger, model, backend, ocrVersion, approved, end, range, judged, startedAt, finishedAt }) {
  const resolved = range ?? judged?.range ?? null;
  const counted = isJudged(end) && judged ? judged : null;
  return {
    record_version: RECORD_VERSION,
    repo,
    pr,
    trigger,
    head_sha: resolved ? resolved.head : null,
    range: rangeText(resolved),
    model: approved ? (model ?? null) : null,
    backend: approved ? (backend ?? null) : null,
    ocr_version: approved ? (ocrVersion ?? null) : null,
    outcome: end.outcome,
    cause: end.cause ?? null,
    failing_step: end.cause === 'unexpected' ? end.failingStep : null,
    files_reviewable: countOrNull(counted?.filesReviewable),
    files_reviewed: countOrNull(counted?.filesReviewed),
    findings_posted: countOrNull(counted?.findingsPosted),
    findings_failed: countOrNull(counted?.findingsFailed),
    started_at: startedAt,
    finished_at: finishedAt,
  };
}

// --- Pure helpers: the summary comment --------------------------------------

/** HTML-escape, including the characters Markdown and GitHub act on. */
function escapeText(text) {
  return String(text ?? '').replace(/[&<>"'`@]/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

const code = (text) => `<code>${escapeText(text)}</code>`;
const short = (sha) => String(sha ?? '').slice(0, 7);

/** The URL itself when it is a plain https URL safe inside a Markdown link
 * target, else null. It comes from the action's summary_comment_url. */
function linkableUrl(url) {
  return typeof url === 'string' && /^https:\/\/[A-Za-z0-9.-]+\/[A-Za-z0-9._~\/#?=&%+-]*$/.test(url) ? url : null;
}

/** The line pointing at upstream's summary comment, if the action posted one. */
function upstreamLine(upstreamSummaryUrl) {
  const url = linkableUrl(upstreamSummaryUrl);
  if (!url) return [];
  return [`Findings that failed to post are named in upstream's own summary comment: [upstream summary](${url}).`];
}

function headline(record) {
  if (record.outcome === 'cancelled') return 'OCR review cancelled';
  if (record.outcome === 'failure') return `OCR review failed: ${record.cause}`;
  if (record.cause === 'nothing-reviewable') return 'OCR review: no reviewable files';
  return 'OCR review complete';
}

function successBody(record, judged, upstreamSummaryUrl) {
  const lines = [];
  const range = record.range ? `${short(record.range.split('..')[0])}..${short(record.head_sha)}` : 'unknown range';
  if (record.cause === 'nothing-reviewable') {
    lines.push(`There were no reviewable files in ${code(range)}, so there was nothing to review.`);
    return lines;
  }
  lines.push(
    `Reviewed ${record.files_reviewed} of ${record.files_reviewable} reviewable files in ${code(range)}.`,
    `Findings posted: ${record.findings_posted}; failed to post: ${record.findings_failed}.`,
  );
  if (record.findings_failed > 0 && !linkableUrl(upstreamSummaryUrl)) {
    lines.push('', 'The action reported no summary comment URL, so the findings that failed to post, which it names there, could not be linked.');
  }
  const unreviewed = judged?.unreviewed ?? [];
  if (unreviewed.length > 0) {
    lines.push('', `**Reviewable files ocr did not review (${unreviewed.length}):**`, '');
    for (const path of unreviewed) lines.push(`- ${code(path)}`);
  }
  return lines;
}

function failureBody(record, detail) {
  const lines = [`Cause ${code(record.cause)}: ${CAUSE_TEXT[record.cause] ?? CAUSE_TEXT.unexpected}`];
  if (record.failing_step) lines.push('', `Failing step: ${code(record.failing_step)}.`);
  if (detail) lines.push('', `Detail: ${escapeText(detail)}`);
  return lines;
}

/**
 * This workflow's summary comment for a run (State Machine table).
 * `judged` carries the unreviewed files; `detail` is the failing step's own
 * one-line explanation; `upstreamSummaryUrl` is the action's
 * summary_comment_url, linked on any outcome when present.
 */
export function renderSummary(record, { runUrl, judged, detail, upstreamSummaryUrl } = {}) {
  const body = record.outcome === 'success' ? successBody(record, judged, upstreamSummaryUrl) : failureBody(record, detail);
  const sha = markSha(record);
  if (record.outcome === 'success' && sha === null) {
    body.push('', 'This summary is not a review mark: it settles no review. Re-run `/ocr` for a whole review of the head.');
  }
  const upstream = upstreamLine(upstreamSummaryUrl);
  const footer = [
    `model ${record.model ? code(record.model) : 'unresolved'}`,
    `backend ${record.backend ? code(record.backend) : 'unresolved'}`,
    `ocr ${record.ocr_version ? code(record.ocr_version) : 'unresolved'}`,
    `record v${record.record_version}`,
    `[run](${runUrl})`,
  ].join(' | ');
  return [...(sha === null ? [] : [markLine(sha)]), SUMMARY_MARKER, `### ${headline(record)}`, '', ...body, ...(upstream.length > 0 ? ['', ...upstream] : []), '', `<sub>${footer}</sub>`, ''].join('\n');
}
