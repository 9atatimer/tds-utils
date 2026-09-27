// resume.spec.ts -- "A batch resumes after termination" against the real
// daemon: an accepted rebuild item of 100 operations is being applied when
// the browser stops the extension's service worker (CDP
// ServiceWorker.stopAllWorkers, as Chrome stops an idle worker). The next
// worker says hello, the daemon re-offers the unacknowledged batch, and the
// extension resumes from its durable cursor: every folder exists exactly
// once and the batch ends APPLIED.

import type { Operation } from '../support/daemon.js';
import { DYNOMARK, bar } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

const FOLDERS = 99;
const STOP_AFTER = 10;

function title(i: number): string {
  return `F${String(i).padStart(2, '0')}`;
}

const REBUILD_ITEM = {
  action: 'add' as const,
  description: 'Add an Archive of dated folders',
  operations: [
    { op: 'create_folder', index: 0, parent: bar(...DYNOMARK), title: 'Archive' },
    ...Array.from({ length: FOLDERS }, (_, i) => ({
      op: 'create_folder',
      index: i + 1,
      parent: bar('Dynomark', 'Archive'),
      title: title(i),
    })),
  ] as Operation[],
};

test('Given an accepted batch being applied, When the service worker is stopped mid-batch, Then the next worker resumes it from the cursor and no folder is duplicated', async ({
  world,
}) => {
  await world.start({ role: 'writer', hostId: 'mbp', script: { propose_diff: [[REBUILD_ITEM]] } });
  const tree = await world.tree();
  await until(
    () => tree.titles(DYNOMARK),
    (titles) => titles.includes('dynomark-writer:mbp'),
  );

  const view = await world.browser.extensionPage('diff.html');
  await view.locator('#propose-rebuild').click();
  const item = view.locator('tr', { hasText: REBUILD_ITEM.description });
  await item.locator('button.accept').click();
  await until(
    () => tree.titles(['Dynomark', 'Archive']),
    (titles) => titles.length >= STOP_AFTER,
    30_000,
  );
  await world.browser.stopServiceWorkers();

  const cursor = await view.evaluate(
    async () => (await chrome.storage.local.get('batch_cursor'))['batch_cursor'] as { batch_id: string; next_index: number } | undefined,
  );
  expect(cursor?.next_index).toBeGreaterThan(0);
  expect(cursor?.next_index).toBeLessThan(FOLDERS + 1);

  await world.browser.extensionPage('options.html');
  const titles = await until(
    () => tree.titles(['Dynomark', 'Archive']),
    (t) => t.length >= FOLDERS,
    60_000,
  );
  expect(titles).toHaveLength(FOLDERS);
  expect(new Set(titles).size).toBe(FOLDERS);
  expect(await tree.foldersTitled('Archive')).toHaveLength(1);
  await expect
    .poll(
      async () => {
        await view.locator('#refresh').click();
        await view.locator('button[data-diff]').first().click();
        return item.locator('.batch-state').textContent();
      },
      { timeout: 30_000 },
    )
    .toContain('APPLIED');
});
