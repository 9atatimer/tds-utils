// bookmarkTree.fake.test.ts -- the BookmarkTreePort fake honours the port
// contract in both browser flavors, and models what only a fake can arrange:
// per-profile node ids, the Firefox menu root and separators, Chrome's
// account-storage copies of the top-level folders, and user edits.

import { describe, expect, it } from 'vitest';
import { FakeBookmarkTree } from '../../fakes/FakeBookmarkTree.js';
import { describeBookmarkTreeContract } from '../../port-contracts/bookmarkTree.contract.js';
import { NodeIdSchema } from '../../../src/wire/values.js';

describeBookmarkTreeContract('FakeBookmarkTree (chrome)', () => new FakeBookmarkTree({ flavor: 'chrome' }));
describeBookmarkTreeContract('FakeBookmarkTree (firefox)', () => new FakeBookmarkTree({ flavor: 'firefox' }));
describeBookmarkTreeContract(
  'FakeBookmarkTree (chrome, account storage)',
  () => new FakeBookmarkTree({ flavor: 'chrome', accountStorage: true }),
);

describe('FakeBookmarkTree', () => {
  it('Given two Chrome profiles, When each creates a folder, Then both get the same id: node ids are per profile, not global', async () => {
    const a = new FakeBookmarkTree({ flavor: 'chrome' });
    const b = new FakeBookmarkTree({ flavor: 'chrome' });
    const inA = await a.createFolder('1', 'Dynomark');
    const inB = await b.createFolder('1', 'Other name');
    expect(inA.id).toBe(inB.id);
    expect(inA.id).toMatch(/^[0-9]+$/);
  });

  it('Given a Firefox profile, When read, Then all four root keys map to guid-shaped ids, menu included', async () => {
    const { root_ids } = await new FakeBookmarkTree({ flavor: 'firefox' }).readTree();
    expect(Object.keys(root_ids).sort()).toEqual(['bar', 'menu', 'mobile', 'other']);
    for (const id of Object.values(root_ids)) expect(NodeIdSchema.safeParse(id).success).toBe(true);
    expect(root_ids.bar).toBe('toolbar_____');
  });

  it('Given a Chrome profile with account storage, When read, Then root_ids name the syncing copies, not the local-only ones', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome', accountStorage: true });
    const read = await tree.readTree();
    const bars = read.nodes.filter((n) => n.title === 'Bookmarks bar');
    expect(bars).toHaveLength(2);
    expect(tree.isSyncing(read.root_ids.bar)).toBe(true);
    expect(bars.filter((n) => n.id !== read.root_ids.bar).every((n) => !tree.isSyncing(n.id))).toBe(true);
  });

  it('Given a Firefox separator seeded between two folders, When read, Then it is a titled-empty separator with no url at its index', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'firefox' });
    await tree.createFolder('toolbar_____', 'A');
    const sep = tree.addSeparator('toolbar_____');
    await tree.createFolder('toolbar_____', 'B');
    expect(await tree.getNode(sep)).toMatchObject({ kind: 'separator', title: '', index: 1 });
    expect(await tree.getNode(sep)).not.toHaveProperty('url');
  });

  it('Given a Chrome profile, When a separator is seeded, Then the fake refuses: Chrome has none', () => {
    expect(() => new FakeBookmarkTree({ flavor: 'chrome' }).addSeparator('1')).toThrow(/separator/);
  });

  it('Given a folder with contents deleted by the user, When read, Then the folder and every descendant are gone', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const folder = await tree.createFolder('1', 'Old');
    const inner = await tree.createBookmark(folder.id, 'x', 'https://x.example/');
    tree.deleteByUser(folder.id);
    expect(await tree.getNode(folder.id)).toBeUndefined();
    expect(await tree.getNode(inner.id)).toBeUndefined();
  });
});
