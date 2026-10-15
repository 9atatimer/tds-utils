// lib/decide/answers.mjs -- decide: turning a backend's answer into the
// normalized decision (docs/ops/decide.md, "The answer").
//
// The published answer shapes are thin (the Workers AI docs show no sample
// response), so every reading here is defensive and the raw answer is kept
// beside the normalized one:
//
//   choice  { choice, confidence, probabilities: { option: p } }
//   score   { score, confidence, legend, probabilities } -- probabilities
//           keyed by level index, by legend label, or as an array; `score`
//           is the vendor's probability-weighted level, 0 = lowest
//   noul    a probability of true: a bare number, { probability },
//           { noul } (the reference SystemOne shape, Issue#513),
//           { probabilities: { true, false } } or { value }
//
// `confidence` is undocumented and is not the top probability: it passes
// through as vendor_confidence and is never used for anything else.
//
// Pure: values in, values out.

import { isPlainObject } from './schema.mjs';

// --- Constants --------------------------------------------------------------

/** A distribution summing within this band is renormalized to 1; outside
 * it, it is kept as received and marked uncalibrated. */
export const SUM_TOLERANCE = 0.02;

/** The vendor's expected score may differ from ours by this much before
 * the output carries vendor_expected. */
export const EXPECTED_TOLERANCE = 0.01;

// --- Predicates -------------------------------------------------------------

/** A probability: a finite number in [0, 1]. */
export const isProbability = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;

const isFiniteNumber = (value) => typeof value === 'number' && Number.isFinite(value);

const isIndexKey = (key, levels) => /^(0|[1-9][0-9]*)$/.test(key) && Number(key) < levels;

// --- Pure helpers: the envelope ---------------------------------------------

const malformed = (message) => ({ ok: false, error: { class: 'malformed', message, status: null } });

/** Answers given as [{ id, ... }] become { id: answer }. */
function answersMap(answers) {
  if (isPlainObject(answers)) return answers;
  if (Array.isArray(answers) && answers.every((a) => isPlainObject(a) && typeof a.id === 'string')) {
    return Object.fromEntries(answers.map((a) => [a.id, a]));
  }
  return null;
}

/**
 * Unwrap a backend's JSON body. Workers AI (direct or through AI Gateway)
 * wraps it: { result: { model, answers, usage }, success, errors, messages };
 * a SystemOne server returns { model, answers, usage }. Returns
 * { ok: true, result, answers } or a malformed failure.
 */
export function unwrapResponse(body) {
  if (!isPlainObject(body)) return malformed('the backend answered with something other than a JSON object');
  const wrapped = isPlainObject(body.result) && ('success' in body || 'errors' in body || !('answers' in body));
  if (wrapped && body.success === false) return malformed('the backend answered success: false');
  const result = wrapped ? body.result : body;
  const answers = answersMap(result.answers);
  if (!answers) return malformed('the backend answer has no answers object');
  return { ok: true, result, answers };
}

// --- Pure helpers: distributions --------------------------------------------

/** Renormalize a list of probabilities when its sum is within tolerance.
 * Returns { values, calibrated }. */
export function renormalize(values) {
  const sum = values.reduce((total, p) => total + p, 0);
  if (sum > 0 && Math.abs(sum - 1) <= SUM_TOLERANCE + 1e-12) return { values: values.map((p) => p / sum), calibrated: true };
  return { values: [...values], calibrated: false };
}

/** The index of the largest value; the lowest index wins a tie. */
export function argmax(values) {
  return values.reduce((best, p, i) => (p > values[best] ? i : best), 0);
}

/** sum(i * p_i), over a distribution scaled to sum to 1 (a mean level even
 * when the received distribution was off). */
export function expectedLevel(values) {
  const sum = values.reduce((total, p) => total + p, 0);
  return values.reduce((total, p, i) => total + i * p, 0) / sum;
}

const vendorConfidence = (answer) => (isPlainObject(answer) && isFiniteNumber(answer.confidence) ? answer.confidence : null);

// --- Pure helpers: score ----------------------------------------------------

/** Order a score answer's probabilities lowest -> highest level, whatever
 * the keying. `labels` is the request's criteria. Returns an array of
 * numbers (missing levels 0), or null when no keying fits. */
export function scoreProbabilities(probabilities, labels, legend) {
  const levels = labels.length;
  if (Array.isArray(probabilities)) return probabilities.length === levels ? probabilities : null;
  if (!isPlainObject(probabilities)) return null;
  const keys = Object.keys(probabilities);
  if (keys.length === 0) return null;
  const byPosition = (positionOf) => {
    const out = new Array(levels).fill(0);
    for (const key of keys) out[positionOf(key)] = probabilities[key];
    return out;
  };
  if (keys.every((key) => isIndexKey(key, levels))) return byPosition(Number);
  const unique = (list) => new Set(list).size === list.length;
  if (unique(labels) && keys.every((key) => labels.includes(key))) return byPosition((key) => labels.indexOf(key));
  const legendLabels = Array.isArray(legend) ? legend : isPlainObject(legend) ? legendArray(legend, levels) : null;
  if (legendLabels && legendLabels.length === levels && unique(legendLabels) && keys.every((key) => legendLabels.includes(key))) {
    return byPosition((key) => legendLabels.indexOf(key));
  }
  return null;
}

/** A legend given as { "0": label, ... } as an array, or null. */
function legendArray(legend, levels) {
  const keys = Object.keys(legend);
  if (keys.length !== levels || !keys.every((key) => isIndexKey(key, levels))) return null;
  return keys.sort((a, b) => Number(a) - Number(b)).map((key) => legend[key]);
}

/** Normalize a score answer against its question. */
export function normalizeScore(question, answer) {
  const levels = question.criteria.length;
  const body = isPlainObject(answer) ? answer : { score: answer };
  const vendorScore = isFiniteNumber(body.score) ? body.score : null;
  const base = { type: 'score', levels, vendor_confidence: vendorConfidence(answer) };
  if (body.probabilities === undefined || body.probabilities === null) {
    if (vendorScore === null || vendorScore < 0 || vendorScore > levels - 1) return malformed('a score answer with neither probabilities nor a score in range');
    return {
      ok: true,
      // No distribution, no mode: rounding an expectation does not find the most
      // probable level (mass on 0 and 2 averages to 1), so top stays null.
      answer: { ...base, probabilities: null, expected: vendorScore, unit: vendorScore / (levels - 1), top: null, calibrated: false },
    };
  }
  const ordered = scoreProbabilities(body.probabilities, question.criteria, body.legend);
  if (!ordered) return malformed(`a score answer whose probabilities do not map onto the ${levels} levels asked`);
  if (!ordered.every(isProbability)) return malformed('a score answer with a probability outside [0, 1]');
  if (ordered.every((p) => p === 0)) return malformed('a score answer whose probabilities are all zero');
  const { values, calibrated } = renormalize(ordered);
  const expected = expectedLevel(values);
  const out = { ...base, probabilities: values, expected, unit: expected / (levels - 1), top: argmax(values), calibrated };
  if (vendorScore !== null && Math.abs(vendorScore - expected) > EXPECTED_TOLERANCE) out.vendor_expected = vendorScore;
  return { ok: true, answer: out };
}

// --- Pure helpers: choice ---------------------------------------------------

/** Normalize a choice answer against its question. */
export function normalizeChoice(question, answer) {
  const options = Object.keys(question.criteria);
  const body = isPlainObject(answer) ? answer : { choice: answer };
  const vendorChoice = typeof body.choice === 'string' ? body.choice : null;
  const base = { type: 'choice', vendor_confidence: vendorConfidence(answer) };
  let received = body.probabilities;
  if (received === undefined || received === null) {
    if (!options.includes(vendorChoice)) return malformed('a choice answer with neither probabilities nor a known choice');
    return { ok: true, answer: { ...base, probabilities: null, top: vendorChoice, calibrated: false } };
  }
  if (Array.isArray(received)) {
    if (received.length !== options.length) return malformed(`a choice answer with ${received.length} probabilities for ${options.length} options`);
    received = Object.fromEntries(options.map((option, i) => [option, received[i]]));
  }
  if (!isPlainObject(received)) return malformed('a choice answer whose probabilities are not an object');
  const unknown = Object.keys(received).find((key) => !options.includes(key));
  if (unknown !== undefined) return malformed(`a choice answer with a probability for an option not asked: "${unknown}"`);
  const ordered = options.map((option) => (received[option] === undefined ? 0 : received[option]));
  if (!ordered.every(isProbability)) return malformed('a choice answer with a probability outside [0, 1]');
  if (ordered.every((p) => p === 0)) return malformed('a choice answer whose probabilities are all zero');
  const { values, calibrated } = renormalize(ordered);
  const top = options[argmax(values)];
  const out = { ...base, probabilities: Object.fromEntries(options.map((option, i) => [option, values[i]])), top, calibrated };
  if (vendorChoice !== null && vendorChoice !== top) out.vendor_choice = vendorChoice;
  return { ok: true, answer: out };
}

// --- Pure helpers: noul -----------------------------------------------------

/** The probability of true from a noul answer, whatever its shape.
 * Returns { p, calibrated } or { label } (a bare boolean) or null. */
export function readNoul(answer) {
  if (isFiniteNumber(answer)) return { p: answer, calibrated: true };
  if (typeof answer === 'boolean') return { label: answer };
  if (!isPlainObject(answer)) return null;
  for (const key of ['p_true', 'probability', 'noul']) {
    if (isFiniteNumber(answer[key])) return { p: answer[key], calibrated: true };
  }
  const pair = answer.probabilities;
  if (isPlainObject(pair) && (pair.true !== undefined || pair.false !== undefined)) {
    const pTrue = pair.true ?? null;
    const pFalse = pair.false ?? null;
    if (pTrue !== null && !isFiniteNumber(pTrue)) return null;
    if (pFalse !== null && !isFiniteNumber(pFalse)) return null;
    if (pTrue !== null && pFalse !== null) {
      const { values, calibrated } = renormalize([pTrue, pFalse]);
      return { p: values[0], calibrated };
    }
    return pTrue !== null ? { p: pTrue, calibrated: true } : { p: 1 - pFalse, calibrated: true };
  }
  if (isFiniteNumber(answer.value)) return { p: answer.value, calibrated: true };
  if (typeof answer.value === 'boolean') return { label: answer.value };
  return null;
}

/** Normalize a noul (yes/no) answer. A bare boolean is a label with no
 * probability: p_true is null, never a 0/1 sentinel that would clear any
 * threshold. */
export function normalizeNoul(answer) {
  const read = readNoul(answer);
  const base = { type: 'noul', vendor_confidence: vendorConfidence(answer) };
  if (!read) return malformed('a noul answer with no probability of true');
  if ('label' in read) return { ok: true, answer: { ...base, p_true: null, value: read.label, calibrated: false } };
  if (!isProbability(read.p)) return malformed('a noul answer whose probability of true is outside [0, 1]');
  return { ok: true, answer: { ...base, p_true: read.p, calibrated: read.calibrated } };
}

// --- Pure helpers: the decision ---------------------------------------------

/** Normalize one answer against the question that asked it. */
export function normalizeAnswer(question, answer) {
  if (question.type === 'score') return normalizeScore(question, answer);
  if (question.type === 'choice') return normalizeChoice(question, answer);
  return normalizeNoul(answer);
}

/**
 * Normalize every answer of a backend's (unwrapped) answers against the
 * questions asked. A question with no answer, or any answer that cannot be
 * read, makes the whole decision malformed. Returns { ok: true, answers }
 * (in the request's question order) or a malformed failure.
 */
export function normalizeAnswers(questions, answers) {
  // Entries, then fromEntries: assigning out[qid] would hand a question id of
  // "__proto__" (legal by the id rule) to the prototype setter and drop it.
  const entries = [];
  for (const [qid, question] of Object.entries(questions)) {
    if (!Object.hasOwn(answers, qid) || answers[qid] === undefined || answers[qid] === null) return malformed(`no answer for question "${qid}"`);
    const normalized = normalizeAnswer(question, answers[qid]);
    if (!normalized.ok) return malformed(`question "${qid}": ${normalized.error.message}`);
    entries.push([qid, normalized.answer]);
  }
  return { ok: true, answers: Object.fromEntries(entries) };
}
