// well-formed.test.ts -- contract v1 README, "Framing": every string on the
// wire is a sequence of Unicode scalar values; a frame with a lone UTF-16
// surrogate, escaped or not, is invalid.

import { describe, expect, it } from 'vitest';
import { MessageSchema } from '../../../src/wire/messages.js';

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

// --- Tests ---

describe('wire strings are well-formed', () => {
  it('Given a title cut mid-emoji (a lone high surrogate), When parsed, Then the message is rejected', () => {
    expect(MessageSchema.safeParse(ingestTitled('Tokio \uD83D')).success).toBe(false);
  });

  it('Given a JSON frame carrying an escaped lone low surrogate in a folder name, When parsed, Then it is rejected', () => {
    const frame = JSON.parse(
      '{"v":1,"type":"hello","id":"req-1","profile_id":"p-1","follow_up":{"root":"bar","names":["Follow \\udc00Up"]}}',
    ) as unknown;
    expect(MessageSchema.safeParse(frame).success).toBe(false);
  });

  it('Given a title holding a complete surrogate pair, When parsed, Then it is accepted', () => {
    expect(MessageSchema.safeParse(ingestTitled('Tokio 🔖')).success).toBe(true);
  });
});
