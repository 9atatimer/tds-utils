// search.spec.ts -- recall (design Goal 4) through the omnibox handler, the
// `bm` keyword's background side (headless has no address bar, so the
// scenario calls the handler through the service worker's diagnostic
// handle): a filed page is found by its title from the pulled LocalIndex
// (tier 1, no daemon call), and by a word that appears only in its captured
// page text from the daemon's corpus (tier 2).

import { PAGES, READING, TOKIO, filing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given a filed page, When the omnibox handler gets its title, Then tier 1 suggests it; When it gets a word only in its page text, Then tier 2 suggests it (Goal 4)', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(1) });
  const url = pages.url(TOKIO.path);
  await world.saveAndFile(url, TOKIO.title, READING);

  const byTitle = await until(
    () => world.omnibox('Tokio'),
    (rounds) => rounds.some((r) => r.hits.some((h) => h.tier === 'local' && h.identity === url)),
  );
  expect(byTitle[0]?.hits[0]).toEqual({ identity: url, tier: 'local' });
  expect(byTitle[0]?.ask).toBe('Tokio');

  const byText = await until(
    () => world.omnibox(TOKIO.bodyWord),
    (rounds) => rounds.some((r) => r.hits.some((h) => h.tier === 'corpus' && h.identity === url)),
  );
  expect(byText[0]?.hits.filter((h) => h.tier === 'local')).toEqual([]);
  expect(byText.at(-1)?.hits).toContainEqual({ identity: url, tier: 'corpus' });
});
