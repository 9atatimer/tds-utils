// issuedMoves.test.ts -- the IssuedMoves decorator over the tree port (design,
// "Move": the extension adapter sets origin from the batch operations it
// itself issued). Every call that overlaps another -- a burst of reports to a
// fresh worker, a batch move issued while a report is consumed -- changes the
// list as it is when the call resumes, so no remembered move is lost and no
// consumed one comes back.

import { describe, expect, it } from 'vitest';
import { IssuedMoves } from '../../../src/app/issuedMoves.js';
import { FakeBookmarkTree } from '../../fakes/FakeBookmarkTree.js';
import { FakeStorage } from '../../fakes/FakeStorage.js';
import { seedOwnedTree } from '../../fixtures/ownedTree.js';

describe('Issued moves -- overlapping calls change the list as it is when they resume', () => {
  it('Given two moves an earlier worker issued, When a fresh worker consumes both reports at once, Then neither is remembered after', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const ids = await seedOwnedTree(tree);
    const storage = new FakeStorage();
    await storage.saveIssuedMoves([
      { node_id: ids.saved, parent_id: ids.rust },
      { node_id: ids.usersOwn, parent_id: ids.rust },
    ]);
    const issued = new IssuedMoves(tree, storage);

    const own = await Promise.all([issued.consume(ids.saved, ids.rust), issued.consume(ids.usersOwn, ids.rust)]);

    expect(own).toEqual([true, true]);
    expect(await storage.loadIssuedMoves()).toEqual([]);
    expect(await new IssuedMoves(tree, storage).consume(ids.saved, ids.rust)).toBe(false);
  });

  it('Given a loaded list, When a batch move is issued while another report is consumed, Then the browser report of the batch move is still the extension own', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const ids = await seedOwnedTree(tree);
    const storage = new FakeStorage();
    await storage.saveIssuedMoves([{ node_id: ids.usersOwn, parent_id: ids.dynomark }]);
    const issued = new IssuedMoves(tree, storage);
    expect(await issued.consume(ids.saved, ids.graveyard)).toBe(false);

    await Promise.all([issued.move(ids.saved, ids.rust), issued.consume(ids.usersOwn, ids.dynomark)]);

    expect(await storage.loadIssuedMoves()).toEqual([{ node_id: ids.saved, parent_id: ids.rust }]);
    expect(await issued.consume(ids.saved, ids.rust)).toBe(true);
  });
});
