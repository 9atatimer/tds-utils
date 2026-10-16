// test/decide_io.test.mjs -- decide: the command flows (bin/decide) driven
// through runCli with the argv forms docs/ops/decide.md shows. fetch, the
// 1Password CLI, the clock, stdin and stdout are fakes passed in; no
// network, no subprocess, no sleeps.
// Run: node --test test/decide_io.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PROBE_REQUEST, RETRY_DELAY_MS, runCli } from '../bin/decide';

const BASE = 'https://gateway.example/v1/acct/gw';
/** The REST route that base resolves to. */
const REST = 'https://api.cloudflare.com/client/v4/accounts/acct/ai/run/@cf/cloudflare';
const TOKEN = 'run-token-s3cret';
const CF_ENV = Object.freeze({ DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_TOKEN: TOKEN });

const QUESTIONS = {
  urgency: { type: 'score', instructions: 'How urgent?', criteria: ['low', 'medium', 'high'] },
  team: { type: 'choice', instructions: 'Which team?', criteria: { billing: 'money', technical: 'bugs' } },
  spam: { type: 'noul', instructions: 'Is it spam?' },
};
const RECORD = { id: 'ticket-7', state: 'My invoice is wrong.', questions: QUESTIONS };
const RESULT = {
  model: '@cf/cloudflare/clef',
  answers: {
    urgency: { score: 0.75, confidence: 0.43, legend: ['low', 'medium', 'high'], probabilities: { 0: 0.5, 1: 0.25, 2: 0.25 } },
    team: { choice: 'billing', confidence: 0.91, probabilities: { billing: 0.75, technical: 0.25 } },
    spam: { probability: 0.125 },
  },
  usage: { prompt_tokens: 40 },
};
const wrapped = (result) => ({ result, success: true, errors: [], messages: [] });
const answering = (questions) => wrapped({ model: 'm', answers: Object.fromEntries(Object.keys(questions).map((q) => [q, { probability: 0.5 }])) });

// --- Fakes -------------------------------------------------------------------

/** A clock whose time moves only when told to (or on sleep). */
function fakeClock() {
  const clock = {
    t: 1000,
    sleeps: [],
    now: () => clock.t,
    advance: (ms) => {
      clock.t += ms;
    },
    sleep: async (ms) => {
      clock.sleeps.push(ms);
      clock.t += ms;
    },
  };
  return clock;
}

const response = (status, body) => ({ status, text: async () => (typeof body === 'string' ? body : JSON.stringify(body)) });

/** A fetch answering from `handler(call, index)`; records every call. */
function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    const call = { url, method: init.method, headers: init.headers, body: JSON.parse(init.body) };
    calls.push(call);
    return handler(call, calls.length - 1);
  };
  fn.calls = calls;
  return fn;
}

/** Answers in order from a list: a response, or an Error to throw. */
const sequence = (...answers) => (_call, i) => {
  const answer = answers[Math.min(i, answers.length - 1)];
  if (answer instanceof Error) throw answer;
  return answer;
};

/** The 1Password CLI: records argv, answers `result`. */
function fakeOp(result = { code: 0, stdout: `${TOKEN}\n`, stderr: '' }) {
  const fn = async (argv) => {
    fn.calls.push(argv);
    return result;
  };
  fn.calls = [];
  return fn;
}

/** Every adapter runCli needs, with stdout/stderr captured. */
function fakeIo({ env = CF_ENV, stdin = '', files = {}, fetch, op = fakeOp(), clock = fakeClock() } = {}) {
  const io = {
    env,
    fetch,
    op,
    clock,
    signalFor: () => undefined,
    readStdin: async () => stdin,
    readFile: async (path) => {
      if (!(path in files)) throw new Error(`ENOENT: no such file, open '${path}'`);
      return files[path];
    },
    lines: [],
    errs: [],
  };
  io.out = (line) => io.lines.push(line);
  io.err = (line) => io.errs.push(line);
  io.decisions = () => io.lines.map((line) => JSON.parse(line));
  return io;
}

const networkError = () => Object.assign(new TypeError('fetch failed'), { cause: new Error('ECONNREFUSED') });
const timeoutError = () => Object.assign(new Error('The operation was aborted due to timeout'), { name: 'TimeoutError' });

// --- run: one record ---------------------------------------------------------

test('run --file posts the record (without its id) and prints one normalized decision', async () => {
  const clock = fakeClock();
  const fetch = fakeFetch(() => {
    clock.advance(212);
    return response(200, wrapped(RESULT));
  });
  const io = fakeIo({ files: { 'ticket.json': JSON.stringify(RECORD) }, fetch, clock });
  const code = await runCli(['run', '--file', 'ticket.json'], io);
  assert.equal(code, 0);
  assert.equal(fetch.calls.length, 1);
  assert.equal(fetch.calls[0].url, `${REST}/clef`);
  assert.equal(fetch.calls[0].headers['cf-aig-gateway-id'], 'gw');
  assert.equal(fetch.calls[0].method, 'POST');
  assert.deepEqual(fetch.calls[0].body, { model: 'clef', state: RECORD.state, questions: QUESTIONS });
  assert.deepEqual(io.decisions(), [
    {
      id: 'ticket-7',
      ok: true,
      model: 'clef',
      backend: 'cf-ai-gateway',
      latency_ms: 212,
      usage: { prompt_tokens: 40 },
      answers: {
        urgency: { type: 'score', levels: 3, vendor_confidence: 0.43, probabilities: [0.5, 0.25, 0.25], expected: 0.75, unit: 0.375, top: 0, calibrated: true },
        team: { type: 'choice', vendor_confidence: 0.91, probabilities: { billing: 0.75, technical: 0.25 }, top: 'billing', calibrated: true },
        spam: { type: 'noul', vendor_confidence: null, p_true: 0.125, calibrated: true },
      },
      raw: RESULT,
    },
  ]);
  assert.deepEqual(io.errs, []);
});

test('run reads stdin when no --file is given, and --tool stamps the gateway metadata', async () => {
  const fetch = fakeFetch(() => response(200, wrapped(RESULT)));
  const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch });
  assert.equal(await runCli(['run', '--tool', 'ocrinator', '--model', 'clef-flash'], io), 0);
  assert.equal(fetch.calls[0].headers['cf-aig-metadata'], '{"tool":"ocrinator"}');
  assert.equal(fetch.calls[0].url, `${REST}/clef-flash`);
  assert.equal(io.decisions()[0].model, 'clef-flash');
});

test('a record without an id gets id null', async () => {
  const { id: _drop, ...anonymous } = RECORD;
  const io = fakeIo({ stdin: JSON.stringify(anonymous), fetch: fakeFetch(() => response(200, wrapped(RESULT))) });
  await runCli(['run'], io);
  assert.equal(io.decisions()[0].id, null);
});

test('the systemone backend posts to /v1/systemone with no auth and reads an unwrapped answer', async () => {
  const fetch = fakeFetch(() => response(200, RESULT));
  const io = fakeIo({ env: { DECIDE_BACKEND: 'systemone', DECIDE_URL: 'http://127.0.0.1:30000' }, stdin: JSON.stringify(RECORD), fetch });
  assert.equal(await runCli(['run'], io), 0);
  assert.equal(fetch.calls[0].url, 'http://127.0.0.1:30000/v1/systemone');
  assert.deepEqual(fetch.calls[0].headers, { 'content-type': 'application/json' });
  assert.equal(io.decisions()[0].backend, 'systemone');
});

// --- run: failures -----------------------------------------------------------

test('every HTTP failure status prints a failure decision and exits with its class code', async () => {
  const table = [
    [400, 'rejected', 3],
    [413, 'rejected', 3],
    [422, 'rejected', 3],
    [401, 'auth', 5],
    [403, 'auth', 5],
    [429, 'unavailable', 4],
    [500, 'unavailable', 4],
    [404, 'config', 2],
  ];
  for (const [status, cls, exit] of table) {
    const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch: fakeFetch(() => response(status, { success: false, errors: [{ message: 'no' }] })) });
    assert.equal(await runCli(['run'], io), exit, `HTTP ${status}`);
    const [decision] = io.decisions();
    assert.deepEqual(Object.keys(decision), ['id', 'ok', 'error']);
    assert.equal(decision.id, 'ticket-7');
    assert.equal(decision.ok, false);
    assert.equal(decision.error.class, cls);
    assert.equal(decision.error.status, status);
    assert.match(io.errs[0], new RegExp(`^decide: ${cls}: `));
  }
});

test('the token never reaches stdout or stderr, even when the backend echoes it', async () => {
  const fetch = fakeFetch(() => response(401, { errors: [{ message: `bad token ${TOKEN}` }] }));
  const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch });
  assert.equal(await runCli(['run'], io), 5);
  assert.match(io.decisions()[0].error.message, /bad token \[redacted\]/);
  assert.equal([...io.lines, ...io.errs].join('\n').includes(TOKEN), false);
});

test('a 2xx that is not JSON, or lacks a question, is malformed (exit 6)', async () => {
  const notJson = fakeIo({ stdin: JSON.stringify(RECORD), fetch: fakeFetch(() => response(200, '<html>')) });
  assert.equal(await runCli(['run'], notJson), 6);
  assert.equal(notJson.decisions()[0].error.class, 'malformed');
  const { spam: _drop, ...partial } = RESULT.answers;
  const missing = fakeIo({ stdin: JSON.stringify(RECORD), fetch: fakeFetch(() => response(200, wrapped({ ...RESULT, answers: partial }))) });
  assert.equal(await runCli(['run'], missing), 6);
  assert.match(missing.decisions()[0].error.message, /no answer for question "spam"/);
});

test('an invalid record is rejected (exit 3) before any network call or token read', async () => {
  const fetch = fakeFetch(() => response(200, wrapped(RESULT)));
  const op = fakeOp();
  const io = fakeIo({ env: { DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'op://v/i' }, stdin: JSON.stringify({ ...RECORD, questions: {} }), fetch, op });
  assert.equal(await runCli(['run'], io), 3);
  assert.equal(fetch.calls.length, 0);
  assert.equal(op.calls.length, 0);
  assert.equal(io.decisions()[0].id, 'ticket-7');
  assert.equal(io.decisions()[0].error.class, 'rejected');
});

test('input that is not JSON is rejected (exit 3)', async () => {
  const io = fakeIo({ stdin: 'not json', fetch: fakeFetch(() => response(200, {})) });
  assert.equal(await runCli(['run'], io), 3);
  assert.deepEqual(io.decisions()[0], { id: null, ok: false, error: { class: 'rejected', message: 'the input is not valid JSON', status: null } });
});

test('missing configuration exits 2 with a failure decision and no network call', async () => {
  const fetch = fakeFetch(() => response(200, {}));
  const io = fakeIo({ env: {}, stdin: JSON.stringify(RECORD), fetch });
  assert.equal(await runCli(['run'], io), 2);
  assert.equal(fetch.calls.length, 0);
  assert.equal(io.decisions()[0].error.class, 'config');
});

test('an unreadable --file is a config failure', async () => {
  const io = fakeIo({ fetch: fakeFetch(() => response(200, {})) });
  assert.equal(await runCli(['run', '--file', 'nope.json'], io), 2);
  assert.match(io.decisions()[0].error.message, /cannot read the input file nope\.json/);
});

test('a bad flag exits 2 with the usage on stderr', async () => {
  const io = fakeIo({ fetch: fakeFetch(() => response(200, {})) });
  assert.equal(await runCli(['run', '--concurrency', '99'], io), 2);
  assert.match(io.errs[0], /^usage: decide run/);
  assert.equal(io.decisions()[0].error.class, 'config');
});

test('--help prints the usage and exits 0', async () => {
  const io = fakeIo({ fetch: fakeFetch(() => response(200, {})) });
  assert.equal(await runCli(['--help'], io), 0);
  assert.match(io.lines[0], /^usage: decide run/);
});

// --- run: retry --------------------------------------------------------------

test('a 503 is retried once after 2 s; latency is the answered attempt', async () => {
  const clock = fakeClock();
  const fetch = fakeFetch((_call, i) => {
    clock.advance(i === 0 ? 30 : 100);
    return i === 0 ? response(503, {}) : response(200, wrapped(RESULT));
  });
  const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch, clock });
  assert.equal(await runCli(['run'], io), 0);
  assert.equal(fetch.calls.length, 2);
  assert.deepEqual(clock.sleeps, [RETRY_DELAY_MS]);
  assert.equal(RETRY_DELAY_MS, 2000);
  assert.equal(io.decisions()[0].latency_ms, 100);
});

test('502/503/504 twice fails unavailable after exactly one retry', async () => {
  for (const status of [502, 503, 504]) {
    const clock = fakeClock();
    const fetch = fakeFetch(() => response(status, {}));
    const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch, clock });
    assert.equal(await runCli(['run'], io), 4);
    assert.equal(fetch.calls.length, 2, `HTTP ${status}`);
    assert.deepEqual(clock.sleeps, [2000]);
  }
});

test('a network error is retried once; a second one is unavailable', async () => {
  const recovers = fakeFetch(sequence(networkError(), response(200, wrapped(RESULT))));
  assert.equal(await runCli(['run'], fakeIo({ stdin: JSON.stringify(RECORD), fetch: recovers })), 0);
  assert.equal(recovers.calls.length, 2);
  const stays = fakeFetch(sequence(networkError(), networkError()));
  const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch: stays });
  assert.equal(await runCli(['run'], io), 4);
  assert.match(io.decisions()[0].error.message, /network error: ECONNREFUSED/);
});

test('a timeout, a 500 and a 429 are not retried', async () => {
  for (const answer of [timeoutError(), response(500, {}), response(429, {})]) {
    const clock = fakeClock();
    const fetch = fakeFetch(sequence(answer, response(200, wrapped(RESULT))));
    const io = fakeIo({ stdin: JSON.stringify(RECORD), fetch, clock });
    assert.equal(await runCli(['run'], io), 4);
    assert.equal(fetch.calls.length, 1);
    assert.deepEqual(clock.sleeps, []);
  }
});

// --- the 1Password runner ----------------------------------------------------

test('with DECIDE_GATEWAY_OP_ITEM, op reads the password field once and the token is sent', async () => {
  const op = fakeOp();
  const fetch = fakeFetch(() => response(200, wrapped(RESULT)));
  const io = fakeIo({ env: { DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'op://vault/item' }, stdin: JSON.stringify(RECORD), fetch, op });
  assert.equal(await runCli(['run'], io), 0);
  assert.deepEqual(op.calls, [['read', 'op://vault/item/password']]);
  assert.equal(fetch.calls[0].headers.authorization, `Bearer ${TOKEN}`);
  assert.equal('cf-aig-authorization' in fetch.calls[0].headers, false);
});

test('a literal token means op is never run', async () => {
  const op = fakeOp();
  await runCli(['run'], fakeIo({ env: { ...CF_ENV, DECIDE_GATEWAY_OP_ITEM: 'op://vault/item' }, stdin: JSON.stringify(RECORD), fetch: fakeFetch(() => response(200, wrapped(RESULT))), op }));
  assert.equal(op.calls.length, 0);
});

test('op failing, or absent, is a config failure with no network call', async () => {
  for (const result of [{ code: 1, stdout: '', stderr: '[ERROR] not signed in' }, { code: 127, stdout: '', stderr: '', missing: true }, { code: 0, stdout: '\n', stderr: '' }]) {
    const fetch = fakeFetch(() => response(200, wrapped(RESULT)));
    const io = fakeIo({ env: { DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'op://vault/item' }, stdin: JSON.stringify(RECORD), fetch, op: fakeOp(result) });
    assert.equal(await runCli(['run'], io), 2);
    assert.equal(fetch.calls.length, 0);
    assert.equal(io.decisions()[0].error.class, 'config');
    assert.equal(io.decisions()[0].id, 'ticket-7');
  }
});

// --- run --jsonl -------------------------------------------------------------

/** A fetch that holds every request until the test releases it. */
function gatedFetch() {
  const pending = [];
  let inFlight = 0;
  const fn = async (_url, init) => {
    inFlight += 1;
    fn.maxInFlight = Math.max(fn.maxInFlight, inFlight);
    const body = JSON.parse(init.body);
    const answer = await new Promise((release) => pending.push({ body, release }));
    inFlight -= 1;
    return answer;
  };
  fn.maxInFlight = 0;
  fn.pending = pending;
  fn.releaseState = (state, answer) => {
    const index = pending.findIndex((p) => p.body.state === state);
    const [entry] = pending.splice(index, 1);
    entry.release(answer ?? response(200, answering(entry.body.questions)));
  };
  return fn;
}

/** Let queued promise callbacks run (event coordination, not a sleep). */
const settle = async (until) => {
  for (let i = 0; i < 50 && !until(); i += 1) await new Promise((done) => setImmediate(done));
  assert.ok(until(), 'condition never reached');
};

const line = (id, state) => JSON.stringify({ id, state, questions: { q: { type: 'noul', instructions: 'x' } } });

test('--jsonl writes one decision per line in input order while answers arrive out of order', async () => {
  const fetch = gatedFetch();
  const io = fakeIo({ stdin: [line(0, 's0'), line(1, 's1'), line(2, 's2')].join('\n'), fetch });
  const running = runCli(['run', '--jsonl', '--concurrency', '3'], io);
  await settle(() => fetch.pending.length === 3);
  fetch.releaseState('s2');
  fetch.releaseState('s1');
  await settle(() => fetch.pending.length === 1);
  assert.deepEqual(io.lines, [], 'nothing is written before the first record is decided');
  fetch.releaseState('s0');
  assert.equal(await running, 0);
  assert.deepEqual(io.decisions().map((d) => d.id), [0, 1, 2]);
  assert.equal(fetch.maxInFlight, 3);
});

test('--jsonl never has more than --concurrency requests in flight', async () => {
  const fetch = gatedFetch();
  const states = ['a', 'b', 'c', 'd', 'e'];
  const io = fakeIo({ stdin: `${states.map((s, i) => line(`id-${i}`, s)).join('\n')}\n`, fetch });
  const running = runCli(['run', '--jsonl', '--concurrency', '2'], io);
  for (let released = 0; released < states.length; released += 1) {
    await settle(() => fetch.pending.length === Math.min(2, states.length - released));
    fetch.releaseState(fetch.pending[fetch.pending.length - 1].body.state);
  }
  await settle(() => io.lines.length === 5);
  assert.equal(await running, 0);
  assert.equal(fetch.maxInFlight, 2);
  assert.deepEqual(io.decisions().map((d) => d.id), ['id-0', 'id-1', 'id-2', 'id-3', 'id-4']);
});

test('--jsonl writes a failure line per bad record, skips blank lines, and exits with the first failure in input order', async () => {
  const fetch = fakeFetch((call) => (call.body.state === 'denied' ? response(401, {}) : response(200, answering(call.body.questions))));
  const stdin = [line('ok-1', 'fine'), '', '{not json', line('auth-1', 'denied'), '   ', JSON.stringify({ id: 'bad-1', state: 's', questions: {} }), line('ok-2', 'fine')].join('\n');
  const io = fakeIo({ files: { 'batch.jsonl': stdin }, fetch });
  assert.equal(await runCli(['run', '--jsonl', '--file', 'batch.jsonl'], io), 3);
  const decisions = io.decisions();
  assert.deepEqual(
    decisions.map((d) => [d.id, d.ok ? 'ok' : d.error.class]),
    [
      ['ok-1', 'ok'],
      [null, 'rejected'],
      ['auth-1', 'auth'],
      ['bad-1', 'rejected'],
      ['ok-2', 'ok'],
    ],
  );
  assert.equal(fetch.calls.length, 3);
  assert.deepEqual(io.errs, []);
});

test('--jsonl exits with the class of the first failure even when a later class is reached first', async () => {
  const fetch = fakeFetch((call) => response(call.body.state === 'a' ? 429 : 403, {}));
  const io = fakeIo({ stdin: [line(1, 'a'), line(2, 'b')].join('\n'), fetch });
  assert.equal(await runCli(['run', '--jsonl'], io), 4);
  assert.equal(io.lines.length, 2);
});

test('--jsonl with an empty input writes nothing and exits 0', async () => {
  const io = fakeIo({ stdin: '\n\n', fetch: fakeFetch(() => response(200, {})) });
  assert.equal(await runCli(['run', '--jsonl'], io), 0);
  assert.deepEqual(io.lines, []);
});

test('--jsonl with a token failure writes a config line for every valid record', async () => {
  const fetch = fakeFetch(() => response(200, {}));
  const io = fakeIo({
    env: { DECIDE_GATEWAY_URL: BASE, DECIDE_GATEWAY_OP_ITEM: 'op://vault/item' },
    stdin: [line('a', 's'), '{bad', line('b', 's')].join('\n'),
    fetch,
    op: fakeOp({ code: 1, stdout: '', stderr: '' }),
  });
  assert.equal(await runCli(['run', '--jsonl'], io), 2);
  assert.deepEqual(io.decisions().map((d) => [d.id, d.error.class]), [
    ['a', 'config'],
    [null, 'rejected'],
    ['b', 'config'],
  ]);
  assert.equal(fetch.calls.length, 0);
});

// --- probe -------------------------------------------------------------------

test('probe sends one tiny noul question and prints ok, model and latency', async () => {
  const clock = fakeClock();
  const fetch = fakeFetch(() => {
    clock.advance(87);
    return response(200, wrapped({ model: 'm', answers: { probe: 0.9 } }));
  });
  const io = fakeIo({ fetch, clock });
  assert.equal(await runCli(['probe', '--model', 'clef-flash'], io), 0);
  assert.deepEqual(fetch.calls[0].body, { model: 'clef-flash', ...PROBE_REQUEST });
  assert.equal(PROBE_REQUEST.questions.probe.type, 'noul');
  assert.deepEqual(io.decisions(), [{ ok: true, model: 'clef-flash', latency_ms: 87 }]);
});

test('probe failures print a failure and exit with the class code', async () => {
  const refused = fakeIo({ fetch: fakeFetch(() => response(403, {})) });
  assert.equal(await runCli(['probe'], refused), 5);
  assert.deepEqual(Object.keys(refused.decisions()[0]), ['ok', 'model', 'error']);
  assert.equal(refused.decisions()[0].error.class, 'auth');
  const noAnswer = fakeIo({ fetch: fakeFetch(() => response(200, wrapped({ answers: {} }))) });
  assert.equal(await runCli(['probe'], noAnswer), 6);
  const unconfigured = fakeIo({ env: {}, fetch: fakeFetch(() => response(200, {})) });
  assert.equal(await runCli(['probe'], unconfigured), 2);
  assert.equal(unconfigured.decisions()[0].model, null);
});
