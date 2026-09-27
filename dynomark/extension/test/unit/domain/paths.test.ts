// paths.test.ts -- FolderPath resolution, contract v1 README, "Write batches",
// Paths: the root key maps exactly to Snapshot.root_ids (the syncing copy);
// at each level the child FOLDER with the lowest index whose well-formed title
// equals the name exactly; names [] is the top-level folder itself.

import { describe, expect, it } from 'vitest';
import { resolveFolderPath } from '../../../src/domain/paths.js';
import type { NodeKind, SnapshotNode, TreeRead } from '../../../src/domain/tree.js';

// --- Builders ---

function node(id: string, parent_id: string | null, index: number, kind: NodeKind, title: string): SnapshotNode {
  if (kind === 'bookmark') return { id, parent_id, index, kind, title, url: `https://example.com/${id}`, date_added: 0 };
  return { id, parent_id, index, kind, title, date_added: 0 };
}

/** Chrome-shaped: root 0, bar 1, other 2, mobile 3; Follow Up and Dynomark under the bar. */
function chromeTree(extra: readonly SnapshotNode[] = []): TreeRead {
  return {
    root_ids: { bar: '1', other: '2', mobile: '3' },
    nodes: [
      node('0', null, 0, 'folder', ''),
      node('1', '0', 0, 'folder', 'Bookmarks bar'),
      node('2', '0', 1, 'folder', 'Other bookmarks'),
      node('3', '0', 2, 'folder', 'Mobile bookmarks'),
      node('10', '1', 0, 'folder', 'Follow Up'),
      node('11', '1', 1, 'folder', 'Dynomark'),
      node('14', '11', 0, 'folder', 'Rust'),
      ...extra,
    ],
  };
}

// --- Tests ---

describe('resolveFolderPath', () => {
  it('Given names [], When resolved, Then the path is the top-level folder root_ids names', () => {
    expect(resolveFolderPath(chromeTree(), { root: 'other', names: [] })).toBe('2');
  });

  it('Given a nested path, When resolved, Then each level descends into the named child folder', () => {
    expect(resolveFolderPath(chromeTree(), { root: 'bar', names: ['Dynomark', 'Rust'] })).toBe('14');
  });

  it('Given two sibling folders with the same title, When resolved, Then the lower index wins whatever the node order', () => {
    const tree = chromeTree([node('21', '11', 2, 'folder', 'Go'), node('20', '11', 1, 'folder', 'Go')]);
    expect(resolveFolderPath(tree, { root: 'bar', names: ['Dynomark', 'Go'] })).toBe('20');
  });

  it('Given a bookmark and a separator titled like the name at lower indices, When resolved, Then only the folder is picked', () => {
    const tree = chromeTree([
      node('30', '11', 1, 'bookmark', 'Go'),
      node('31', '11', 2, 'separator', 'Go'),
      node('32', '11', 3, 'folder', 'Go'),
    ]);
    expect(resolveFolderPath(tree, { root: 'bar', names: ['Dynomark', 'Go'] })).toBe('32');
  });

  it('Given a name differing in case or whitespace, When resolved, Then nothing matches (titles compare exactly)', () => {
    expect(resolveFolderPath(chromeTree(), { root: 'bar', names: ['dynomark'] })).toBeUndefined();
    expect(resolveFolderPath(chromeTree(), { root: 'bar', names: ['Dynomark '] })).toBeUndefined();
  });

  it('Given a root key the profile does not have (menu on Chrome), When resolved, Then nothing matches', () => {
    expect(resolveFolderPath(chromeTree(), { root: 'menu', names: [] })).toBeUndefined();
  });

  it('Given a local-only copy of the bar titled like the syncing one, When resolved, Then root_ids decides, never the title', () => {
    const tree: TreeRead = {
      root_ids: { bar: '101', other: '2' },
      nodes: [
        node('0', null, 0, 'folder', ''),
        node('1', '0', 0, 'folder', 'Bookmarks bar'),
        node('2', '0', 1, 'folder', 'Other bookmarks'),
        node('101', '0', 3, 'folder', 'Bookmarks bar'),
        node('7', '1', 0, 'folder', 'Dynomark'),
        node('107', '101', 0, 'folder', 'Dynomark'),
      ],
    };
    expect(resolveFolderPath(tree, { root: 'bar', names: ['Dynomark'] })).toBe('107');
  });

  it('Given a folder title cut mid-emoji, When resolved by its well-formed name, Then the well-formed titles match', () => {
    const tree = chromeTree([node('40', '11', 1, 'folder', 'Notes \uD83D')]);
    expect(resolveFolderPath(tree, { root: 'bar', names: ['Dynomark', 'Notes �'] })).toBe('40');
  });
});
