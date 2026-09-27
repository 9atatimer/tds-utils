// chromeBookmarkTree.test.ts -- the BookmarkTreePort on chrome.bookmarks runs
// the port contract over a tiny stand-in for chrome.bookmarks, with and
// without account storage; root_ids name the syncing copies (contract v1
// README, "Write batches", Paths) and Chrome's refusals become BrowserRefused.

import { describe, expect, it } from 'vitest';
import { ChromeBookmarkTree } from '../../../src/adapters/chrome/bookmarkTree.js';
import { BrowserRefused } from '../../../src/ports/bookmarkTree.js';
import { describeBookmarkTreeContract } from '../../port-contracts/bookmarkTree.contract.js';
import { BookmarksApiStub } from '../../stubs/chromeBookmarks.js';

describeBookmarkTreeContract('ChromeBookmarkTree (stubbed chrome.bookmarks)', () => new ChromeBookmarkTree(new BookmarksApiStub()));
describeBookmarkTreeContract(
  'ChromeBookmarkTree (stubbed chrome.bookmarks, account storage)',
  () => new ChromeBookmarkTree(new BookmarksApiStub({ accountStorage: true })),
);

describe('ChromeBookmarkTree', () => {
  it('Given account storage, When read, Then root_ids name the syncing bar, other and mobile folders', async () => {
    const { root_ids } = await new ChromeBookmarkTree(new BookmarksApiStub({ accountStorage: true })).readTree();
    expect(root_ids).toEqual({ bar: '4', other: '5', mobile: '6' });
  });

  it('Given a Chrome with no folderType, When read, Then root_ids fall back to the fixed ids 1, 2 and 3', async () => {
    const api = new BookmarksApiStub();
    api.folderTypes = false;
    expect((await new ChromeBookmarkTree(api).readTree()).root_ids).toEqual({ bar: '1', other: '2', mobile: '3' });
  });

  it('Given fractional dateAdded values, When read, Then every node carries whole EpochMs and no url on a folder', async () => {
    const api = new BookmarksApiStub();
    const tree = new ChromeBookmarkTree(api);
    const folder = await tree.createFolder('1', 'Follow Up');
    expect(Number.isInteger(folder.date_added)).toBe(true);
    expect(folder).not.toHaveProperty('url');
  });

  it('Given a bookmark id, When its children are asked for, Then the adapter refuses as for a non-folder', async () => {
    const tree = new ChromeBookmarkTree(new BookmarksApiStub());
    const mark = await tree.createBookmark('1', 'Mail', 'https://mail.example/');
    await expect(tree.getChildren(mark.id)).rejects.toBeInstanceOf(BrowserRefused);
  });

  it('Given a path, When resolved, Then it goes through the domain Paths rule over one tree read', async () => {
    const tree = new ChromeBookmarkTree(new BookmarksApiStub());
    const dyn = await tree.createFolder('1', 'Dynomark');
    const rust = await tree.createFolder(dyn.id, 'Rust');
    expect(await tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Rust'] })).toBe(rust.id);
    expect(await tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Go'] })).toBeUndefined();
  });
});
