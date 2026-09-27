// runtime.chat.test.ts -- what the chat page asks the background for (design,
// "The extension": Chat surface -- a view, not a composition root: it sends
// Questions to the background and renders Answers, Citations, "file this" and
// "why here"; conversation state lives in the page). A citation opens in one
// click; only http(s) URLs are ever opened.

import { describe, expect, it } from 'vitest';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { scriptDaemon, sentOf, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

const CITED = { identity: 'https://tokio.rs/tokio/tutorial', title: 'Tokio tutorial', path: { root: 'bar' as const, names: ['Dynomark'] } };

function answers(r: RequestMessage): ResponseMessage | undefined {
  if (r.type === 'ask') {
    return {
      v: 1,
      type: 'ask.result',
      re: r.id,
      answer: { text: 'See the tutorial.', citations: [CITED], external_urls: ['https://async.example/'] },
    };
  }
  if (r.type === 'placement.explain') {
    return {
      v: 1,
      type: 'placement.explain.result',
      re: r.id,
      reason: {
        identity: CITED.identity,
        folder: CITED.path,
        neighbours: [],
        rationale: 'Async runtime docs.',
        feedback_ids: [],
        model_id: 'm',
        created_at: 1,
      },
    };
  }
  return undefined;
}

async function setup(): Promise<{ w: FakeExtensionWorld; runtime: ExtensionRuntime }> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w, {}, answers);
  return { w, runtime: await startRuntime(w) };
}

// --- Tests ---

describe('Chat page -- ask and why here', () => {
  it('Given a question with history, When the page asks, Then ask is sent and the answer comes back with citations and external urls', async () => {
    const { w, runtime } = await setup();
    const page = await runtime.page({ kind: 'ask', question: 'cancel?', history: [{ question: 'q', answer: 'a' }] });
    expect(page).toEqual({
      ok: true,
      kind: 'ask',
      answer: { text: 'See the tutorial.', citations: [CITED], external_urls: ['https://async.example/'] },
    });
    expect(sentOf(w, 'ask')[0]).toMatchObject({ question: 'cancel?', history: [{ question: 'q', answer: 'a' }] });
  });

  it('Given a citation, When "why here" is pressed, Then placement.explain is sent and the reason comes back', async () => {
    const { w, runtime } = await setup();
    const page = await runtime.page({ kind: 'explain', identity: CITED.identity });
    expect(page).toMatchObject({ ok: true, kind: 'explain', reason: { rationale: 'Async runtime docs.' } });
    expect(sentOf(w, 'placement.explain')[0]?.identity).toBe(CITED.identity);
  });
});

describe('Chat page -- open a citation, file an external url', () => {
  it('Given a citation, When it is clicked, Then its identity opens in a new foreground tab', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'open', url: CITED.identity })).toEqual({ ok: true, kind: 'open' });
    expect(w.navigator.opened).toEqual([{ url: CITED.identity, disposition: 'newForegroundTab' }]);
  });

  it('Given a url that is not http(s), When the page asks to open it, Then nothing opens and the page is told why', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'open', url: 'javascript:alert(1)' })).toMatchObject({ ok: false });
    expect(w.navigator.opened).toEqual([]);
  });

  it('Given an external url, When "file this" is pressed, Then it is added to the watched Follow Up folder', async () => {
    const { w, runtime } = await setup();
    const page = await runtime.page({ kind: 'file', url: 'https://async.example/', title: 'Async' });
    expect(page).toMatchObject({ ok: true, kind: 'file', created: true });
    const tree = await w.tree.readTree();
    const followUp = tree.nodes.find((n) => n.kind === 'folder' && n.title === 'Follow Up');
    expect(tree.nodes.filter((n) => n.parent_id === followUp?.id).map((n) => (n.kind === 'bookmark' ? n.url : ''))).toEqual([
      'https://async.example/',
    ]);
  });
});
