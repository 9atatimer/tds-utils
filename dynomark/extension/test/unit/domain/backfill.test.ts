// backfill.test.ts -- which bookmarks a backfill ingests (design, Open
// Question 3: run the existing tree through capture and indexing, searchable,
// not re-filed; contract v1, "Jobs": a backfill ingest is never offered a
// batch). Every http(s) bookmark with a folder path, outside Follow Up (those
// are ordinary saves) and Graveyard (removed), in tree order.

import { describe, expect, it } from 'vitest';
import { backfillBookmark, backfillCandidates, isBackfillDone } from '../../../src/domain/backfill.js';
import { FakeBookmarkTree } from '../../fakes/FakeBookmarkTree.js';
import { FOLLOW_UP, GRAVEYARD, RUST, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

const SKIP = [FOLLOW_UP, GRAVEYARD];

async function tree() {
  const t = new FakeBookmarkTree({ flavor: 'chrome' });
  const ids = await seedOwnedTree(t);
  const filed = (await t.createBookmark(ids.rust, 'Serde', 'https://serde.rs/')).id;
  const parked = (await t.createBookmark(ids.graveyard, 'Old', 'https://old.example/')).id;
  const bookmarklet = (await t.createBookmark(ids.bar, 'Clip', 'javascript:void(0)')).id;
  const other = (await t.createBookmark((await t.readTree()).root_ids.other, 'Docs', 'http://docs.example/')).id;
  return { t, ids, filed, parked, bookmarklet, other };
}

// --- Tests ---

describe('backfillCandidates', () => {
  it('Given bookmarks across the tree, When candidates are chosen, Then http(s) ones outside Follow Up and Graveyard are, in tree order', async () => {
    const { t, ids, filed, other } = await tree();
    expect(backfillCandidates(await t.readTree(), SKIP)).toEqual([ids.usersOwn, filed, other]);
  });
});

describe('backfillBookmark -- a candidate as it is now', () => {
  it('Given a candidate, When read now, Then it is the bookmark with its folder path', async () => {
    const { t, filed } = await tree();
    expect(backfillBookmark(await t.readTree(), filed, SKIP)).toMatchObject({ node_id: filed, url: 'https://serde.rs/', path: RUST });
  });

  it('Given a candidate since removed or moved into Graveyard, When read now, Then it is no longer backfilled', async () => {
    const { t, ids, filed, other } = await tree();
    await t.move(filed, ids.graveyard);
    t.deleteByUser(other);
    const now = await t.readTree();
    expect(backfillBookmark(now, filed, SKIP)).toBeUndefined();
    expect(backfillBookmark(now, other, SKIP)).toBeUndefined();
  });
});

describe('isBackfillDone', () => {
  it('Given progress at or past the last node, When asked, Then it is done; before it, not', () => {
    const progress = { started_at: 1, node_ids: ['1', '2'], next_index: 1 };
    expect(isBackfillDone(progress)).toBe(false);
    expect(isBackfillDone({ ...progress, next_index: 2 })).toBe(true);
  });
});
