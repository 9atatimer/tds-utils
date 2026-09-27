/// <reference types="chrome" />
// resume.spec.ts -- the design's "A batch resumes after termination" in a
// real browser: the service worker is terminated in the middle of a large
// batch (CDP ServiceWorker.stopAllWorkers, as Chrome does to an idle
// worker); the next worker says hello, the daemon re-offers the unacknowledged
// batch on replay, and the extension resumes from its durable cursor --
// every folder exists exactly once and the ops done before the kill are
// reported from the cursor (changed true), not re-derived from the tree.

import type { RequestMessage } from '../src/wire/messages.js';
import { expect, ofType, test } from './fixtures.js';

// --- Builders ---

const FOLDERS = 400;
const KILL_AFTER = 60;

type Receipt = Extract<RequestMessage, { type: 'batch.receipt' }>;

function title(i: number): string {
  return `F${String(i).padStart(3, '0')}`;
}

// --- Tests ---

test('Given a worker terminated mid-batch, When a new worker is offered the batch again, Then it resumes from the cursor with no duplicate folder', async ({
  ext,
}) => {
  await ext.daemon.waitFor(ofType('index.pull'));
  const page = await ext.extensionPage('history.html');
  ext.daemon.offer({
    batch_id: 'batch-big',
    operations: [
      { op: 'create_folder', index: 0, parent: { root: 'bar', names: [] }, title: 'Dynomark' },
      ...Array.from({ length: FOLDERS }, (_, i) => ({
        op: 'create_folder' as const,
        index: i + 1,
        parent: { root: 'bar' as const, names: ['Dynomark'] },
        title: title(i),
      })),
    ],
  });
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const [dyn] = await chrome.bookmarks.search({ title: 'Dynomark' });
          return dyn === undefined ? 0 : (await chrome.bookmarks.getChildren(dyn.id)).length;
        }),
      { intervals: [10], timeout: 30_000 },
    )
    .toBeGreaterThanOrEqual(KILL_AFTER);
  await ext.stopServiceWorkers();

  const cursor = await page.evaluate(
    async () => (await chrome.storage.local.get('batch_cursor'))['batch_cursor'] as { batch_id: string; next_index: number },
  );
  expect(cursor.batch_id).toBe('batch-big');
  expect(cursor.next_index).toBeGreaterThan(0);
  expect(cursor.next_index).toBeLessThan(FOLDERS + 1);
  expect(ext.daemon.of('batch.receipt')).toEqual([]);

  const from = ext.daemon.received.length;
  await ext.extensionPage('options.html');
  await ext.daemon.waitFor(ofType('hello'), { from });
  const receipt = (await ext.daemon.waitFor(ofType('batch.receipt'), { from, timeoutMs: 60_000 })) as Receipt;
  expect(receipt.receipt).toMatchObject({ state: 'APPLIED', batch_id: 'batch-big', pre_batch: false });
  const applied = receipt.receipt.state === 'APPLIED' ? receipt.receipt.applied : [];
  expect(applied).toHaveLength(FOLDERS + 1);
  expect(applied.slice(0, cursor.next_index).every((a) => a.changed)).toBe(true);

  const titles = await page.evaluate(async () => {
    const [dyn, ...others] = await chrome.bookmarks.search({ title: 'Dynomark' });
    return {
      dynomarks: others.length + 1,
      children: dyn === undefined ? [] : (await chrome.bookmarks.getChildren(dyn.id)).map((n) => n.title),
    };
  });
  expect(titles.dynomarks).toBe(1);
  expect(titles.children).toHaveLength(FOLDERS);
  expect(new Set(titles.children).size).toBe(FOLDERS);
  expect(ext.daemon.connections()).toBeGreaterThanOrEqual(2);
  expect(ext.daemon.invalid).toEqual([]);
});
