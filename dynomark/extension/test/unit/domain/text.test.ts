// text.test.ts -- the extension makes every string well-formed before sending
// (contract v1 README, "Framing": String.prototype.toWellFormed semantics,
// lone surrogates -> U+FFFD).

import { describe, expect, it } from 'vitest';
import { isWellFormed, toWellFormed } from '../../../src/domain/text.js';

describe('toWellFormed', () => {
  it('Given a title cut mid-emoji, When made well-formed, Then the lone surrogate becomes U+FFFD and the rest is kept', () => {
    expect(toWellFormed('Tokio \uD83D')).toBe('Tokio �');
    expect(toWellFormed('\uDC00a\uD800')).toBe('�a�');
  });

  it('Given a string of complete surrogate pairs and BMP text, When made well-formed, Then it is unchanged', () => {
    const s = 'café 🔖🔖';
    expect(toWellFormed(s)).toBe(s);
    expect(isWellFormed(s)).toBe(true);
  });

  it('Given any lone surrogate, When checked, Then the string is not well-formed, and its well-formed form is', () => {
    for (const s of ['\uD800', '\uDFFF', 'a\uDBFFb', '\uDC00\uD800']) {
      expect(isWellFormed(s)).toBe(false);
      expect(isWellFormed(toWellFormed(s))).toBe(true);
    }
  });
});
