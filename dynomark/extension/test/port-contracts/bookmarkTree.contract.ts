// bookmarkTree.contract.ts -- what every BookmarkTreePort must do, arranged
// only through the port itself so the real Chrome and Firefox adapters can run
// it unchanged (contract v1 README, "Write batches": Paths, Operations; design,
// "Snapshot" and "Deletions": there is no hard delete).

import { describe, expect, it } from 'vitest';
import type { SnapshotNode, TreeRead } from '../../src/domain/tree.js';
import { BrowserRefused, type BookmarkTreePort } from '../../src/ports/bookmarkTree.js';
import { SnapshotSchema } from '../../src/wire/values.js';

// --- Helpers ---

function childrenOf(tree: TreeRead, parentId: string): SnapshotNode[] {
  return tree.nodes.filter((n) => n.parent_id === parentId).sort((a, b) => a.index - b.index);
}

/** Registers the BookmarkTreePort contract suite for one implementation; `make` returns a fresh profile each call. */
export function describeBookmarkTreeContract(name: string, make: () => BookmarkTreePort): void {
  describe(`BookmarkTreePort contract -- ${name}`, () => {
    it('Given a fresh profile, When the tree is read, Then it is a well-shaped snapshot the wire accepts', async () => {
      const read = await make().readTree();
      expect(SnapshotSchema.safeParse({ taken_at: 0, ...read }).error?.issues).toBeUndefined();
      const roots = read.nodes.filter((n) => n.parent_id === null);
      expect(roots).toHaveLength(1);
      expect(new Set(read.nodes.map((n) => n.id)).size).toBe(read.nodes.length);
      for (const n of read.nodes.filter((x) => x.parent_id !== null)) {
        expect(read.nodes.find((p) => p.id === n.parent_id)?.kind).toBe('folder');
      }
      for (const parent of read.nodes.filter((n) => n.kind === 'folder')) {
        expect(childrenOf(read, parent.id).map((c) => c.index)).toEqual(childrenOf(read, parent.id).map((_, i) => i));
      }
      const topLevel = childrenOf(read, roots[0]?.id ?? '').map((n) => n.id);
      expect(topLevel).toContain(read.root_ids.bar);
      expect(topLevel).toContain(read.root_ids.other);
    });

    it('Given a fresh profile, When a root key with names [] is resolved, Then it is the node root_ids names', async () => {
      const tree = make();
      const { root_ids } = await tree.readTree();
      expect(await tree.resolveFolder({ root: 'bar', names: [] })).toBe(root_ids.bar);
      expect(await tree.resolveFolder({ root: 'other', names: [] })).toBe(root_ids.other);
    });

    it('Given a folder created under the bar, When read back, Then it is the last child, resolvable by path, with a fresh id', async () => {
      const tree = make();
      const { root_ids } = await tree.readTree();
      const before = await tree.getChildren(root_ids.bar);
      const made = await tree.createFolder(root_ids.bar, 'Dynomark');
      expect(made).toMatchObject({ kind: 'folder', title: 'Dynomark', parent_id: root_ids.bar, index: before.length });
      expect(await tree.resolveFolder({ root: 'bar', names: ['Dynomark'] })).toBe(made.id);
      expect(await tree.getNode(made.id)).toEqual(made);
      expect((await tree.readTree()).nodes.filter((n) => n.id === made.id)).toHaveLength(1);
    });

    // The browser canonicalizes a URL as it stores it (Chrome lower-cases the host); that is not the
    // normalization Identity is. A URL the browser reported -- the only kind the contract lets a batch
    // carry -- round-trips exactly, query and fragment included.
    it('Given a bookmark created with a browser-reported URL, When read back, Then the URL is exactly as given (never normalized)', async () => {
      const tree = make();
      const { root_ids } = await tree.readTree();
      const folder = await tree.createFolder(root_ids.other, 'Follow Up');
      const url = 'https://tokio.rs/tokio/tutorial?utm_source=x#intro';
      const made = await tree.createBookmark(folder.id, 'Tokio tutorial', url);
      expect(await tree.getChildren(folder.id)).toEqual([made]);
      expect(made).toMatchObject({ kind: 'bookmark', title: 'Tokio tutorial', url, parent_id: folder.id, index: 0 });
    });

    it('Given two sibling folders with one title, When their path is resolved, Then the lower index wins', async () => {
      const tree = make();
      const { root_ids } = await tree.readTree();
      const first = await tree.createFolder(root_ids.bar, 'Rust');
      await tree.createFolder(root_ids.bar, 'Rust');
      expect(await tree.resolveFolder({ root: 'bar', names: ['Rust'] })).toBe(first.id);
    });

    it('Given a bookmark moved to another folder, When read back, Then it keeps its id, sits last there, and its old siblings close the gap', async () => {
      const tree = make();
      const { root_ids } = await tree.readTree();
      const from = await tree.createFolder(root_ids.bar, 'Follow Up');
      const to = await tree.createFolder(root_ids.bar, 'Dynomark');
      await tree.createBookmark(to.id, 'Already here', 'https://example.com/a');
      const moving = await tree.createBookmark(from.id, 'Tokio', 'https://tokio.rs/');
      const staying = await tree.createBookmark(from.id, 'Serde', 'https://serde.rs/');
      const moved = await tree.move(moving.id, to.id);
      expect(moved).toMatchObject({ id: moving.id, parent_id: to.id, index: 1 });
      expect(await tree.getNode(staying.id)).toMatchObject({ parent_id: from.id, index: 0 });
    });

    it('Given a node id nobody holds, When read, Then getNode answers undefined and getChildren refuses', async () => {
      const tree = make();
      expect(await tree.getNode('no-such-node')).toBeUndefined();
      await expect(tree.getChildren('no-such-node')).rejects.toBeInstanceOf(BrowserRefused);
    });

    it('Given a missing parent or node, When created into or moved, Then the browser refuses and the tree is unchanged', async () => {
      const tree = make();
      const { root_ids } = await tree.readTree();
      const before = await tree.readTree();
      await expect(tree.createFolder('no-such-node', 'X')).rejects.toBeInstanceOf(BrowserRefused);
      await expect(tree.createBookmark('no-such-node', 'X', 'https://x.example/')).rejects.toBeInstanceOf(BrowserRefused);
      await expect(tree.move('no-such-node', root_ids.bar)).rejects.toBeInstanceOf(BrowserRefused);
      expect(await tree.readTree()).toEqual(before);
    });

    it('Given the browser root, a top-level folder, a bookmark and a descendant, When used against the rules, Then each call is refused', async () => {
      const tree = make();
      const read = await tree.readTree();
      const rootId = read.nodes.find((n) => n.parent_id === null)?.id ?? '';
      const outer = await tree.createFolder(read.root_ids.bar, 'Outer');
      const inner = await tree.createFolder(outer.id, 'Inner');
      const leaf = await tree.createBookmark(outer.id, 'Leaf', 'https://leaf.example/');
      await expect(tree.createFolder(rootId, 'Loose')).rejects.toBeInstanceOf(BrowserRefused);
      await expect(tree.move(read.root_ids.bar, read.root_ids.other)).rejects.toBeInstanceOf(BrowserRefused);
      await expect(tree.createFolder(leaf.id, 'Under a bookmark')).rejects.toBeInstanceOf(BrowserRefused);
      await expect(tree.move(outer.id, inner.id)).rejects.toBeInstanceOf(BrowserRefused);
    });
  });
}
