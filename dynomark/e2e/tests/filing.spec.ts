// filing.spec.ts -- the live loop (design Goals 1, 2 and 8): a page open in
// a tab and saved into Follow Up with the native tree is captured from that
// tab, ingested by the real daemon, placed, and filed under Dynomark by a
// batch the extension applies; the Follow Up node itself is consumed (moved,
// not copied). Nothing outside the owned roots is touched. The measured
// ingest-received -> APPLIED interval is printed from the daemon's log.

import { DYNOMARK, FOLLOW_UP, OWNED_TOP_LEVEL, PAGES, READING, TOKIO, filing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test('Given a page open in a tab, When it is saved into Follow Up, Then it is captured from the tab, ingested, placed and filed under Dynomark, and the Follow Up node is consumed (Goals 1, 2, 8)', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(1) });
  const tree = await world.tree();
  await until(
    () => tree.titles([]),
    (titles) => titles.includes('Follow Up'),
  );

  const url = pages.url(TOKIO.path);
  await world.openTab(url);
  const node = await tree.create(FOLLOW_UP, TOKIO.title, url);

  const path = await until(
    () => tree.pathOf(node),
    (p) => p?.join('/') === READING.join('/'),
  );
  expect(path).toEqual(READING);
  expect(await tree.titles(FOLLOW_UP)).toEqual([]);
  expect(await tree.withUrl(url)).toEqual([node]);
  // Captured from the tab: the only request for the page is the tab's own (the daemon's fetch fallback never ran).
  expect(pages.requested.filter((p) => p === TOKIO.path)).toHaveLength(1);
  expect(await tree.titles(DYNOMARK)).toEqual(expect.arrayContaining(['dynomark-writer:mbp', 'Reading']));
  // Goal 8: every top-level folder the loop made is an owned root.
  expect((await tree.titles([])).every((t) => OWNED_TOP_LEVEL.includes(t))).toBe(true);

  const intervals = world.reportGoal2();
  expect(intervals.length).toBeGreaterThanOrEqual(1);
  expect(Math.max(...intervals)).toBeLessThan(60_000);
});
