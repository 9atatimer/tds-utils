/// <reference types="chrome" />
// extension.spec.ts -- the extension end to end in Chromium, against a fake
// native host (task-026 item 8): it loads unpacked with its pinned id and
// says hello; a save into Follow Up reaches the daemon as one ingest with a
// capture from the open tab; a scripted batch.offer changes the tree and is
// answered with a receipt; the omnibox handler and the pages work against
// the daemon.

import type { RequestMessage } from '../src/wire/messages.js';
import { PINNED_EXTENSION_ID } from '../test/support/browser.js';
import { FAKE_HOST_ID } from '../test/support/fakeDaemon.js';
import { expect, followUpId, ofType, test } from './fixtures.js';

// --- Builders ---

const ARTICLE_URL = 'https://article.test/async-rust';
const ARTICLE_HTML = `<!doctype html><title>Async Rust | Article</title>
<body><nav>Home Blog About</nav><article><h1>Async Rust</h1><p>Futures are lazy state machines driven by an executor.</p></article>
<footer>Copyright</footer></body>`;

type Ingest = Extract<RequestMessage, { type: 'ingest' }>;
type Receipt = Extract<RequestMessage, { type: 'batch.receipt' }>;

// --- Tests ---

test('Given the built extension, When it loads unpacked, Then its id is the pinned one and it says hello, snapshot, replay and pull', async ({
  ext,
}) => {
  expect(ext.extensionId).toBe(PINNED_EXTENSION_ID);
  const hello = await ext.daemon.waitFor(ofType('hello'));
  expect(hello).toMatchObject({ v: 1, follow_up: { root: 'bar', names: ['Follow Up'] } });
  await ext.daemon.waitFor(ofType('index.pull'));
  expect(ext.daemon.received.map((r) => r.frame.type).slice(0, 4)).toEqual(['hello', 'tree.snapshot', 'events.replay', 'index.pull']);
  expect(ext.daemon.invalid).toEqual([]);
});

test('Given a tab showing a page, When it is bookmarked into Follow Up, Then the daemon receives one ingest with a tab capture of its article', async ({
  ext,
}) => {
  await ext.context.route(ARTICLE_URL, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: ARTICLE_HTML }));
  const tab = await ext.context.newPage();
  await tab.goto(ARTICLE_URL);
  await ext.daemon.waitFor(ofType('index.pull'));
  const folder = await followUpId(ext);
  const page = await ext.extensionPage('history.html');
  const id = await page.evaluate(async ({ parentId, url }) => (await chrome.bookmarks.create({ parentId, title: 'Async Rust', url })).id, {
    parentId: folder,
    url: ARTICLE_URL,
  });
  const ingest = (await ext.daemon.waitFor((r) => r.type === 'ingest' && r.bookmark.node_id === id)) as Ingest;
  expect(ingest).toMatchObject({ backfill: false, bookmark: { url: ARTICLE_URL, path: { root: 'bar', names: ['Follow Up'] } } });
  expect(ingest.capture).toMatchObject({ source: 'tab', title: 'Async Rust | Article' });
  expect(ingest.capture?.text).toContain('Futures are lazy state machines');
  expect(ingest.capture?.text).not.toContain('Copyright');
  expect(ext.daemon.of('ingest').filter((r) => r.bookmark.node_id === id)).toHaveLength(1);
  expect(ext.daemon.invalid).toEqual([]);
});

test('Given a save in Follow Up, When the daemon offers a batch filing it, Then the tree changes, the receipt is APPLIED and a snapshot follows', async ({
  ext,
}) => {
  await ext.daemon.waitFor(ofType('index.pull'));
  const folder = await followUpId(ext);
  const page = await ext.extensionPage('history.html');
  const saved = await page.evaluate(
    async (parentId) => (await chrome.bookmarks.create({ parentId, title: 'Tokio', url: 'https://tokio.rs/' })).id,
    folder,
  );
  await ext.daemon.waitFor((r) => r.type === 'ingest' && r.bookmark.node_id === saved);
  const from = ext.daemon.received.length;
  ext.daemon.offer({
    batch_id: 'batch-file-1',
    operations: [
      { op: 'create_folder', index: 0, parent: { root: 'bar', names: [] }, title: 'Dynomark' },
      { op: 'create_folder', index: 1, parent: { root: 'bar', names: ['Dynomark'] }, title: 'Rust' },
      { op: 'move', index: 2, node_id: saved, to: { root: 'bar', names: ['Dynomark', 'Rust'] }, expect: { parent_id: folder } },
    ],
  });
  const receipt = (await ext.daemon.waitFor(ofType('batch.receipt'), { from })) as Receipt;
  expect(receipt.receipt).toMatchObject({ state: 'APPLIED', batch_id: 'batch-file-1', pre_batch: true });
  expect(receipt.receipt.state === 'APPLIED' ? receipt.receipt.applied.map((a) => a.changed) : []).toEqual([true, true, true]);
  const parent = await page.evaluate(async (id) => {
    const [node] = await chrome.bookmarks.get(id);
    const [folderNode] = await chrome.bookmarks.get(node?.parentId ?? '');
    return folderNode?.title;
  }, saved);
  expect(parent).toBe('Rust');
  await ext.daemon.waitFor(ofType('tree.snapshot'), { from: ext.daemon.received.findIndex((r) => r.frame === receipt) });
  const moved = await ext.daemon.waitFor((r) => r.type === 'move.observed' && r.move.node_id === saved, { from });
  expect(moved).toMatchObject({ move: { origin: 'extension', from: { names: ['Follow Up'] }, to: { names: ['Dynomark', 'Rust'] } } });
  expect(ext.daemon.invalid).toEqual([]);
});

test('Given the pulled index, When the omnibox handler gets "tokio" (through the background handle: headless has no address bar), Then tier 1 then tier 2 suggest, and Enter opens the hit', async ({
  ext,
}) => {
  ext.daemon.indexRows = [
    {
      identity: 'https://tokio.rs/tokio/tutorial',
      title: 'Tokio tutorial',
      path: { root: 'bar', names: ['Dynomark', 'Rust'] },
      tags: ['rust'],
      summary: 'Async.',
    },
  ];
  ext.daemon.searchHits = [
    {
      identity: 'https://without.boats/blog/pin/',
      title: 'Pin',
      path: { root: 'bar', names: ['Dynomark', 'Rust'] },
      score: 0.5,
      tier: 'corpus',
    },
  ];
  await ext.daemon.waitFor(ofType('index.pull'));
  const worker = await ext.serviceWorker();
  const rounds = await worker.evaluate(async () => {
    const runtime = (
      globalThis as unknown as {
        dynomark: {
          omniboxInput(t: string, s: (rows: { hits: readonly { identity: string; tier: string }[]; ask?: string }) => void): void;
        };
      }
    ).dynomark;
    const seen: string[][] = [];
    for (let i = 0; i < 50; i += 1) {
      seen.length = 0;
      runtime.omniboxInput('tokio', (rows) => seen.push([...rows.hits.map((h) => `${h.tier} ${h.identity}`), `ask ${rows.ask ?? ''}`]));
      if ((seen[0] ?? []).length > 1) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    return seen;
  });
  expect(rounds[0]).toEqual(['local https://tokio.rs/tokio/tutorial']);
  expect(rounds.at(-1)).toEqual(['local https://tokio.rs/tokio/tutorial', 'corpus https://without.boats/blog/pin/']);
  expect(ext.daemon.of('search').map((r) => r.query)).toEqual(['tokio']);
  await worker.evaluate(() =>
    (globalThis as unknown as { dynomark: { omniboxEnter(t: string, d: string): Promise<void> } }).dynomark.omniboxEnter(
      'tokio',
      'newForegroundTab',
    ),
  );
  // No network: the tab's navigation fails to an error page, but the browser still reports the URL it was sent to.
  const page = await ext.extensionPage('history.html');
  await expect
    .poll(() => page.evaluate(async () => (await chrome.tabs.query({})).map((t) => t.url ?? t.pendingUrl)))
    .toContain('https://tokio.rs/tokio/tutorial');
});

test('Given a connected daemon, When the options page opens, Then it shows the transport and the daemon role, host, models and queue depth', async ({
  ext,
}) => {
  await ext.daemon.waitFor(ofType('index.pull'));
  const page = await ext.extensionPage('options.html');
  await expect(page.locator('#daemon-role')).toHaveText('writer');
  await expect(page.locator('#daemon-host')).toHaveText(FAKE_HOST_ID);
  await expect(page.locator('#daemon-embedding')).toHaveText('nomic-embed-text (local)');
  await expect(page.locator('#daemon-queue')).toHaveText('3');
  await expect(page.locator('#link')).toHaveText('connected');
  await expect(page.locator('#capture')).toBeChecked();
  await page.locator('#capture').uncheck();
  await expect(page.locator('#message')).toHaveText('saved');
  await page.reload();
  await expect(page.locator('#daemon-role')).toHaveText('writer');
  await expect(page.locator('#capture')).not.toBeChecked();
});

test('Given an APPLIED batch and a FAILED job, When the history page offers Undo and Retry, Then pressing them sends undo and job.retry', async ({
  ext,
}) => {
  ext.daemon.batches = [{ batch_id: 'batch-1', state: 'APPLIED', created_at: 1_790_000_000_000, identity: 'https://tokio.rs/' }];
  ext.daemon.failedJobs = [
    {
      job_id: 'job-9',
      node_id: '42',
      identity: 'https://serde.rs/',
      state: 'FAILED',
      seq: 3,
      attempts: 3,
      backfill: false,
      last_error: 'timeout',
    },
  ];
  ext.daemon.extra = (r) => {
    if (r.type === 'undo') return { v: 1, type: 'undo.result', re: r.id, batch_id: 'batch-2', undoes: r.batch_id, dropped: [] };
    if (r.type === 'job.retry')
      return { v: 1, type: 'job.retry.result', re: r.id, job: { ...ext.daemon.failedJobs[0]!, state: 'QUEUED', seq: 4 } };
    return undefined;
  };
  await ext.daemon.waitFor(ofType('index.pull'));
  const page = await ext.extensionPage('history.html');
  await page.locator('button[data-batch="batch-1"]').click();
  expect(await ext.daemon.waitFor(ofType('undo'))).toMatchObject({ batch_id: 'batch-1' });
  await expect(page.locator('#message')).toContainText('batch-2');
  await page.locator('button[data-job="job-9"]').click();
  expect(await ext.daemon.waitFor(ofType('job.retry'))).toMatchObject({ job_id: 'job-9' });
  await expect(page.locator('#message')).toContainText('queued');
});
