// audit.spec.ts -- the diff mechanism (design Goals 3 and 8, "A diff item is
// accepted", "An audit item may cross the boundary", "A batch is undone")
// against the real daemon: an audit is proposed from the diff page, one of
// its two items is accepted and applied to the user's own bar (the one
// boundary exception), the other stays unapplied, and undoing the accepted
// item from the history page reverts it into Graveyard.

import type { Operation } from '../support/daemon.js';
import { bar } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

const BOOK = 'https://doc.rust-lang.org/book/';
const ACCEPTED = {
  action: 'add' as const,
  description: 'Add The Rust Book to a Reading list folder on your bar',
  operations: [
    { op: 'create_folder', index: 0, parent: bar(), title: 'Reading list' },
    { op: 'create', index: 1, parent: bar('Reading list'), title: 'The Rust Book', url: BOOK },
  ] as Operation[],
};
const LEFT = {
  action: 'add' as const,
  description: 'Add a Later folder to your bar',
  operations: [{ op: 'create_folder', index: 0, parent: bar(), title: 'Later' }] as Operation[],
};

test('Given an audit proposed with two items, When one is accepted and then undone, Then it is applied across the boundary alone and its undo moves what it made to Graveyard', async ({
  world,
}) => {
  await world.start({ role: 'writer', hostId: 'mbp', script: { propose_diff: [[ACCEPTED, LEFT]] } });
  const tree = await world.tree();
  await until(
    () => tree.titles(['Dynomark']),
    (titles) => titles.includes('dynomark-writer:mbp'),
  );

  const view = await world.browser.extensionPage('diff.html');
  await view.locator('#propose-audit').click();
  const accepted = view.locator('tr', { hasText: ACCEPTED.description });
  const left = view.locator('tr', { hasText: LEFT.description });
  await expect(left).toBeVisible();
  await accepted.locator('button.accept').click();

  await until(
    () => tree.titles(['Reading list']),
    (titles) => titles.includes('The Rust Book'),
  );
  expect(await tree.titles([])).not.toContain('Later');
  await expect
    .poll(
      async () => {
        await view.locator('button[data-diff]').first().click();
        return accepted.locator('.batch-state').textContent();
      },
      { timeout: 30_000 },
    )
    .toContain('APPLIED');
  const batchId = ((await accepted.locator('.batch-state').textContent()) ?? '').split(' ').at(-1) ?? '';
  expect(batchId).toMatch(/^batch-/);
  await expect(left.locator('.batch-state')).toHaveText('proposed');

  const history = await world.browser.extensionPage('history.html');
  await history.locator(`button[data-batch="${batchId}"]`).click();
  await expect(history.locator('#message')).toContainText('undo');
  await until(
    () => tree.titles([]),
    (titles) => !titles.includes('Reading list'),
  );
  const [book] = await tree.withUrl(BOOK);
  expect((await tree.pathOf(book ?? ''))?.[0]).toBe('Graveyard');
  expect(await tree.titles([])).not.toContain('Later');
});
