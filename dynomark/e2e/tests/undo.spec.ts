// undo.spec.ts -- undoable, never destructive (design Goal 6): the filing
// batch is undone from the history page after the user has edited the tree
// elsewhere; the filed bookmark returns to Follow Up, the folder the batch
// created goes to Graveyard (never deleted), and the user's own edits made
// in between survive untouched.

import { DYNOMARK, FOLLOW_UP, PAGES, READING, TOKIO, filing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given a filed page and an unrelated user edit made since, When the filing is undone from the history page, Then the bookmark is back in Follow Up, its folder is in Graveyard, and the user edit survives (Goal 6)', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(1) });
  const url = pages.url(TOKIO.path);
  const node = await world.saveAndFile(url, TOKIO.title, READING);

  const tree = await world.tree();
  const notes = await tree.create(DYNOMARK, 'Notes');
  const mine = await tree.create([], 'Mine', 'https://example.org/mine');

  const history = await world.browser.extensionPage('history.html');
  const row = history.locator('tr', { hasText: url });
  await until(
    async () => {
      await history.reload();
      return row.count();
    },
    (n) => n === 1,
  );
  await row.locator('button[data-batch]').click();
  await expect(history.locator('#message')).toContainText('undo');

  await until(
    () => tree.pathOf(node),
    (p) => p?.join('/') === FOLLOW_UP.join('/'),
  );
  await until(
    () => tree.titles(['Graveyard']),
    (titles) => titles.includes('Reading'),
  );
  expect(await tree.titles(DYNOMARK)).not.toContain('Reading');
  expect(await tree.pathOf(notes)).toEqual(DYNOMARK);
  expect(await tree.pathOf(mine)).toEqual([]);
  expect(await tree.withUrl(url)).toEqual([node]);
});
