// feedback.spec.ts -- "A user move becomes feedback" across both runtimes:
// the user moves a filed bookmark between two owned folders; the extension
// reports the move with origin user, the writer daemon records it as
// feedback, and the next placement names it in its reason ("why here").

import { PAGES, READING, SERDE, TOKIO, filing } from '../support/scenario.js';
import { expect, test } from '../support/world.js';

test('Given a filed bookmark the user moves to another owned folder, When the next save is placed, Then its placement reason lists that move as feedback', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  await world.start({ role: 'writer', hostId: 'mbp', script: filing(2) });
  const tokio = pages.url(TOKIO.path);
  const node = await world.saveAndFile(tokio, TOKIO.title, READING);

  const tree = await world.tree();
  const rust = await tree.create(['Dynomark'], 'Rust');
  await world.tree().then((t) => t.move(node, rust));
  await world.daemon.waitForLog((e) => e.event === 'move.observed' && e['node_id'] === node && e['feedback'] === true);

  const serde = pages.url(SERDE.path);
  await world.saveAndFile(serde, SERDE.title, READING);
  const answer = await world.pageRequest({ kind: 'explain', identity: serde });
  expect(answer).toMatchObject({ ok: true, kind: 'explain' });
  const reason = answer['reason'] as { feedback_ids: readonly string[] };
  expect(reason.feedback_ids).toHaveLength(1);
});
