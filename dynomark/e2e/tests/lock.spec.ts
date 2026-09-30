// lock.spec.ts -- "Placement respects a lock" across both runtimes: the
// user locks an owned folder on the diff page (folder.flags.set by node id
// and path); when the model then names that folder for the next save, the
// daemon places it elsewhere and the extension files it there, never
// inside the locked folder.

import { DYNOMARK, PAGES, READING, SERDE, TOKIO, filing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given the user locked the folder the model names, When the next save is placed, Then it is filed outside that folder', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(2) });
  await world.saveAndFile(pages.url(TOKIO.path), TOKIO.title, READING);

  const tree = await world.tree();
  const reading = (await tree.children(DYNOMARK))?.find((n) => n.title === 'Reading');
  expect(reading).toBeDefined();
  const view = await world.browser.extensionPage('diff.html');
  await view.locator(`input[data-lock="${reading?.id ?? ''}"]`).check();
  await expect(view.locator('#message')).toContainText('locked on');

  const node = await world.save(pages.url(SERDE.path), SERDE.title);
  const path = await until(
    () => tree.pathOf(node),
    (p) => p !== undefined && p[0] === 'Dynomark',
  );
  expect(path).not.toEqual(READING);
  expect(await tree.titles(READING)).toEqual([TOKIO.title]);
});
