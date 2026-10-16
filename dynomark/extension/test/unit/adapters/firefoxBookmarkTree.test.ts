// firefoxBookmarkTree.test.ts -- the BookmarkTreePort on Firefox's
// browser.bookmarks (design, seam table: the second "Browser tree API"
// adapter; task-032) runs the port contract over a tiny stand-in for
// browser.bookmarks. Firefox differs from Chrome where it matters: root_ids
// are its fixed guids, menu included (contract v2 README, "Write batches",
// Paths); every node has a `type`, and a separator is a separator even though
// Firefox reports a url (`data:`) on it; bookmark events carry the same
// shapes, and there is no onChildrenReordered to listen to.

import { describe, expect, it } from 'vitest';
import { listenFirefoxBookmarkEvents } from '../../../src/adapters/firefox/bookmarkEvents.js';
import { FirefoxBookmarkTree } from '../../../src/adapters/firefox/bookmarkTree.js';
import type { FirefoxBookmarkNode } from '../../../src/adapters/firefox/bookmarkTree.js';
import type { BookmarkEvent } from '../../../src/ports/bookmarkEvents.js';
import { SnapshotSchema } from '../../../src/wire/values.js';
import { describeBookmarkTreeContract } from '../../port-contracts/bookmarkTree.contract.js';
import { EventStub } from '../../stubs/chromeEvents.js';
import { FirefoxBookmarksStub } from '../../stubs/firefoxBookmarks.js';

describeBookmarkTreeContract('FirefoxBookmarkTree (stubbed browser.bookmarks)', () => new FirefoxBookmarkTree(new FirefoxBookmarksStub()));

// --- Builders ---

const TOOLBAR = 'toolbar_____';

function eventsApi() {
  return {
    onCreated: new EventStub<[string, FirefoxBookmarkNode]>(),
    onMoved: new EventStub<[string, { parentId: string; oldParentId: string; index: number; oldIndex: number }]>(),
    onChanged: new EventStub<[string, { title: string; url?: string }]>(),
    onRemoved: new EventStub<[string, { parentId: string; index: number }]>(),
  };
}

// --- Tests ---

describe('FirefoxBookmarkTree', () => {
  it('Given a Firefox profile, When read, Then root_ids name the toolbar, unfiled, mobile and menu guids', async () => {
    const { root_ids } = await new FirefoxBookmarkTree(new FirefoxBookmarksStub()).readTree();
    expect(root_ids).toEqual({ bar: TOOLBAR, other: 'unfiled_____', mobile: 'mobile______', menu: 'menu________' });
  });

  it('Given a separator between two folders, When read, Then it is a separator with no url at its index, and the wire accepts the snapshot', async () => {
    const api = new FirefoxBookmarksStub();
    const tree = new FirefoxBookmarkTree(api);
    await tree.createFolder(TOOLBAR, 'Follow Up');
    const sep = api.addSeparator(TOOLBAR);
    await tree.createFolder(TOOLBAR, 'Dynomark');
    const read = await tree.readTree();
    const node = read.nodes.find((n) => n.id === sep);
    expect(node).toMatchObject({ kind: 'separator', parent_id: TOOLBAR, index: 1, title: '' });
    expect(node).not.toHaveProperty('url');
    expect(await tree.getNode(sep)).toEqual(node);
    expect(SnapshotSchema.safeParse({ taken_at: 0, ...read }).error?.issues).toBeUndefined();
  });

  it("Given a separator among a folder's children, When they are listed, Then it is listed as a separator, not a bookmark", async () => {
    const api = new FirefoxBookmarksStub();
    const tree = new FirefoxBookmarkTree(api);
    const folder = await tree.createFolder(TOOLBAR, 'Dynomark');
    await tree.createBookmark(folder.id, 'Tokio', 'https://tokio.rs/');
    api.addSeparator(folder.id);
    expect((await tree.getChildren(folder.id)).map((n) => n.kind)).toEqual(['bookmark', 'separator']);
  });

  it('Given a separator, When its children are asked for, Then the adapter refuses as for a non-folder', async () => {
    const api = new FirefoxBookmarksStub();
    const sep = api.addSeparator(TOOLBAR);
    await expect(new FirefoxBookmarkTree(api).getChildren(sep)).rejects.toThrow(/no folder/);
  });
});

describe('listenFirefoxBookmarkEvents', () => {
  it('Given a separator and a bookmark created, When the events fire, Then each is a created event of its own kind', async () => {
    const api = eventsApi();
    const stub = new FirefoxBookmarksStub();
    const seen: BookmarkEvent[] = [];
    listenFirefoxBookmarkEvents((e) => seen.push(e), api);
    const sep = stub.addSeparator(TOOLBAR);
    const mark = await stub.create({ parentId: TOOLBAR, title: 'Tokio', url: 'https://tokio.rs/' });
    api.onCreated.fire(sep, await stub.reported(sep));
    api.onCreated.fire(mark.id, mark);
    expect(seen.map((e) => (e.kind === 'created' ? e.node.kind : e.kind))).toEqual(['separator', 'bookmark']);
    expect(seen[0]).not.toHaveProperty('node.url');
  });

  it('Given Firefox has no onChildrenReordered, When listening and each event fires, Then nothing throws and moves, changes and removals arrive', () => {
    const api = eventsApi();
    const seen: BookmarkEvent[] = [];
    listenFirefoxBookmarkEvents((e) => seen.push(e), api);
    api.onMoved.fire('g00000000005', { parentId: TOOLBAR, oldParentId: 'unfiled_____', index: 0, oldIndex: 2 });
    api.onChanged.fire('g00000000005', { title: 'Tokio!' });
    api.onRemoved.fire('g00000000005', { parentId: TOOLBAR, index: 0 });
    expect(seen).toEqual([
      { kind: 'moved', node_id: 'g00000000005', parent_id: TOOLBAR, old_parent_id: 'unfiled_____' },
      { kind: 'changed', node_id: 'g00000000005' },
      { kind: 'removed', node_id: 'g00000000005', parent_id: TOOLBAR },
    ]);
  });
});
