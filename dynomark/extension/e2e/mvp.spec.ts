/// <reference types="chrome" />
// mvp.spec.ts -- the MVP extension flows end to end in Chromium, against the
// fake native host: an ask round trip through the chat surface (opened from
// the omnibox's Ask fall-through) with "why here", "file this" and a citation
// that opens in one click; a diff proposed, read and accepted one item at a
// time, its batch applied and its state shown, and a folder pinned; the
// writer-conflict banner, with a batch refused while the conflict stands;
// background-tab capture of a save no tab shows (a real page on 127.0.0.1);
// and the settings page's backfill.

import type { Page } from '@playwright/test';
import type { RequestMessage } from '../src/wire/messages.js';
import { serveLocal } from '../test/support/localServer.js';
import { expect, followUpId, ofType, test } from './fixtures.js';

// --- Builders ---

type Ingest = Extract<RequestMessage, { type: 'ingest' }>;
type Receipt = Extract<RequestMessage, { type: 'batch.receipt' }>;

const CITED = {
  identity: 'https://tokio.rs/tokio/tutorial',
  title: 'Tokio tutorial',
  path: { root: 'bar' as const, names: ['Dynomark', 'Rust'] },
};
const EXTERNAL = 'https://rust-lang.github.io/async-book/';

async function bookmarkCount(page: Page, url: string): Promise<number> {
  return page.evaluate(async (u) => (await chrome.bookmarks.search({ url: u })).length, url);
}

// --- Tests ---

test('Given no hit, When the omnibox Enter asks, Then the chat surface opens with the question sent, and its answer offers why here, file this and a one-click citation', async ({
  ext,
}) => {
  ext.daemon.askAnswer = { text: 'The Tokio tutorial covers cancellation.', citations: [CITED], external_urls: [EXTERNAL] };
  ext.daemon.reasons = [
    {
      identity: CITED.identity,
      folder: CITED.path,
      neighbours: [],
      rationale: 'Nearest neighbours are Rust async runtime docs.',
      feedback_ids: [],
      model_id: 'ollama:qwen2.5',
      created_at: 1_790_000_030_000,
    },
  ];
  await ext.daemon.waitFor(ofType('index.pull'));
  const worker = await ext.serviceWorker();
  const opened = ext.context.waitForEvent('page', (p) => p.url().includes('/chat.html'));
  await worker.evaluate(() =>
    (globalThis as unknown as { dynomark: { omniboxEnter(t: string, d: string): Promise<void> } }).dynomark.omniboxEnter(
      'how do I cancel a future',
      'currentTab',
    ),
  );
  const chat = await opened;
  expect(new URL(chat.url()).searchParams.get('q')).toBe('how do I cancel a future');
  expect(await ext.daemon.waitFor(ofType('ask'))).toMatchObject({ question: 'how do I cancel a future', history: [] });
  await expect(chat.locator('.answer-text').first()).toHaveText('The Tokio tutorial covers cancellation.');
  await expect(chat.locator('li.external').first()).toContainText('external');
  await expect(chat.locator('#model')).toContainText('llama3.1:8b (local)');

  await chat.locator(`button[data-explain="${CITED.identity}"]`).click();
  expect(await ext.daemon.waitFor(ofType('placement.explain'))).toMatchObject({ identity: CITED.identity });
  await expect(chat.locator('.reason').first()).toContainText('Rust async runtime docs');

  const from = ext.daemon.received.length;
  await chat.locator(`button[data-file="${EXTERNAL}"]`).click();
  const ingest = (await ext.daemon.waitFor((r) => r.type === 'ingest' && r.bookmark.url === EXTERNAL, { from })) as Ingest;
  expect(ingest.bookmark.path).toEqual({ root: 'bar', names: ['Follow Up'] });
  await expect(chat.locator('#message')).toContainText('Follow Up');

  await chat.locator('#question').fill('and select?');
  await chat.locator('#ask').click();
  const second = (await ext.daemon.waitFor((r) => r.type === 'ask' && r.question === 'and select?')) as Extract<
    RequestMessage,
    { type: 'ask' }
  >;
  expect(second.history).toEqual([{ question: 'how do I cancel a future', answer: 'The Tokio tutorial covers cancellation.' }]);
  await expect(chat.locator('.answer-text')).toHaveCount(2);

  const closed = chat.waitForEvent('close');
  await chat.locator(`button[data-open="${CITED.identity}"]`).first().click();
  await closed;
  const page = await ext.extensionPage('history.html');
  await expect
    .poll(() => page.evaluate(async () => (await chrome.tabs.query({})).map((t) => t.url ?? t.pendingUrl)))
    .toContain(CITED.identity);
});

test('Given an audit diff, When it is proposed, read and one item accepted in the diff view, Then its batch is applied across the boundary and the item shows APPLIED; a folder can be pinned', async ({
  ext,
}) => {
  ext.daemon.diffs = [{ diff_id: 'diff-2', kind: 'audit', proposed_at: 1_790_000_090_000, item_count: 0, unaccepted_count: 0 }];
  ext.daemon.diffItems = [
    {
      item_id: 'item-3',
      diff_id: 'diff-2',
      action: 'add',
      description: 'Add The Rust Book to your bar folder Reading',
      operations: [
        { op: 'create_folder', index: 0, parent: { root: 'bar', names: [] }, title: 'Reading' },
        {
          op: 'create',
          index: 1,
          parent: { root: 'bar', names: ['Reading'] },
          title: 'The Rust Book',
          url: 'https://doc.rust-lang.org/book/',
        },
      ],
      accepted_at: null,
    },
  ];
  ext.daemon.outline = [{ node_id: '16', path: { root: 'bar', names: ['Dynomark', 'Rust'] }, pinned: false, locked: false, item_count: 1 }];
  await ext.daemon.waitFor(ofType('index.pull'));
  const view = await ext.extensionPage('diff.html');

  const from = ext.daemon.received.length;
  await view.locator('#propose-audit').click();
  await ext.daemon.waitFor(ofType('diff.propose'), { from });
  const types = ext.daemon.received.slice(from).map((r) => r.frame.type);
  expect(types.indexOf('tree.snapshot')).toBeLessThan(types.indexOf('diff.propose'));
  expect(types).toContain('tree.snapshot');

  await view.locator('button[data-diff="diff-2"]').click();
  await expect(view.locator('#items')).toContainText('Add The Rust Book');
  await view.locator('button[data-accept="item-3"]').click();
  expect(await ext.daemon.waitFor(ofType('diff.accept'))).toMatchObject({ item_id: 'item-3' });
  const receipt = (await ext.daemon.waitFor(ofType('batch.receipt'))) as Receipt;
  expect(receipt.receipt).toMatchObject({ state: 'APPLIED', batch_id: 'batch-item-3' });
  expect(await bookmarkCount(view, 'https://doc.rust-lang.org/book/')).toBe(1);
  await expect
    .poll(async () => {
      await view.locator('button[data-diff="diff-2"]').click();
      return view.locator('.batch-state').first().textContent();
    })
    .toContain('APPLIED');
  await expect(view.locator('button[data-accept="item-3"]')).toBeDisabled();

  await view.locator('input[data-pin="16"]').check();
  expect(await ext.daemon.waitFor(ofType('folder.flags.set'))).toMatchObject({ node_id: '16', pinned: true });
  expect(ext.daemon.invalid).toEqual([]);
});

test('Given another host is writer too, When the settings page opens, Then the conflict banner names it, and a batch offered meanwhile is REJECTED writer_conflict', async ({
  ext,
}) => {
  ext.daemon.writer = { own_marker: true, other_writers: ['work-laptop'], conflict: true };
  await ext.daemon.waitFor(ofType('writer.status'));
  const options = await ext.extensionPage('options.html');
  await expect(options.locator('#writer-conflict')).toBeVisible();
  await expect(options.locator('#writer-conflict')).toContainText('work-laptop');

  const from = ext.daemon.received.length;
  ext.daemon.offer({
    batch_id: 'batch-conflict',
    operations: [{ op: 'create_folder', index: 0, parent: { root: 'bar', names: [] }, title: 'Dynomark' }],
  });
  const receipt = (await ext.daemon.waitFor(ofType('batch.receipt'), { from })) as Receipt;
  expect(receipt.receipt).toMatchObject({ state: 'REJECTED', reason: 'writer_conflict' });
  expect(await options.evaluate(async () => (await chrome.bookmarks.search({ title: 'Dynomark' })).length)).toBe(0);

  ext.daemon.writer = { own_marker: true, other_writers: [], conflict: false };
  await options.locator('#refresh').click();
  await expect(options.locator('#writer-conflict')).toBeHidden();
});

test('Given a writer and a save no tab shows, When it lands in Follow Up, Then the page is read from a background tab (source background_tab) and the window is closed', async ({
  ext,
}) => {
  const server = await serveLocal({
    '/story': `<!doctype html><title>Story | News</title><body><nav>Menu</nav><article><p>Full text visible only when signed in.</p></article></body>`,
  });
  try {
    await ext.daemon.waitFor(ofType('writer.status'));
    const folder = await followUpId(ext);
    const page = await ext.extensionPage('history.html');
    const windowsBefore = await page.evaluate(async () => (await chrome.windows.getAll()).length);
    const url = `${server.origin}/story`;
    const id = await page.evaluate(async ({ parentId, u }) => (await chrome.bookmarks.create({ parentId, title: 'Story', url: u })).id, {
      parentId: folder,
      u: url,
    });
    const ingest = (await ext.daemon.waitFor((r) => r.type === 'ingest' && r.bookmark.node_id === id, { timeoutMs: 40_000 })) as Ingest;
    expect(ingest.capture).toMatchObject({ source: 'background_tab', title: 'Story | News' });
    expect(ingest.capture?.text).toContain('Full text visible only when signed in.');
    expect(server.requested).toContain('/story');
    await expect.poll(() => page.evaluate(async () => (await chrome.windows.getAll()).length)).toBe(windowsBefore);
  } finally {
    await server.close();
  }
});

test('Given existing bookmarks, When backfill is started from the settings page, Then each is ingested with backfill true and the progress is shown', async ({
  ext,
}) => {
  await ext.daemon.waitFor(ofType('index.pull'));
  const options = await ext.extensionPage('options.html');
  const ids = await options.evaluate(async () => {
    const made = [];
    for (const n of [1, 2, 3])
      made.push((await chrome.bookmarks.create({ parentId: '1', title: `Doc ${n}`, url: `https://docs${n}.example/` })).id);
    return made;
  });
  await options.locator('#backfill').click();
  for (const id of ids) await ext.daemon.waitFor((r) => r.type === 'ingest' && r.backfill && r.bookmark.node_id === id);
  await expect
    .poll(async () => {
      await options.locator('#refresh').click();
      return options.locator('#backfill-progress').textContent();
    })
    .toContain('3 of 3');
  expect(ext.daemon.of('ingest').filter((r) => r.backfill && r.capture !== undefined)).toEqual([]);
});
