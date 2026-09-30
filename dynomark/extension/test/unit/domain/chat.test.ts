// chat.test.ts -- the conversation the chat page keeps and sends as history
// (design, "Turn / Question / Answer / Citation"; contract v1, "Size limits":
// ask.question 1 to 8,192 code points, history at most 50 turns, an answer
// text at most 65,536).

import { describe, expect, it } from 'vitest';
import { askableQuestion, historyFor, withTurn, type Turn } from '../../../src/domain/chat.js';
import { MAX_ANSWER_TEXT, MAX_HISTORY_TURNS, MAX_QUESTION } from '../../../src/domain/limits.js';
import { isWellFormed } from '../../../src/domain/text.js';

// --- Builders ---

function turns(n: number): Turn[] {
  return Array.from({ length: n }, (_, i) => ({ question: `q${i}`, answer: `a${i}` }));
}

// --- Tests ---

describe('askableQuestion', () => {
  it('Given a question with surrounding blanks, When made askable, Then it is trimmed', () => {
    expect(askableQuestion('  why pin?  ')).toBe('why pin?');
  });

  it('Given a blank question, When made askable, Then there is nothing to ask', () => {
    expect(askableQuestion(' \n ')).toBeUndefined();
  });

  it('Given a question over the cap, When made askable, Then it is cut to the cap in code points, never mid-pair', () => {
    const asked = askableQuestion('\u{1F600}'.repeat(MAX_QUESTION + 5)) ?? '';
    expect([...asked]).toHaveLength(MAX_QUESTION);
    expect(isWellFormed(asked)).toBe(true);
  });
});

describe('historyFor -- what a question carries as history', () => {
  it('Given more turns than the cap, When sent, Then only the most recent ones go, oldest first', () => {
    const history = historyFor(turns(MAX_HISTORY_TURNS + 3));
    expect(history).toHaveLength(MAX_HISTORY_TURNS);
    expect(history[0]?.question).toBe('q3');
    expect(history.at(-1)?.question).toBe(`q${MAX_HISTORY_TURNS + 2}`);
  });

  it('Given an answer over the cap and a lone surrogate in a question, When sent, Then each is made well-formed and cut to its cap', () => {
    const [turn] = historyFor([{ question: 'bad \uD800 half', answer: 'x'.repeat(MAX_ANSWER_TEXT + 1) }]);
    expect(turn?.question).toBe('bad � half');
    expect(turn?.answer).toHaveLength(MAX_ANSWER_TEXT);
  });
});

describe('withTurn -- the page appends each exchange', () => {
  it('Given a conversation, When an exchange is added, Then it is last and the earlier ones are unchanged', () => {
    const before = turns(2);
    const after = withTurn(before, { question: 'q2', answer: 'a2' });
    expect(after.map((t) => t.question)).toEqual(['q0', 'q1', 'q2']);
    expect(before).toHaveLength(2);
  });
});
