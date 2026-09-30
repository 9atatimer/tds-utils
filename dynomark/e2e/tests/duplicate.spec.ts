// duplicate.spec.ts -- "A duplicate identity is parked" across both
// runtimes: a page already filed is saved into Follow Up again (a second
// node, same identity); the writer files nothing new -- the new node is
// moved to Graveyard by a batch the extension applies -- and the existing
// placement is unchanged.

import { FOLLOW_UP, PAGES, READING, TOKIO, filing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given a filed page, When the same URL is saved into Follow Up again, Then the new node is parked in Graveyard and the filed one stays where it is', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(2) });
  const url = pages.url(TOKIO.path);
  const filed = await world.saveAndFile(url, TOKIO.title, READING);

  const again = await world.save(url, `${TOKIO.title} (again)`);
  const tree = await world.tree();
  await until(
    () => tree.pathOf(again),
    (p) => p?.join('/') === 'Graveyard',
  );
  expect(await tree.pathOf(filed)).toEqual(READING);
  expect(await tree.titles(FOLLOW_UP)).toEqual([]);
  expect(await tree.titles(READING)).toEqual([TOKIO.title]);
});
