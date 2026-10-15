// test/decide_answers.test.mjs -- decide: unwrapping a backend's answer and
// normalizing each question type (lib/decide/answers.mjs). Values only; no
// fakes.
// Run: node --test test/decide_answers.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeAnswers, normalizeChoice, normalizeNoul, normalizeScore, unwrapResponse } from '../lib/decide/answers.mjs';

const RUBRIC5 = ['none', 'low', 'medium', 'high', 'critical'];
const score5 = { type: 'score', instructions: 'How urgent?', criteria: RUBRIC5 };
const score3 = { type: 'score', instructions: 'How sure?', criteria: ['no', 'maybe', 'yes'] };
const choice = { type: 'choice', instructions: 'Which team?', criteria: { billing: 'money', technical: 'bugs', sales: 'buying' } };

const ok = (verdict) => {
  assert.equal(verdict.ok, true, JSON.stringify(verdict));
  return verdict.answer;
};
const isMalformed = (verdict, pattern) => {
  assert.equal(verdict.ok, false);
  assert.equal(verdict.error.class, 'malformed');
  if (pattern) assert.match(verdict.error.message, pattern);
};
const near = (got, want) => assert.ok(Math.abs(got - want) < 1e-12, `${got} != ${want}`);

// --- Envelope ----------------------------------------------------------------

test('a Workers AI envelope is unwrapped to its result', () => {
  const result = { model: '@cf/cloudflare/clef', answers: { q: 0.5 }, usage: { prompt_tokens: 12 } };
  const verdict = unwrapResponse({ result, success: true, errors: [], messages: [] });
  assert.deepEqual(verdict, { ok: true, result, answers: { q: 0.5 } });
});

test('a SystemOne answer is taken as it is', () => {
  const body = { model: 'clef-flash', answers: { q: 0.5 }, usage: null };
  assert.deepEqual(unwrapResponse(body), { ok: true, result: body, answers: { q: 0.5 } });
});

test('answers given as a list of {id, ...} are keyed by id', () => {
  const verdict = unwrapResponse({ model: 'm', answers: [{ id: 'q', probability: 0.4 }] });
  assert.deepEqual(verdict.answers, { q: { id: 'q', probability: 0.4 } });
});

test('success false, no answers, or a non-object body is malformed', () => {
  isMalformed(unwrapResponse({ result: { answers: {} }, success: false, errors: [{ message: 'x' }] }), /success: false/);
  isMalformed(unwrapResponse({ result: { model: 'm' }, success: true }), /no answers/);
  isMalformed(unwrapResponse({ model: 'm' }), /no answers/);
  isMalformed(unwrapResponse([1, 2]), /JSON object/);
  isMalformed(unwrapResponse(null), /JSON object/);
});

// --- Score: the math ---------------------------------------------------------

test('expected is sum(i * p_i), unit is expected/(levels-1), top is the argmax level', () => {
  const answer = ok(normalizeScore(score5, { probabilities: [0.0625, 0.25, 0.375, 0.25, 0.0625] }));
  assert.equal(answer.levels, 5);
  assert.deepEqual(answer.probabilities, [0.0625, 0.25, 0.375, 0.25, 0.0625]);
  assert.equal(answer.expected, 2);
  assert.equal(answer.unit, 0.5);
  assert.equal(answer.top, 2);
  assert.equal(answer.calibrated, true);
});

test('expected falls between levels when the mass is split', () => {
  const answer = ok(normalizeScore(score5, { probabilities: [0, 0.25, 0, 0.75, 0] }));
  assert.equal(answer.expected, 2.5);
  assert.equal(answer.unit, 0.625);
  assert.equal(answer.top, 3);
});

test('a three-level rubric: [0.5, 0.25, 0.25] -> expected 0.75, unit 0.375, top 0', () => {
  const answer = ok(normalizeScore(score3, { probabilities: [0.5, 0.25, 0.25] }));
  assert.equal(answer.expected, 0.75);
  assert.equal(answer.unit, 0.375);
  assert.equal(answer.top, 0);
});

test('the vendor score within 0.01 of ours adds nothing; beyond it, vendor_expected carries it and ours stands', () => {
  const close = ok(normalizeScore(score3, { score: 0.755, probabilities: [0.5, 0.25, 0.25] }));
  assert.equal('vendor_expected' in close, false);
  const far = ok(normalizeScore(score3, { score: 1.2, probabilities: [0.5, 0.25, 0.25] }));
  assert.equal(far.expected, 0.75);
  assert.equal(far.vendor_expected, 1.2);
});

test('vendor confidence passes through and is not the top probability', () => {
  const answer = ok(normalizeScore(score3, { confidence: 0.43, probabilities: [0.5, 0.25, 0.25] }));
  assert.equal(answer.vendor_confidence, 0.43);
  assert.equal(ok(normalizeScore(score3, { probabilities: [0.5, 0.25, 0.25] })).vendor_confidence, null);
});

// --- Score: keyings ----------------------------------------------------------

test('probabilities keyed by level index are ordered lowest to highest; a missing level is 0', () => {
  const answer = ok(normalizeScore(score3, { probabilities: { 2: 0.25, 0: 0.75 } }));
  assert.deepEqual(answer.probabilities, [0.75, 0, 0.25]);
});

test('probabilities keyed by the request criteria labels map to their levels', () => {
  const answer = ok(normalizeScore(score5, { probabilities: { critical: 0.5, none: 0.25, medium: 0.25 } }));
  assert.deepEqual(answer.probabilities, [0.25, 0, 0.25, 0, 0.5]);
  assert.equal(answer.expected, 2.5);
});

test('probabilities keyed by the vendor legend map through its positions (array or index object)', () => {
  const legend = ['L-none', 'L-maybe', 'L-yes'];
  const fromArray = ok(normalizeScore(score3, { legend, probabilities: { 'L-yes': 0.5, 'L-none': 0.5 } }));
  assert.deepEqual(fromArray.probabilities, [0.5, 0, 0.5]);
  const fromObject = ok(normalizeScore(score3, { legend: { 0: 'L-none', 1: 'L-maybe', 2: 'L-yes' }, probabilities: { 'L-maybe': 1 } }));
  assert.deepEqual(fromObject.probabilities, [0, 1, 0]);
});

test('a keying that maps onto no level, or an array of the wrong length, is malformed', () => {
  isMalformed(normalizeScore(score3, { probabilities: { 3: 1 } }), /do not map/);
  isMalformed(normalizeScore(score3, { probabilities: { high: 1 } }), /do not map/);
  isMalformed(normalizeScore(score3, { probabilities: [0.5, 0.5] }), /do not map/);
  isMalformed(normalizeScore(score3, { probabilities: {} }), /do not map/);
});

test('a probability outside [0, 1] or an all-zero distribution is malformed', () => {
  isMalformed(normalizeScore(score3, { probabilities: [1.5, 0, 0] }), /outside/);
  isMalformed(normalizeScore(score3, { probabilities: [-0.1, 0.6, 0.5] }), /outside/);
  isMalformed(normalizeScore(score3, { probabilities: [0, 0, 0] }), /all zero/);
});

test('with no probabilities but a vendor score: probabilities null, expected = the score, uncalibrated', () => {
  const answer = ok(normalizeScore(score5, { score: 1.6, confidence: 0.4 }));
  assert.deepEqual(answer, { type: 'score', levels: 5, vendor_confidence: 0.4, probabilities: null, expected: 1.6, unit: 0.4, top: null, calibrated: false });
  assert.equal(ok(normalizeScore(score5, 3)).expected, 3);
  isMalformed(normalizeScore(score5, { score: 7 }), /neither probabilities nor a score in range/);
  isMalformed(normalizeScore(score5, {}), /neither/);
});

// --- Renormalization ---------------------------------------------------------

test('a distribution summing within 0.98..1.02 is renormalized to 1 and stays calibrated', () => {
  const high = ok(normalizeScore(score3, { probabilities: [0.5, 0.26, 0.25] }));
  near(high.probabilities.reduce((a, b) => a + b, 0), 1);
  near(high.probabilities[0], 0.5 / 1.01);
  assert.equal(high.calibrated, true);
  const edge = ok(normalizeScore(score3, { probabilities: [0.49, 0.49, 0] }));
  assert.equal(edge.calibrated, true);
  near(edge.probabilities[0], 0.5);
});

test('outside the band, probabilities are kept as received and marked uncalibrated', () => {
  const answer = ok(normalizeScore(score3, { probabilities: [0.5, 0.25, 0.22] }));
  assert.deepEqual(answer.probabilities, [0.5, 0.25, 0.22]);
  assert.equal(answer.calibrated, false);
  near(answer.expected, (0.25 + 0.44) / 0.97);
});

// --- Choice ------------------------------------------------------------------

test('a choice answer keeps the probabilities per option and picks the top', () => {
  const answer = ok(normalizeChoice(choice, { choice: 'billing', confidence: 0.91, probabilities: { billing: 0.75, technical: 0.25 } }));
  assert.deepEqual(answer, {
    type: 'choice',
    vendor_confidence: 0.91,
    probabilities: { billing: 0.75, technical: 0.25, sales: 0 },
    top: 'billing',
    calibrated: true,
  });
});

test('choice probabilities given as an array follow the request option order', () => {
  const answer = ok(normalizeChoice(choice, { probabilities: [0.25, 0.5, 0.25] }));
  assert.deepEqual(answer.probabilities, { billing: 0.25, technical: 0.5, sales: 0.25 });
  assert.equal(answer.top, 'technical');
  isMalformed(normalizeChoice(choice, { probabilities: [0.5, 0.5] }), /2 probabilities for 3 options/);
});

test('our argmax wins over a disagreeing vendor choice, which rides along as vendor_choice', () => {
  const answer = ok(normalizeChoice(choice, { choice: 'sales', probabilities: { billing: 0.75, sales: 0.25 } }));
  assert.equal(answer.top, 'billing');
  assert.equal(answer.vendor_choice, 'sales');
});

test('a probability for an option not asked is malformed', () => {
  isMalformed(normalizeChoice(choice, { probabilities: { billing: 0.5, legal: 0.5 } }), /option not asked: "legal"/);
});

test('a choice with only a known label is uncalibrated; an unknown label is malformed', () => {
  assert.deepEqual(ok(normalizeChoice(choice, 'sales')), { type: 'choice', vendor_confidence: null, probabilities: null, top: 'sales', calibrated: false });
  isMalformed(normalizeChoice(choice, { choice: 'legal' }), /neither probabilities nor a known choice/);
});

// --- Noul --------------------------------------------------------------------

test('noul reads a probability of true from every documented-or-plausible shape', () => {
  for (const shape of [0.75, { probability: 0.75 }, { p_true: 0.75 }, { value: 0.75 }, { probabilities: { true: 0.75, false: 0.25 } }, { probabilities: { true: 0.75 } }, { probabilities: { false: 0.25 } }]) {
    const answer = ok(normalizeNoul(shape));
    assert.equal(answer.p_true, 0.75, JSON.stringify(shape));
    assert.equal(answer.calibrated, true);
  }
});

test('a true/false pair outside the band is kept and marked uncalibrated', () => {
  const answer = ok(normalizeNoul({ probabilities: { true: 0.5, false: 0.3 } }));
  assert.equal(answer.p_true, 0.5);
  assert.equal(answer.calibrated, false);
});

test('a bare boolean is a label with p_true null, never a 0/1 sentinel', () => {
  assert.deepEqual(ok(normalizeNoul({ value: true })), { type: 'noul', vendor_confidence: null, p_true: null, value: true, calibrated: false });
  assert.equal(ok(normalizeNoul(false)).p_true, null);
});

test('noul reads the reference SystemOne shape { noul } (Issue#513)', () => {
  // Cloudflare's joint_schema_model.py systemone_answer at clef-flash 8b2e5fd.
  const answer = ok(normalizeNoul({ type: 'noul', noul: 0.9 }));
  near(answer.p_true, 0.9);
  assert.equal(answer.calibrated, true);
});

test('noul passes vendor confidence through', () => {
  assert.equal(ok(normalizeNoul({ probability: 0.83, confidence: 0.2 })).vendor_confidence, 0.2);
  assert.equal(ok(normalizeNoul(0.83)).vendor_confidence, null);
});

test('a noul answer with no readable probability, or one outside [0, 1], is malformed', () => {
  isMalformed(normalizeNoul('yes'), /no probability/);
  isMalformed(normalizeNoul({ answer: 0.5 }), /no probability/);
  isMalformed(normalizeNoul(1.2), /outside/);
  isMalformed(normalizeNoul({ probabilities: { true: 'high' } }), /no probability/);
});

// --- The decision ------------------------------------------------------------

test('every question is normalized, in the request order', () => {
  const questions = { urgency: score3, team: choice, spam: { type: 'noul', instructions: 'Spam?' } };
  const verdict = normalizeAnswers(questions, { spam: 0.25, team: { probabilities: { sales: 1 } }, urgency: { probabilities: [0, 0, 1] } });
  assert.equal(verdict.ok, true);
  assert.deepEqual(Object.keys(verdict.answers), ['urgency', 'team', 'spam']);
  assert.equal(verdict.answers.urgency.expected, 2);
  assert.equal(verdict.answers.team.top, 'sales');
  assert.equal(verdict.answers.spam.p_true, 0.25);
});

test('a question with no answer makes the whole decision malformed', () => {
  const questions = { a: { type: 'noul', instructions: 'x' }, b: { type: 'noul', instructions: 'y' } };
  isMalformed(normalizeAnswers(questions, { a: 0.5 }), /no answer for question "b"/);
  isMalformed(normalizeAnswers(questions, { a: 0.5, b: null }), /no answer for question "b"/);
});

test('one unreadable answer makes the whole decision malformed, naming the question', () => {
  isMalformed(normalizeAnswers({ a: score3 }, { a: { probabilities: { nope: 1 } } }), /question "a":/);
});

test('a question id of __proto__ is kept as an own answer, not swallowed by the prototype', () => {
  const questions = JSON.parse('{"__proto__": {"type": "noul", "instructions": "Is it?"}}');
  const verdict = normalizeAnswers(questions, JSON.parse('{"__proto__": 0.75}'));
  assert.equal(verdict.ok, true);
  assert.deepEqual(Object.keys(verdict.answers), ['__proto__']);
  assert.equal(JSON.parse(JSON.stringify(verdict.answers)).__proto__.p_true, 0.75);
});
