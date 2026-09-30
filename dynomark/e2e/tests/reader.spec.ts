// reader.spec.ts -- a reader host (design Multi-device policy, "A reader
// host never writes"): its daemon ingests every save it sees for its own
// search and chat and never files. The save is indexed (tier-2 search finds
// a word only in its page text) while the node stays in Follow Up and no
// owned folder or writer marker is ever created.

import { FOLLOW_UP, PAGES, TOKIO, indexing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given a daemon configured reader, When a page is saved into Follow Up, Then it is indexed and searchable but never filed', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'reader', hostId: 'phone-laptop', script: indexing(1) });
  const url = pages.url(TOKIO.path);
  const node = await world.save(url, TOKIO.title);

  await world.daemon.waitForLog((e) => e.event === 'job.ran' && e['after'] === 'INDEXED');
  const byText = await until(
    () => world.omnibox(TOKIO.bodyWord),
    (rounds) => rounds.some((r) => r.hits.some((h) => h.tier === 'corpus' && h.identity === url)),
  );
  expect(byText.at(-1)?.hits).toContainEqual({ identity: url, tier: 'corpus' });

  const tree = await world.tree();
  expect(await tree.pathOf(node)).toEqual(FOLLOW_UP);
  expect(await tree.titles([])).not.toContain('Dynomark');
  expect(world.daemon.log().filter((e) => e.event === 'job.applied')).toEqual([]);
});
