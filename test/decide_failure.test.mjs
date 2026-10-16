// test/decide_failure.test.mjs -- decide: failure classes, exit codes,
// HTTP status classification, the retry rule, redaction
// (lib/decide/failure.mjs), and the command line (lib/decide/args.mjs).
// Values only; no fakes.
// Run: node --test test/decide_failure.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs } from '../lib/decide/args.mjs';
import { EXIT_CODES, classifyHttpFailure, classifyTransportError, exitCodeFor, redact, shouldRetry, vendorMessage } from '../lib/decide/failure.mjs';

// --- Exit codes and HTTP classes ---------------------------------------------

test('each failure class has its contract exit code', () => {
  assert.deepEqual(EXIT_CODES, { config: 2, rejected: 3, unavailable: 4, auth: 5, malformed: 6 });
  assert.equal(exitCodeFor('rejected'), 3);
  assert.equal(exitCodeFor('nonsense'), 1);
});

test('every HTTP status maps to its class and exit code', () => {
  const table = [
    [400, 'rejected', 3],
    [413, 'rejected', 3],
    [422, 'rejected', 3],
    [401, 'auth', 5],
    [403, 'auth', 5],
    [429, 'unavailable', 4],
    [402, 'unavailable', 4],
    [500, 'unavailable', 4],
    [502, 'unavailable', 4],
    [503, 'unavailable', 4],
    [504, 'unavailable', 4],
    [404, 'config', 2],
    [405, 'rejected', 3],
    [302, 'malformed', 6],
  ];
  for (const [status, cls, code] of table) {
    const verdict = classifyHttpFailure(status);
    assert.equal(verdict.class, cls, `HTTP ${status}`);
    assert.equal(verdict.status, status);
    assert.equal(exitCodeFor(verdict.class), code, `HTTP ${status}`);
  }
});

test('a 429 says spend limit or rate limit', () => {
  assert.match(classifyHttpFailure(429).message, /spend limit or rate limit \(HTTP 429\)/);
});

// Issue#520: three different 429s, told apart by the vendor's message.
const CAPACITY_429 = { errors: [{ message: 'AiError: AiError: Capacity temporarily exceeded, please try again. (fec9d3c8-bb67)' }] };
const RATE_429 = { errors: [{ message: 'Unified billing rate limited' }] };

test('a Workers AI capacity 429 says capacity, not spend', () => {
  const said = classifyHttpFailure(429, CAPACITY_429);
  assert.equal(said.class, 'unavailable');
  assert.match(said.message, /Workers AI capacity is temporarily exceeded \(HTTP 429\)/);
  assert.doesNotMatch(said.message, /spend/);
});

test("a gateway rate-limit 429 says the request rate, not spend", () => {
  const said = classifyHttpFailure(429, RATE_429);
  assert.equal(said.class, 'unavailable');
  assert.match(said.message, /request-rate limit \(HTTP 429\)/);
  assert.doesNotMatch(said.message, /spend/);
});

test('a capacity or rate-limit 429 earns the retry; any other 429 does not', () => {
  assert.equal(shouldRetry({ status: 429, body: CAPACITY_429 }), true);
  assert.equal(shouldRetry({ status: 429, body: RATE_429 }), true);
  assert.equal(shouldRetry({ status: 429, body: { errors: [{ message: 'spend limit exceeded' }] } }), false);
  assert.equal(shouldRetry({ status: 429, body: null }), false);
});

test("the vendor's error message rides along, trimmed", () => {
  assert.match(classifyHttpFailure(400, { errors: [{ code: 5006, message: 'Error: questions too long' }] }).message, /: Error: questions too long$/);
  assert.equal(vendorMessage({ error: { message: 'bad' } }), 'bad');
  assert.equal(vendorMessage({ error: 'worse' }), 'worse');
  assert.equal(vendorMessage(null), '');
  assert.equal(vendorMessage({ errors: [{ message: 'x'.repeat(300) }] }).length, 203);
});

test('a timeout and a network error are unavailable', () => {
  const timeout = classifyTransportError({ kind: 'timeout', message: 'aborted' }, 60000);
  assert.equal(timeout.class, 'unavailable');
  assert.match(timeout.message, /60000 ms/);
  assert.match(classifyTransportError({ kind: 'network', message: 'ECONNRESET' }, 1).message, /network error: ECONNRESET/);
});

// --- Retry and redaction -----------------------------------------------------

test('only a network error and 502/503/504 earn the retry', () => {
  assert.equal(shouldRetry({ error: { kind: 'network' } }), true);
  assert.equal(shouldRetry({ error: { kind: 'timeout' } }), false);
  for (const status of [502, 503, 504]) assert.equal(shouldRetry({ status }), true);
  for (const status of [200, 400, 401, 429, 500]) assert.equal(shouldRetry({ status }), false);
});

test('redact removes every occurrence of the secret', () => {
  assert.equal(redact('Bearer s3cret and s3cret', 's3cret'), 'Bearer [redacted] and [redacted]');
  assert.equal(redact('nothing', null), 'nothing');
});

// --- Command line ------------------------------------------------------------

test('run takes its flags in both spellings', () => {
  assert.deepEqual(parseArgs(['run', '--model', 'clef-flash', '--tool=ocrinator', '--jsonl', '--concurrency', '8', '--file', 'in.jsonl']), {
    ok: true,
    command: 'run',
    flags: { jsonl: true, model: 'clef-flash', tool: 'ocrinator', concurrency: 8, file: 'in.jsonl' },
  });
});

test('concurrency defaults to 4 and accepts 1..16 only', () => {
  assert.equal(parseArgs(['run']).flags.concurrency, 4);
  assert.equal(parseArgs(['run', '--concurrency', '1']).flags.concurrency, 1);
  assert.equal(parseArgs(['run', '--concurrency', '16']).flags.concurrency, 16);
  for (const bad of ['0', '17', '2.5', 'many']) assert.equal(parseArgs(['run', '--concurrency', bad]).ok, false, bad);
});

test('--help anywhere is help', () => {
  assert.deepEqual(parseArgs(['--help']), { ok: true, command: 'help' });
  assert.deepEqual(parseArgs(['run', '-h']), { ok: true, command: 'help' });
});

test('no command, an unknown command, an unknown flag or a missing value is a config failure', () => {
  for (const argv of [[], ['frob'], ['run', '--fast'], ['run', '--model'], ['probe', '--jsonl'], ['run', '--jsonl=yes'], ['run', 'stray']]) {
    const verdict = parseArgs(argv);
    assert.equal(verdict.ok, false, argv.join(' '));
    assert.equal(verdict.error.class, 'config');
  }
});

test('probe takes --model', () => {
  assert.equal(parseArgs(['probe', '--model', 'clef-flash']).flags.model, 'clef-flash');
});
