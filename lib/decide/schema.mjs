// lib/decide/schema.mjs -- decide: the record a caller sends (state,
// questions, images, id) and the local validation that runs before any
// network call (docs/ops/decide.md, "Usage").
//
// A record is { state, questions, images?, id? }. `id` is the caller's and
// never reaches the model. Validation mirrors the decision-model limits:
// 1-64 questions, ids ^[A-Za-z0-9_.-]{1,100}$, the three question types
// (noul: yes/no; choice: 2-255 named options; score: a 2-10 level rubric,
// lowest first), at most 4 images.
//
// Pure: values in, values out.

// --- Constants --------------------------------------------------------------

/** The question types a decision model answers. */
export const QUESTION_TYPES = Object.freeze(['noul', 'choice', 'score']);

/** The limits, in one place. */
export const LIMITS = Object.freeze({
  questionsMin: 1,
  questionsMax: 64,
  choiceMin: 2,
  choiceMax: 255,
  scoreMin: 2,
  scoreMax: 10,
  imagesMax: 4,
});

/** A question id. */
export const QUESTION_ID = /^[A-Za-z0-9_.-]{1,100}$/;

// --- Predicates -------------------------------------------------------------

/** A plain JSON object: not null, not an array. */
export const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const isNonEmptyString = (value) => typeof value === 'string' && value.trim() !== '';

/** The state is present: a non-empty string, or any other non-null JSON value. */
export function hasState(record) {
  const { state } = record;
  if (state === undefined || state === null) return false;
  return typeof state === 'string' ? state.trim() !== '' : true;
}

// --- Pure helpers -----------------------------------------------------------

const invalid = (message) => ({ ok: false, message });

/** One question's problem, or null when it is valid. */
export function questionProblem(id, question) {
  if (!QUESTION_ID.test(id)) return `question id "${id.slice(0, 120)}" does not match ${QUESTION_ID.source}`;
  if (!isPlainObject(question)) return `question "${id}" is not an object`;
  if (!QUESTION_TYPES.includes(question.type)) return `question "${id}" has type ${JSON.stringify(question.type)}; expected one of ${QUESTION_TYPES.join(', ')}`;
  if (!isNonEmptyString(question.instructions)) return `question "${id}" has no instructions (a non-empty string)`;
  if (question.type === 'choice') return choiceProblem(id, question.criteria);
  if (question.type === 'score') return scoreProblem(id, question.criteria);
  return null;
}

function choiceProblem(id, criteria) {
  if (!isPlainObject(criteria)) return `choice question "${id}" needs criteria as an object of {option: description}`;
  const options = Object.keys(criteria);
  if (options.length < LIMITS.choiceMin || options.length > LIMITS.choiceMax) {
    return `choice question "${id}" has ${options.length} options; allowed ${LIMITS.choiceMin}-${LIMITS.choiceMax}`;
  }
  const bad = options.find((option) => option === '' || typeof criteria[option] !== 'string');
  if (bad !== undefined) return `choice question "${id}" option "${bad}" needs a string description`;
  return null;
}

function scoreProblem(id, criteria) {
  if (!Array.isArray(criteria)) return `score question "${id}" needs criteria as an array of level descriptions, lowest first`;
  if (criteria.length < LIMITS.scoreMin || criteria.length > LIMITS.scoreMax) {
    return `score question "${id}" has ${criteria.length} levels; allowed ${LIMITS.scoreMin}-${LIMITS.scoreMax}`;
  }
  if (!criteria.every((level) => typeof level === 'string')) return `score question "${id}" levels must all be strings`;
  return null;
}

/** The image types Clef accepts (Cloudflare's published Clef schema). */
const IMAGE_TYPES = Object.freeze(['image/png', 'image/jpeg', 'image/webp']);
/** A base64 data URL: the schema's string form, matched case-insensitively. */
const DATA_URL = /^data:/i;

/** One image in either form the schema allows: a data: URL, or
 * { content_type, base64 }. Returns a problem or null. */
function imageProblem(image) {
  if (typeof image === 'string') {
    return DATA_URL.test(image) ? null : 'a string image must be a data: URL (data:image/png;base64,...); raw base64 and remote URLs are refused';
  }
  if (!isPlainObject(image) || !isNonEmptyString(image.content_type) || !isNonEmptyString(image.base64)) {
    return 'an object image needs non-empty content_type and base64';
  }
  return IMAGE_TYPES.includes(image.content_type) ? null : 'an image content_type must be image/png, image/jpeg or image/webp';
}

function imagesProblem(images) {
  if (images === undefined) return null;
  if (!Array.isArray(images)) return 'images must be an array of data: URLs or {content_type, base64} objects';
  if (images.length > LIMITS.imagesMax) return `${images.length} images; at most ${LIMITS.imagesMax} allowed`;
  for (const image of images) {
    const problem = imageProblem(image);
    if (problem) return problem;
  }
  return null;
}

/**
 * Validate one record. Returns { ok: true, id, request } where request is
 * { state, questions, images? } (exactly what the model is sent, in the
 * caller's key order), or { ok: false, id, message }.
 */
export function validateRecord(record) {
  if (!isPlainObject(record)) return { ...invalid('a record must be a JSON object'), id: null };
  const id = record.id === undefined ? null : record.id;
  const fail = (message) => ({ ...invalid(message), id });
  if (!hasState(record)) return fail('the record has no state');
  if (!isPlainObject(record.questions)) return fail('questions must be an object of {id: question}');
  const ids = Object.keys(record.questions);
  if (ids.length < LIMITS.questionsMin || ids.length > LIMITS.questionsMax) {
    return fail(`${ids.length} questions; allowed ${LIMITS.questionsMin}-${LIMITS.questionsMax}`);
  }
  for (const qid of ids) {
    const problem = questionProblem(qid, record.questions[qid]);
    if (problem) return fail(problem);
  }
  const imageProblem = imagesProblem(record.images);
  if (imageProblem) return fail(imageProblem);
  const request = { state: record.state, questions: record.questions };
  if (record.images !== undefined) request.images = record.images;
  return { ok: true, id, request };
}
