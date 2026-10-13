// test/ocr_review_io.test.mjs -- OCR on Demand, the I/O layer the workflow
// steps call (bin/ocr-review): GitHub REST, the 1Password CLI, the gateway,
// git, step outputs, the job summary. Every adapter is a fake passed in; no
// network, no subprocess, no filesystem.
// Run: node --test test/ocr_review_io.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  REVIEW_STEPS,
  runAuthorize,
  runComment,
  runCredentials,
  runHostTools,
  runProbe,
  runReport,
  runVerdict,
} from '../bin/ocr-review';

const HEAD = 'c'.repeat(40);
const BASE = 'b'.repeat(40);

/** Step I/O: the log lines, the outputs, the files written. */
function fakeStep() {
  const events = [];
  return {
    events,
    outputs: {},
    files: {},
    log: (line) => events.push(['log', line]),
    setOutput(name, value) {
      events.push(['output', name, value]);
      this.outputs[name] = value;
    },
    writeFile(path, text) {
      events.push(['file', path]);
      this.files[path] = text;
    },
  };
}

/** A fetch that answers from a handler and records each call. */
function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init = {}) => {
    calls.push({ url: String(url), init, body: init.body ? JSON.parse(init.body) : undefined });
    return handler(String(url), init);
  };
  fn.calls = calls;
  return fn;
}

const json = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body, text: async () => JSON.stringify(body) });
const text = (status, body) => ({ status, ok: status >= 200 && status < 300, text: async () => body });

const PR_BODY = {
  state: 'open',
  head: { sha: HEAD, repo: { full_name: 'o/r' } },
  base: { ref: 'main', repo: { full_name: 'o/r' } },
};

// --- authorize ---------------------------------------------------------------

const authorizeEnv = (over) => ({
  GITHUB_TOKEN: 't',
  REPO: 'o/r',
  EVENT_NAME: 'issue_comment',
  COMMENT_BODY: '/ocr',
  AUTHOR_ASSOCIATION: 'MEMBER',
  PR: '7',
  ...over,
});

test('authorize approves an open same-repo PR and outputs its head, base and trigger', async () => {
  const step = fakeStep();
  const fetch = fakeFetch(() => json(200, PR_BODY));
  const code = await runAuthorize({ env: authorizeEnv(), fetch, step, now: () => '2026-10-12T10:00:00Z' });
  assert.equal(code, 0);
  assert.equal(fetch.calls[0].url, 'https://api.github.com/repos/o/r/pulls/7');
  assert.equal(fetch.calls[0].init.headers.authorization, 'Bearer t');
  assert.equal(step.outputs.decision, 'approve');
  assert.equal(step.outputs.trigger, 'comment');
  assert.equal(step.outputs.head_sha, HEAD);
  assert.equal(step.outputs.base_ref, 'main');
  assert.equal(step.outputs.started_at, '2026-10-12T10:00:00Z');
});

test('authorize skips a non-/ocr comment without a single API call, and exits 0', async () => {
  const step = fakeStep();
  const fetch = fakeFetch(() => json(200, PR_BODY));
  const code = await runAuthorize({ env: authorizeEnv({ COMMENT_BODY: 'nice' }), fetch, step, now: () => 'x' });
  assert.equal(code, 0);
  assert.equal(step.outputs.decision, 'skip');
  assert.equal(fetch.calls.length, 0);
});

test('authorize: a 404 (no PR, or an issue) fails pr-not-open with exit 1', async () => {
  const step = fakeStep();
  const code = await runAuthorize({ env: authorizeEnv(), fetch: fakeFetch(() => json(404, {})), step, now: () => 'x' });
  assert.equal(code, 1);
  assert.equal(step.outputs.decision, 'fail');
  assert.equal(step.outputs.cause, 'pr-not-open');
});

test('authorize: a fork head fails fork; a dispatch reads trigger dispatch', async () => {
  const step = fakeStep();
  const body = { ...PR_BODY, head: { sha: HEAD, repo: { full_name: 'x/r' } } };
  const code = await runAuthorize({ env: authorizeEnv({ EVENT_NAME: 'workflow_dispatch' }), fetch: fakeFetch(() => json(200, body)), step, now: () => 'x' });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'fork');
  assert.equal(step.outputs.trigger, 'dispatch');
});

test('authorize: any other API failure throws (the job fails; report calls it unexpected)', async () => {
  await assert.rejects(runAuthorize({ env: authorizeEnv(), fetch: fakeFetch(() => json(500, {})), step: fakeStep(), now: () => 'x' }), /HTTP 500/);
});

// --- host tools ----------------------------------------------------------------

/** A fake PATH lookup: the tools the runner has; records each question. */
function fakeOnPath(...tools) {
  const asked = [];
  const onPath = (tool) => {
    asked.push(tool);
    return tools.includes(tool);
  };
  onPath.asked = asked;
  return onPath;
}

test('host tools: on the pool image (op baked in) the check passes and says not to install op', async () => {
  const step = fakeStep();
  const onPath = fakeOnPath('git', 'unzip', 'gpg', 'op');
  const code = await runHostTools({ env: {}, onPath, step });
  assert.equal(code, 0);
  assert.deepEqual([...onPath.asked].sort(), ['git', 'gpg', 'op', 'unzip']);
  assert.equal(step.outputs.install_op, 'false');
  assert.equal(step.outputs.cause ?? '', '');
  assert.ok(step.events.some((e) => e[0] === 'log' && e[1].includes('git present, unzip present, gpg present, op present')));
});

test('host tools: on a GitHub-hosted runner (no op) the check passes and says to install op', async () => {
  const step = fakeStep();
  const code = await runHostTools({ env: {}, onPath: fakeOnPath('git', 'unzip', 'gpg'), step });
  assert.equal(code, 0);
  assert.equal(step.outputs.install_op, 'true');
});

test('host tools: no op and no gpg fails runner-tool-missing with detail gpg, exit 1', async () => {
  const step = fakeStep();
  const code = await runHostTools({ env: {}, onPath: fakeOnPath('git', 'unzip'), step });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'runner-tool-missing');
  assert.equal(step.outputs.detail, 'gpg');
  assert.ok(step.events.some((e) => e[0] === 'log' && /^::error::runner-tool-missing: gpg/.test(e[1])));
});

// --- credentials ---------------------------------------------------------------

const ITEM = 'op://vault-uuid/item-title';
const credEnv = (over) => ({
  OP_SERVICE_ACCOUNT_TOKEN: 'ops_token',
  OLLAMA_GATEWAY_OP_ITEM: ITEM,
  OLLAMA_GATEWAY_URL: 'https://gateway.example',
  OLLAMA_GATEWAY_MODEL: 'qwen3.6:latest',
  MODEL_OVERRIDE: '',
  TRIGGER: 'dispatch',
  RUNNER_TEMP: '/tmp/rt',
  ...over,
});
const FIELDS = {
  'access/client id header': 'CF-Access-Client-Id',
  'access/client id': 'id%1.access',
  'access/client secret header': 'CF-Access-Client-Secret',
  password: 'secret-456',
};

/** A fake `op`: answers `op read <ref>` from FIELDS; records argv and env. */
function fakeOp({ fail = null } = {}) {
  const calls = [];
  const run = async (argv, env) => {
    calls.push({ argv, env });
    const field = argv[argv.length - 1].slice(ITEM.length + 1);
    if (fail) return { code: 1, stdout: '', stderr: fail };
    return { code: 0, stdout: FIELDS[field], stderr: '' };
  };
  run.calls = calls;
  return run;
}

test('credentials: every value is masked (workflow-command escaped) before any output or file', async () => {
  const step = fakeStep();
  const code = await runCredentials({ env: credEnv(), op: fakeOp(), step });
  assert.equal(code, 0);
  const firstWrite = step.events.findIndex((e) => e[0] !== 'log');
  const masks = step.events.slice(0, firstWrite).filter((e) => e[0] === 'log' && e[1].startsWith('::add-mask::'));
  const masked = masks.map((e) => e[1].slice('::add-mask::'.length));
  for (const v of ['id%251.access', 'secret-456', 'CF-Access-Client-Id', 'CF-Access-Client-Secret']) {
    assert.ok(masked.includes(v), `masked ${v} before the first output`);
  }
  assert.ok(masked.includes(ITEM), 'the item reference itself is masked');
});

test('credentials: op is called with argv, the token only in its environment', async () => {
  const op = fakeOp();
  await runCredentials({ env: credEnv(), op, step: fakeStep() });
  assert.equal(op.calls.length, 4);
  for (const call of op.calls) {
    assert.equal(call.argv[0], 'read');
    assert.equal(call.env.OP_SERVICE_ACCOUNT_TOKEN, 'ops_token');
    assert.ok(!call.argv.includes('ops_token'));
  }
});

test('credentials: outputs the model, url and ocr header string; headers file is 0600 JSON', async () => {
  const step = fakeStep();
  await runCredentials({ env: credEnv({ MODEL_OVERRIDE: 'gemma4:27b' }), op: fakeOp(), step });
  assert.equal(step.outputs.model, 'gemma4:27b');
  assert.equal(step.outputs.url, 'https://gateway.example');
  assert.equal(step.outputs.extra_headers, 'CF-Access-Client-Id=id%1.access,CF-Access-Client-Secret=secret-456');
  assert.deepEqual(JSON.parse(step.files['/tmp/rt/ocr-gateway-headers.json']), {
    'CF-Access-Client-Id': 'id%1.access',
    'CF-Access-Client-Secret': 'secret-456',
  });
});

test('credentials: a missing variable is configuration, exit 1, op never called', async () => {
  const step = fakeStep();
  const op = fakeOp();
  const code = await runCredentials({ env: credEnv({ OLLAMA_GATEWAY_URL: '' }), op, step });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'configuration');
  assert.match(step.outputs.detail, /OLLAMA_GATEWAY_URL/);
  assert.equal(op.calls.length, 0);
});

test('credentials: a refused token is configuration, and op\'s stderr is never echoed', async () => {
  const step = fakeStep();
  const code = await runCredentials({
    env: credEnv(),
    op: fakeOp({ fail: '[ERROR] authentication failed: invalid service account token for op://vault-uuid/item-title' }),
    step,
  });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'configuration');
  assert.match(step.outputs.detail, /service-account token/);
  const everything = JSON.stringify(step.events);
  assert.doesNotMatch(everything.replace(/::add-mask::[^"]*/g, ''), /vault-uuid/);
});

// --- probe -------------------------------------------------------------------

const probeEnv = { GATEWAY_URL: 'https://gateway.example', MODEL: 'qwen3.6:latest', HEADERS_FILE: '/tmp/rt/h.json' };
const readHeaders = () => JSON.stringify({ 'CF-Access-Client-Id': 'i', 'CF-Access-Client-Secret': 's' });
const instant = { now: () => 0, sleep: async () => {} };

test('probe: posts to the completions path with the item headers, never following a redirect', async () => {
  const step = fakeStep();
  const fetch = fakeFetch(() => text(200, JSON.stringify({ choices: [{ message: { content: 'OK' } }] })));
  const code = await runProbe({ env: probeEnv, fetch, readFile: readHeaders, clock: instant, step });
  assert.equal(code, 0);
  assert.equal(fetch.calls[0].url, 'https://gateway.example/v1/chat/completions');
  assert.equal(fetch.calls[0].init.method, 'POST');
  assert.equal(fetch.calls[0].init.redirect, 'manual');
  assert.equal(fetch.calls[0].init.headers['CF-Access-Client-Secret'], 's');
  assert.ok(fetch.calls[0].init.signal, 'every attempt is bounded');
});

test('probe: an Access 302 fails credential with exit 1; nothing logged carries a header value', async () => {
  const step = fakeStep();
  const code = await runProbe({ env: probeEnv, fetch: fakeFetch(() => text(302, '')), readFile: readHeaders, clock: instant, step });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'credential');
  assert.doesNotMatch(JSON.stringify(step.events), /"s"|CF-Access-Client-Secret/);
});

test('probe: a thrown fetch (DNS, TLS, connect) is gateway-down', async () => {
  const step = fakeStep();
  const fetch = fakeFetch(() => {
    throw new TypeError('fetch failed');
  });
  const code = await runProbe({ env: probeEnv, fetch, readFile: readHeaders, clock: instant, step });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'gateway-down');
});

// --- verdict -----------------------------------------------------------------

const resultJson = JSON.stringify({
  status: 'completed',
  comments: [{ path: 'src/a.js', start_line: 2, content: 'x' }],
  manifest: {
    input: { mode: 'range', resolved_base: BASE, resolved_head: HEAD },
    coverage: { selected: [{ path: 'src/a.js' }], completed: [{ path: 'src/a.js' }], reused: [], failed: [], waived: [] },
  },
});

/** A fake git answering the three questions the verdict asks. */
function fakeGit() {
  const calls = [];
  const run = async (argv, stdin) => {
    calls.push({ argv, stdin });
    if (argv.includes('--name-status')) return 'M\0src/a.js\0M\0yarn.lock\0';
    if (argv.includes('--numstat')) return '1\t1\tsrc/a.js\0';
    if (argv.includes('check-attr')) return ['src/a.js', 'linguist-generated', 'unspecified', 'src/a.js', 'linguist-vendored', 'unspecified', ''].join('\0');
    throw new Error(`unexpected git ${argv.join(' ')}`);
  };
  run.calls = calls;
  return run;
}

/** The verdict step's env as the workflow sets it: the Review step's
 * outcome, the action's post counts (steps.ocr.outputs.comments_*), and
 * OCR_EXIT_CODE, which the action itself exports. */
const verdictEnv = (over) => ({
  OCR_STEP_OUTCOME: 'success',
  OCR_EXIT_CODE: '0',
  OCR_RESULT_PATH: '/tmp/ocr-result.json',
  OCR_COMMENTS_TOTAL: '1',
  OCR_COMMENTS_INLINE: '0',
  OCR_COMMENTS_ROUTED: '0',
  OCR_COMMENTS_SKIPPED: '0',
  OCR_COMMENTS_FAILED: '1',
  RUNNER_TEMP: '/tmp/rt',
  ...over,
});

test('verdict: an ocr exit code marks the Review step engine-error and keeps the step green', async () => {
  const step = fakeStep();
  const code = await runVerdict({ env: verdictEnv({ OCR_STEP_OUTCOME: 'failure', OCR_EXIT_CODE: '3' }), git: fakeGit(), readFile: () => '', step });
  assert.equal(code, 0);
  assert.equal(step.outputs.review_cause, 'engine-error');
  assert.match(step.outputs.review_detail, /exited 3/);
});

test('verdict: the upstream action failing with no ocr exit code is left for report to call unexpected', async () => {
  const step = fakeStep();
  const code = await runVerdict({ env: verdictEnv({ OCR_STEP_OUTCOME: 'failure', OCR_EXIT_CODE: '' }), git: fakeGit(), readFile: () => '', step });
  assert.equal(code, 0);
  assert.equal(step.outputs.review_cause ?? '', '');
});

test('verdict: a completed review is judged by the action\'s counts', async () => {
  const step = fakeStep();
  const git = fakeGit();
  const code = await runVerdict({ env: verdictEnv(), git, readFile: () => resultJson, step });
  assert.equal(code, 0);
  assert.equal(step.outputs.cause, '');
  // git was asked about exactly the range ocr resolved.
  assert.ok(git.calls[0].argv.includes(`${BASE}..${HEAD}`));
  const state = JSON.parse(step.files['/tmp/rt/ocr-review-state/state.json']);
  assert.deepEqual(state.range, { base: BASE, head: HEAD });
  assert.equal(state.outcome, 'success');
  assert.equal(state.findingsPosted, 0);
  assert.equal(state.findingsFailed, 1);
});

test('verdict: a count the action did not set is engine-error naming it, never "nothing failed"', async () => {
  const step = fakeStep();
  const code = await runVerdict({ env: verdictEnv({ OCR_COMMENTS_FAILED: '' }), git: fakeGit(), readFile: () => resultJson, step });
  assert.equal(code, 1);
  assert.equal(step.outputs.cause, 'engine-error');
  assert.match(step.outputs.detail, /comments_failed/);
  assert.equal(JSON.parse(step.files['/tmp/rt/ocr-review-state/state.json']).cause, 'engine-error');
});

// --- report and comment --------------------------------------------------------

const reviewOutputs = (over = {}) =>
  JSON.stringify({
    tools: 'success',
    node: 'success',
    opcli: 'success',
    creds: 'success',
    probe: 'success',
    ocr: 'success',
    verdict: 'success',
    model: 'qwen3.6:latest',
    ...over,
  });

const reportEnv = (over) => ({
  REPO: 'o/r',
  PR: '7',
  EVENT_NAME: 'workflow_dispatch',
  RUN_CANCELLED: 'false',
  AUTHORIZE_RESULT: 'success',
  AUTHORIZE_OUTPUTS: JSON.stringify({ decision: 'approve', cause: '', authorize: 'success', tools: 'success', node: 'success', started_at: '2026-10-12T10:00:00Z' }),
  REVIEW_RESULT: 'success',
  REVIEW_OUTPUTS: reviewOutputs(),
  OCR_VERSION: '1.12.13',
  STATE_PATH: '/tmp/state/state.json',
  RUN_URL: 'https://github.com/o/r/actions/runs/1',
  RECORD_PATH: '/tmp/rt/record/ocr-review-record.json',
  COMMENT_PATH: '/tmp/rt/comment.md',
  ...over,
});

const noState = () => {
  const error = new Error('ENOENT');
  error.code = 'ENOENT';
  throw error;
};

test('report: pr-not-open writes the record and does not comment', async () => {
  const step = fakeStep();
  const env = reportEnv({
    AUTHORIZE_RESULT: 'failure',
    AUTHORIZE_OUTPUTS: JSON.stringify({ decision: 'fail', cause: 'pr-not-open', authorize: 'failure', started_at: 's' }),
    REVIEW_RESULT: 'skipped',
    REVIEW_OUTPUTS: '{}',
  });
  await runReport({ env, readFile: noState, step, now: () => 'f' });
  const record = JSON.parse(step.files[env.RECORD_PATH]);
  assert.equal(record.cause, 'pr-not-open');
  assert.equal(record.trigger, 'dispatch');
  assert.equal(step.outputs.should_comment, 'false');
});

test('report: the record is written to its file and the job summary before the comment body', async () => {
  const step = fakeStep();
  const env = reportEnv({ REVIEW_RESULT: 'failure', REVIEW_OUTPUTS: reviewOutputs({ probe: 'failure', probe_cause: 'gateway-down', probe_detail: 'HTTP 502', ocr: 'skipped', verdict: 'skipped' }) });
  await runReport({ env, readFile: noState, step, now: () => 'f', summary: (t) => step.events.push(['summary', t]) });
  const order = step.events.filter((e) => e[0] === 'file' || e[0] === 'summary').map((e) => (e[0] === 'summary' ? 'summary' : e[1]));
  assert.deepEqual(order, [env.RECORD_PATH, 'summary', env.COMMENT_PATH]);
  const record = JSON.parse(step.files[env.RECORD_PATH]);
  assert.equal(record.cause, 'gateway-down');
  assert.equal(record.model, 'qwen3.6:latest');
  assert.equal(record.started_at, '2026-10-12T10:00:00Z');
  assert.equal(record.finished_at, 'f');
  assert.match(step.files[env.COMMENT_PATH], /HTTP 502/);
  assert.equal(step.outputs.should_comment, 'true');
});

test('report: a cancelled run is recorded cancelled', async () => {
  const step = fakeStep();
  await runReport({ env: reportEnv({ RUN_CANCELLED: 'true', REVIEW_RESULT: 'cancelled' }), readFile: noState, step, now: () => 'f' });
  assert.equal(JSON.parse(step.files['/tmp/rt/record/ocr-review-record.json']).outcome, 'cancelled');
});

test('report: a failed setup step is unexpected naming review and the step', async () => {
  const step = fakeStep();
  const env = reportEnv({ REVIEW_RESULT: 'failure', REVIEW_OUTPUTS: reviewOutputs({ opcli: 'failure', creds: 'skipped', probe: 'skipped', ocr: 'skipped', verdict: 'skipped' }) });
  await runReport({ env, readFile: noState, step, now: () => 'f' });
  const record = JSON.parse(step.files[env.RECORD_PATH]);
  assert.equal(record.cause, 'unexpected');
  const opcli = REVIEW_STEPS.find((s) => s.key === 'opcli');
  assert.equal(record.failing_step, `review / ${opcli.name}`);
});

test('report: a host-tools failure is recorded runner-tool-missing and the comment names the tool', async () => {
  const step = fakeStep();
  const env = reportEnv({
    REVIEW_RESULT: 'failure',
    REVIEW_OUTPUTS: reviewOutputs({
      stage: 'success',
      hosttools: 'failure',
      hosttools_cause: 'runner-tool-missing',
      hosttools_detail: 'gpg',
      opcli: 'skipped',
      creds: 'skipped',
      probe: 'skipped',
      ocr: 'skipped',
      verdict: 'skipped',
      model: '',
    }),
  });
  await runReport({ env, readFile: noState, step, now: () => 'f' });
  const record = JSON.parse(step.files[env.RECORD_PATH]);
  assert.equal(record.outcome, 'failure');
  assert.equal(record.cause, 'runner-tool-missing');
  assert.equal(record.failing_step, null);
  assert.match(step.files[env.COMMENT_PATH], /Detail: gpg/);
  assert.equal(step.outputs.should_comment, 'true');
});

test('report: the review state supplies the range and counts', async () => {
  const step = fakeStep();
  const state = { cause: null, range: { base: BASE, head: HEAD }, filesReviewable: 1, filesReviewed: 1, findingsPosted: 0, findingsFailed: 0, unreviewed: [] };
  await runReport({ env: reportEnv(), readFile: () => JSON.stringify(state), step, now: () => 'f' });
  const record = JSON.parse(step.files['/tmp/rt/record/ocr-review-record.json']);
  assert.equal(record.outcome, 'success');
  assert.equal(record.range, `${BASE}..${HEAD}`);
  assert.equal(record.files_reviewed, 1);
});

test('report: the comment links upstream\'s summary from the review job\'s upstream_summary_url', async () => {
  const step = fakeStep();
  const url = 'https://github.com/o/r/pull/7#issuecomment-9';
  const state = { outcome: 'success', cause: null, range: { base: BASE, head: HEAD }, filesReviewable: 1, filesReviewed: 1, findingsPosted: 1, findingsFailed: 1, unreviewed: [] };
  const env = reportEnv({ REVIEW_OUTPUTS: reviewOutputs({ upstream_summary_url: url }) });
  await runReport({ env, readFile: () => JSON.stringify(state), step, now: () => 'f' });
  const body = step.files[env.COMMENT_PATH];
  assert.ok(body.includes(`](${url})`), body);
  assert.match(body, /failed to post are named/);
});

test('comment: posts the body to the PR; a failed post throws so the job fails', async () => {
  const fetch = fakeFetch(() => json(201, { html_url: 'u' }));
  await runComment({ env: { GITHUB_TOKEN: 't', REPO: 'o/r', PR: '7', COMMENT_PATH: '/c' }, fetch, readFile: () => 'hello' });
  assert.equal(fetch.calls[0].url, 'https://api.github.com/repos/o/r/issues/7/comments');
  assert.deepEqual(fetch.calls[0].body, { body: 'hello' });
  await assert.rejects(
    runComment({ env: { GITHUB_TOKEN: 't', REPO: 'o/r', PR: '7', COMMENT_PATH: '/c' }, fetch: fakeFetch(() => json(403, {})), readFile: () => 'x' }),
    /HTTP 403/,
  );
});
