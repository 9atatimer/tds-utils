/// <reference types="chrome" />
// tree.ts -- read and edit the browser's bookmark tree as the user would, from
// an extension page (chrome.bookmarks is only reachable from the extension's
// own contexts). Paths are folder titles below the bookmarks bar, the root
// every Dynomark owned folder lives under by default.

import type { Page } from '@playwright/test';

export interface TreeNode {
  readonly id: string;
  readonly title: string;
  readonly url?: string;
}

export class Tree {
  constructor(private readonly page: Page) {}

  /** The children of the folder at `names` below the bar; undefined when there is no such folder. */
  children(names: readonly string[]): Promise<TreeNode[] | undefined> {
    return this.page.evaluate(async (path) => {
      const [root] = await chrome.bookmarks.getTree();
      let folder = root?.children?.find((n) => n.id === '1');
      for (const name of path) {
        folder = folder?.children?.find((n) => n.url === undefined && n.title === name);
      }
      if (folder === undefined) return undefined;
      return (folder.children ?? []).map((n) => ({ id: n.id, title: n.title, ...(n.url === undefined ? {} : { url: n.url }) }));
    }, names);
  }

  /** The titles of the children of the folder at `names` (empty when it does not exist). */
  async titles(names: readonly string[]): Promise<string[]> {
    return ((await this.children(names)) ?? []).map((n) => n.title);
  }

  /** The folder titles from below the bar down to `id`'s parent; undefined when `id` is gone or not under the bar. */
  pathOf(id: string): Promise<string[] | undefined> {
    return this.page.evaluate(async (nodeId) => {
      const names: string[] = [];
      let [node] = await chrome.bookmarks.get(nodeId).catch(() => []);
      while (node?.parentId !== undefined && node.parentId !== '1') {
        [node] = await chrome.bookmarks.get(node.parentId);
        if (node === undefined) return undefined;
        names.unshift(node.title);
      }
      return node?.parentId === '1' ? names : undefined;
    }, id);
  }

  /** Save `url` into the folder at `names` (the Ctrl+D dialog's effect); the new node's id. */
  create(names: readonly string[], title: string, url?: string): Promise<string> {
    return this.page.evaluate(
      async ({ path, t, u }) => {
        const [root] = await chrome.bookmarks.getTree();
        let folder = root?.children?.find((n) => n.id === '1');
        for (const name of path) folder = folder?.children?.find((n) => n.url === undefined && n.title === name);
        if (folder === undefined) throw new Error(`no folder ${path.join('/')}`);
        const made = await chrome.bookmarks.create({ parentId: folder.id, title: t, ...(u === undefined ? {} : { url: u }) });
        return made.id;
      },
      { path: names, t: title, u: url },
    );
  }

  /** Move node `id` to the end of folder `to` (a drag in the bookmark manager). */
  async move(id: string, to: string): Promise<void> {
    await this.page.evaluate(async ({ node, parentId }) => void (await chrome.bookmarks.move(node, { parentId })), {
      node: id,
      parentId: to,
    });
  }

  /** Every node whose url is `url`. */
  withUrl(url: string): Promise<string[]> {
    return this.page.evaluate(async (u) => (await chrome.bookmarks.search({ url: u })).map((n) => n.id), url);
  }

  /** Every folder titled `title`, anywhere. */
  foldersTitled(title: string): Promise<string[]> {
    return this.page.evaluate(
      async (t) => (await chrome.bookmarks.search({ title: t })).filter((n) => n.url === undefined).map((n) => n.id),
      title,
    );
  }
}
