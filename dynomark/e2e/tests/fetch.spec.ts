// fetch.spec.ts -- "Content falls back to fetch" across both runtimes: with
// both extension capture settings off and no tab showing the page, the
// ingest carries source none, the daemon fetches the page itself (no
// cookies, 127.0.0.1 here), files it, and the fetched text is searchable.

import { PAGES, READING, SERDE, filing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given tab capture off and no tab showing a saved page, When it is saved into Follow Up, Then the daemon fetches it and a word only in its text is found by tier 2', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(1) });
  const settings = await world.pageRequest({ kind: 'settings.set', capture_from_tab: false, capture_in_background: false });
  expect(settings).toMatchObject({ ok: true, capture_from_tab: false, capture_in_background: false });

  const url = pages.url(SERDE.path);
  const tree = await world.tree();
  const node = await tree.create(['Follow Up'], SERDE.title, url);
  await until(
    () => tree.pathOf(node),
    (p) => p?.join('/') === READING.join('/'),
  );
  expect(pages.requested).toEqual([SERDE.path]);

  const byText = await until(
    () => world.omnibox(SERDE.bodyWord),
    (rounds) => rounds.some((r) => r.hits.some((h) => h.tier === 'corpus' && h.identity === url)),
  );
  expect(byText.at(-1)?.hits).toContainEqual({ identity: url, tier: 'corpus' });
});
