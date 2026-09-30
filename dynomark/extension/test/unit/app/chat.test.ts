// chat.test.ts -- the extension half of the chat (design, Behaviors rows "A
// question is answered with citations", "An out-of-corpus URL is marked", "A
// placement is explained"; "The extension": Chat surface sends Questions to
// the background and renders Answers, Citations, "file this" and "why
// here"). The grounding itself is the daemon's `ask`; the extension sends the
// question with its history, and files a URL by adding it to Follow Up.

import { describe, expect, it } from 'vitest';
import { askQuestion, explainPlacement, fileThis } from '../../../src/app/chat.js';
import { DaemonError } from '../../../src/app/errors.js';
import type { Answer } from '../../../src/domain/chat.js';
import type { PlacementReason } from '../../../src/domain/diff.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeBookmarkTree } from '../../fakes/FakeBookmarkTree.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';
import { FOLLOW_UP, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

const ANSWER: Answer = {
  text: 'The Tokio tutorial covers cancellation.',
  citations: [{ identity: 'https://tokio.rs/tokio/tutorial', title: 'Tokio tutorial', path: { root: 'bar', names: ['Dynomark', 'Rust'] } }],
  external_urls: ['https://rust-lang.github.io/async-book/'],
};

const REASON: PlacementReason = {
  identity: 'https://tokio.rs/tokio/tutorial',
  folder: { root: 'bar', names: ['Dynomark', 'Rust'] },
  neighbours: [],
  rationale: 'Rust async runtime docs.',
  feedback_ids: ['fb-1'],
  model_id: 'ollama:qwen2.5:7b-instruct',
  created_at: 1_790_000_030_000,
};

function daemon(r: RequestMessage): ResponseMessage {
  if (r.type === 'ask') return { v: 1, type: 'ask.result', re: r.id, answer: ANSWER };
  if (r.type === 'placement.explain') {
    return r.identity === REASON.identity
      ? { v: 1, type: 'placement.explain.result', re: r.id, reason: REASON }
      : { v: 1, type: 'error', re: r.id, code: 'not_found', message: 'no such entry' };
  }
  throw new Error(`unexpected ${r.type}`);
}

function talk() {
  const transport = new FakeTransport();
  transport.autoAnswer(daemon);
  return { transport, ids: new SequentialIdSource() };
}

// --- Tests ---

describe('askQuestion(question, history, { transport, ids })', () => {
  it('Given a question and earlier turns, When asked, Then ask carries the trimmed question and the history, and the answer comes back as sent', async () => {
    const deps = talk();
    const answer = await askQuestion('  how do I cancel?  ', [{ question: 'tokio?', answer: 'One tutorial.' }], deps);
    expect(answer).toEqual(ANSWER);
    const [sent] = deps.transport.sent;
    expect(sent).toMatchObject({ type: 'ask', question: 'how do I cancel?', history: [{ question: 'tokio?', answer: 'One tutorial.' }] });
  });

  it('Given a blank question, When asked, Then it is refused and nothing is sent', async () => {
    const deps = talk();
    await expect(askQuestion('   ', [], deps)).rejects.toThrow(/empty/);
    expect(deps.transport.sent).toEqual([]);
  });
});

describe('explainPlacement(identity, { transport, ids }) -- "why here"', () => {
  it('Given a filed entry, When explained, Then placement.explain names its identity and the reason comes back', async () => {
    const deps = talk();
    expect(await explainPlacement(REASON.identity, deps)).toEqual(REASON);
    expect(deps.transport.sent[0]).toMatchObject({ type: 'placement.explain', identity: REASON.identity });
  });

  it('Given an identity the daemon does not know, When explained, Then the refusal is a DaemonError with its code', async () => {
    await expect(explainPlacement('https://unknown.example/', talk())).rejects.toMatchObject({ name: DaemonError.name, code: 'not_found' });
  });
});

describe('fileThis(url, title, followUp, { tree }) -- "file this" adds the URL to Follow Up', () => {
  it('Given an external URL, When filed, Then a bookmark with exactly that URL is created in Follow Up', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const ids = await seedOwnedTree(tree);
    const filed = await fileThis('https://rust-lang.github.io/async-book/', 'Async book', FOLLOW_UP, { tree });
    expect(filed.created).toBe(true);
    expect(await tree.getNode(filed.node_id)).toMatchObject({
      parent_id: ids.followUp,
      kind: 'bookmark',
      url: 'https://rust-lang.github.io/async-book/',
      title: 'Async book',
    });
  });

  it('Given the URL is already in Follow Up, When filed again, Then no second bookmark is made', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const ids = await seedOwnedTree(tree);
    const first = await fileThis('https://rust-lang.github.io/async-book/', 'Async book', FOLLOW_UP, { tree });
    const second = await fileThis('https://rust-lang.github.io/async-book/', 'Async book', FOLLOW_UP, { tree });
    expect(second).toEqual({ node_id: first.node_id, created: false });
    expect(await tree.getChildren(ids.followUp)).toHaveLength(2);
  });

  it('Given no title, When filed, Then the URL is the title', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    await seedOwnedTree(tree);
    const filed = await fileThis('https://serde.rs/', '  ', FOLLOW_UP, { tree });
    expect((await tree.getNode(filed.node_id))?.title).toBe('https://serde.rs/');
  });

  it('Given a URL that is not http(s), When filed, Then it is refused and the tree is unchanged', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const ids = await seedOwnedTree(tree);
    await expect(fileThis('javascript:alert(1)', 'x', FOLLOW_UP, { tree })).rejects.toThrow(/http/);
    expect(await tree.getChildren(ids.followUp)).toHaveLength(1);
  });
});
