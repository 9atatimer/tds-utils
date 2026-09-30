// writers.spec.ts -- one writer (design Goal 7, Key Decisions "Two
// writers"): the owned tree carries host mbp's writer marker; then a second
// daemon, configured writer with host id work-laptop and its own store,
// takes the socket (as a second laptop would see the synced tree). It sees
// the other host's marker, reports the conflict (the settings page banner
// names mbp), and a new save is indexed but never filed: no batch, no
// marker of its own, the node stays in Follow Up.

import { DYNOMARK, FOLLOW_UP, PAGES, SERDE, filing, indexing } from '../support/scenario.js';
import { expect, test, until } from '../support/world.js';

test("Given the owned tree holds host mbp's writer marker, When a second daemon configured writer with another host id serves the browser, Then writer_conflict is surfaced and a new save is not filed (Goal 7)", async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(1) });
  const tree = await world.tree();
  await until(
    () => tree.titles(DYNOMARK),
    (titles) => titles.includes('dynomark-writer:mbp'),
  );

  await world.start({ role: 'writer', hostId: 'work-laptop', script: indexing(1) });
  const options = await world.browser.extensionPage('options.html');
  await expect
    .poll(
      async () => {
        await options.reload();
        return options.locator('#daemon-host').textContent();
      },
      { timeout: 60_000 },
    )
    .toBe('work-laptop');
  await expect(options.locator('#writer-conflict')).toBeVisible();
  await expect(options.locator('#writer-conflict')).toContainText('mbp');

  const url = pages.url(SERDE.path);
  const node = await world.save(url, SERDE.title);
  const failed = await world.daemon.waitForLog((e) => e.event === 'job.ran' && e['after'] === 'FAILED');
  expect(String(failed['last_error'])).toContain('mbp');
  expect(await tree.pathOf(node)).toEqual(FOLLOW_UP);
  expect(await tree.titles(DYNOMARK)).not.toContain('dynomark-writer:work-laptop');
  expect(world.daemon.log().filter((e) => e.event === 'job.applied')).toEqual([]);
});
