// text.ts -- well-formed strings (contract v1 README, "Framing"). Browser data
// can hold lone UTF-16 surrogates (a title cut mid-emoji); nothing leaves the
// extension, and no title is compared, until it is well-formed.

// --- Constants ---

/** A high surrogate not followed by a low one, or a low surrogate not preceded by a high one. */
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;
const REPLACEMENT_CHARACTER = '�';

// --- Predicates ---

/** True when the string is a sequence of Unicode scalar values (no lone surrogate). */
export function isWellFormed(s: string): boolean {
  return s.match(LONE_SURROGATE) === null;
}

// --- Pure helpers ---

/** The string with every lone surrogate replaced by U+FFFD (String.prototype.toWellFormed semantics). */
export function toWellFormed(s: string): string {
  return s.replace(LONE_SURROGATE, REPLACEMENT_CHARACTER);
}
