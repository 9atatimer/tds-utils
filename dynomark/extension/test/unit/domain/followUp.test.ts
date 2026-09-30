// followUp.test.ts -- which folder is Follow Up (design, "The extension",
// Watch Follow Up: zero folders named Follow Up at startup -> create one
// under the bookmarks bar; more than one -> use the one under the bookmarks
// bar and report the others; contract v1 README, "Connection lifecycle",
// step 1). The rule is pure over a tree read.

import { describe, expect, it } from 'vitest';
import { FOLLOW_UP_TITLE, resolveFollowUp } from '../../../src/domain/followUp.js';
import type { NodeKind, SnapshotNode, TreeRead } from '../../../src/domain/tree.js';

// --- Builders ---

function node(id: string, parent_id: string | null, index: number, kind: NodeKind, title: string): SnapshotNode {
  if (kind === 'bookmark') return { id, parent_id, index, kind, title, url: `https://example.com/${id}`, date_added: 0 };
  return { id, parent_id, index, kind, title, date_added: 0 };
}

/** Chrome-shaped: root 0, bar 1, other 2, mobile 3, plus `extra`. */
function chromeTree(extra: readonly SnapshotNode[] = []): TreeRead {
  return {
    root_ids: { bar: '1', other: '2', mobile: '3' },
    nodes: [
      node('0', null, 0, 'folder', ''),
      node('1', '0', 0, 'folder', 'Bookmarks bar'),
      node('2', '0', 1, 'folder', 'Other bookmarks'),
      node('3', '0', 2, 'folder', 'Mobile bookmarks'),
      ...extra,
    ],
  };
}

// --- Tests ---

describe('resolveFollowUp', () => {
  it('Given the title the extension watches, When read, Then it is exactly "Follow Up"', () => {
    expect(FOLLOW_UP_TITLE).toBe('Follow Up');
  });

  it('Given no folder named Follow Up, When resolved, Then one is to be created directly under the bookmarks bar', () => {
    const tree = chromeTree([node('10', '1', 0, 'bookmark', 'Follow Up'), node('11', '2', 0, 'folder', 'Follow up')]);
    expect(resolveFollowUp(tree)).toEqual({ kind: 'create', parent: { root: 'bar', names: [] }, title: 'Follow Up' });
  });

  it('Given exactly one Follow Up, under Other bookmarks, When resolved, Then it is used, with its path and nothing to report', () => {
    const tree = chromeTree([node('10', '2', 0, 'folder', 'Follow Up')]);
    expect(resolveFollowUp(tree)).toEqual({ kind: 'use', node_id: '10', path: { root: 'other', names: ['Follow Up'] }, others: [] });
  });

  it('Given three Follow Ups, one directly under the bar, When resolved, Then the bar one is used and the other two reported', () => {
    const tree = chromeTree([
      node('10', '2', 0, 'folder', 'Follow Up'),
      node('11', '1', 0, 'folder', 'Reading'),
      node('12', '11', 0, 'folder', 'Follow Up'),
      node('13', '1', 1, 'folder', 'Follow Up'),
    ]);
    expect(resolveFollowUp(tree)).toEqual({
      kind: 'use',
      node_id: '13',
      path: { root: 'bar', names: ['Follow Up'] },
      others: ['10', '12'],
    });
  });

  it('Given two Follow Ups directly under the bar, When resolved, Then the lower index is used (the Paths rule) and the other reported', () => {
    const tree = chromeTree([node('21', '1', 3, 'folder', 'Follow Up'), node('20', '1', 1, 'folder', 'Follow Up')]);
    expect(resolveFollowUp(tree)).toMatchObject({ kind: 'use', node_id: '20', others: ['21'] });
  });

  it('Given two Follow Ups, neither under the bar, When resolved, Then the first in tree order is used and the other reported', () => {
    const tree = chromeTree([
      node('30', '3', 0, 'folder', 'Follow Up'),
      node('31', '2', 0, 'folder', 'Nested'),
      node('32', '31', 0, 'folder', 'Follow Up'),
    ]);
    expect(resolveFollowUp(tree)).toEqual({
      kind: 'use',
      node_id: '32',
      path: { root: 'other', names: ['Nested', 'Follow Up'] },
      others: ['30'],
    });
  });

  it('Given a Follow Up whose path resolves to an earlier same-named sibling chain, When resolved, Then only a path-addressable folder is used', () => {
    const tree = chromeTree([
      node('40', '2', 0, 'folder', 'Reading'),
      node('41', '2', 1, 'folder', 'Reading'),
      node('42', '41', 0, 'folder', 'Follow Up'),
    ]);
    expect(resolveFollowUp(tree)).toEqual({ kind: 'create', parent: { root: 'bar', names: [] }, title: 'Follow Up' });
  });

  it('Given a Follow Up title with a lone surrogate, When resolved, Then titles compare well-formed', () => {
    const tree = chromeTree([node('50', '1', 0, 'folder', 'Follow \uD800Up')]);
    expect(resolveFollowUp(tree, 'Follow \uFFFDUp')).toMatchObject({ kind: 'use', node_id: '50' });
  });
});
