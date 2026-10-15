// test/decide_schema.test.mjs -- decide: local validation of a record
// before any network call (lib/decide/schema.mjs). Values only; no fakes.
// Run: node --test test/decide_schema.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LIMITS, validateRecord } from '../lib/decide/schema.mjs';

const noul = { type: 'noul', instructions: 'Is it spam?' };
const options = (n) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`o${i}`, `option ${i}`]));
const levels = (n) => Array.from({ length: n }, (_, i) => `level ${i}`);
const questions = (n) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`q${i}`, noul]));
const record = (over) => ({ state: 'a message', questions: { spam: noul }, ...over });

const accepts = (r) => assert.equal(validateRecord(r).ok, true, JSON.stringify(validateRecord(r)));
const rejects = (r, pattern) => {
  const verdict = validateRecord(r);
  assert.equal(verdict.ok, false);
  assert.match(verdict.message, pattern);
};

test('a valid record yields exactly the request the model is sent, without the id', () => {
  const verdict = validateRecord(record({ id: 'row-7', images: ['iVBORw0KGgo='], extra: 'ignored' }));
  assert.deepEqual(verdict, {
    ok: true,
    id: 'row-7',
    request: { state: 'a message', questions: { spam: noul }, images: ['iVBORw0KGgo='] },
  });
});

test('the id passes through whatever its JSON type, and is null when absent', () => {
  assert.deepEqual(validateRecord(record({ id: { row: 3 } })).id, { row: 3 });
  assert.equal(validateRecord(record()).id, null);
  assert.equal(validateRecord(record({ id: 0 })).id, 0);
});

test('a structured state is accepted; a missing or blank one is rejected', () => {
  accepts(record({ state: { subject: 'hi', body: 'there' } }));
  rejects(record({ state: undefined }), /no state/);
  rejects(record({ state: null }), /no state/);
  rejects(record({ state: '   ' }), /no state/);
});

test('a record that is not an object is rejected with a null id', () => {
  for (const bad of [null, [], 'text', 3]) {
    const verdict = validateRecord(bad);
    assert.equal(verdict.ok, false);
    assert.equal(verdict.id, null);
  }
});

test('questions: 1 and 64 are accepted, 0 and 65 are rejected', () => {
  accepts(record({ questions: questions(LIMITS.questionsMin) }));
  accepts(record({ questions: questions(LIMITS.questionsMax) }));
  rejects(record({ questions: {} }), /0 questions/);
  rejects(record({ questions: questions(65) }), /65 questions/);
  rejects(record({ questions: [noul] }), /questions must be an object/);
});

test('question ids: 100 characters of [A-Za-z0-9_.-] pass; 101, empty-safe and other characters fail', () => {
  accepts(record({ questions: { ['a'.repeat(100)]: noul } }));
  accepts(record({ questions: { 'A.b_c-9': noul } }));
  rejects(record({ questions: { ['a'.repeat(101)]: noul } }), /does not match/);
  rejects(record({ questions: { 'has space': noul } }), /does not match/);
  rejects(record({ questions: { 'q/1': noul } }), /does not match/);
});

test('an unknown type, a non-object question and missing instructions are rejected', () => {
  rejects(record({ questions: { q: { type: 'yesno', instructions: 'x' } } }), /type "yesno"/);
  rejects(record({ questions: { q: 'Is it spam?' } }), /not an object/);
  rejects(record({ questions: { q: { type: 'noul' } } }), /no instructions/);
  rejects(record({ questions: { q: { type: 'noul', instructions: '' } } }), /no instructions/);
});

test('noul needs no criteria', () => {
  accepts(record({ questions: { q: { type: 'noul', instructions: 'x' } } }));
});

test('choice: 2 and 255 options pass; 1 and 256 fail; criteria must be an object of strings', () => {
  const choice = (criteria) => record({ questions: { q: { type: 'choice', instructions: 'Which team?', criteria } } });
  accepts(choice(options(LIMITS.choiceMin)));
  accepts(choice(options(LIMITS.choiceMax)));
  rejects(choice(options(1)), /1 options/);
  rejects(choice(options(256)), /256 options/);
  rejects(choice(['billing', 'technical']), /criteria as an object/);
  rejects(choice(undefined), /criteria as an object/);
  rejects(choice({ billing: 'money', technical: 3 }), /"technical" needs a string description/);
});

test('score: 2 and 10 levels pass; 1 and 11 fail; criteria must be an array of strings', () => {
  const score = (criteria) => record({ questions: { q: { type: 'score', instructions: 'How urgent?', criteria } } });
  accepts(score(levels(LIMITS.scoreMin)));
  accepts(score(levels(LIMITS.scoreMax)));
  rejects(score(levels(1)), /1 levels/);
  rejects(score(levels(11)), /11 levels/);
  rejects(score({ low: 'a', high: 'b' }), /array of level descriptions/);
  rejects(score(['low', 2]), /must all be strings/);
});

test('images: 4 pass, 5 fail; each must be a non-empty base64 string, not a URL', () => {
  accepts(record({ images: ['a', 'b', 'c', 'd'] }));
  rejects(record({ images: ['a', 'b', 'c', 'd', 'e'] }), /5 images/);
  rejects(record({ images: 'abc' }), /must be an array/);
  rejects(record({ images: [''] }), /non-empty base64/);
  rejects(record({ images: ['https://example.com/a.png'] }), /not URLs/);
});
