// code-points.test.ts -- contract v1 README, "Framing": string lengths in the
// schema count Unicode code points (a JS runtime counts [...s].length, not
// s.length). No golden file exercises this, so these cases are synthetic.

import { describe, expect, it } from 'vitest';
import { MessageSchema } from '../../../src/wire/messages.js';

// --- Constants ---

/** One astral code point: two UTF-16 code units. */
const ASTRAL = '\u{1F516}';

// --- Builders ---

function ingestTitled(title: string): unknown {
  return {
    v: 1,
    type: 'ingest',
    id: 'req-1',
    bookmark: { node_id: '42', url: 'https://example.com/', title, path: { root: 'bar', names: ['Follow Up'] }, date_added: 0 },
    backfill: false,
  };
}

function searchFor(query: string): unknown {
  return { v: 1, type: 'search', id: 'req-2', query };
}

// --- Tests ---

describe('string length limits count code points', () => {
  it('Given a title of 4096 astral code points (8192 UTF-16 units), When parsed, Then it is within the Title cap and accepted', () => {
    expect(MessageSchema.safeParse(ingestTitled(ASTRAL.repeat(4096))).success).toBe(true);
  });

  it('Given a title of 4097 astral code points, When parsed, Then it is over the Title cap and rejected', () => {
    expect(MessageSchema.safeParse(ingestTitled(ASTRAL.repeat(4097))).success).toBe(false);
  });

  it('Given a query of 1024 astral code points, When parsed, Then it is accepted; at 1025 it is rejected', () => {
    expect(MessageSchema.safeParse(searchFor(ASTRAL.repeat(1024))).success).toBe(true);
    expect(MessageSchema.safeParse(searchFor(ASTRAL.repeat(1025))).success).toBe(false);
  });

  it('Given a one-code-point non-empty field made of one astral character, When parsed, Then minimum lengths count it as one', () => {
    expect(MessageSchema.safeParse(searchFor(ASTRAL)).success).toBe(true);
  });
});
