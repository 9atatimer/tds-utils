// trace.test.ts -- the Trace test (coding skill, section 1.2): every
// extension-side row of the design's Behaviors and Interfaces table resolves
// to one exported application function with the table's signature: values
// first, ports in a trailing deps object. The `satisfies` clauses are the
// check (tsc fails on a drifted signature); the runtime assertion pins the
// count of required parameters, so a value input cannot silently vanish.

import { describe, expect, it } from 'vitest';
import { ackBatch } from '../../src/app/ackBatch.js';
import { applyBatch, type BatchContext } from '../../src/app/applyBatch.js';
import { capture } from '../../src/app/capture.js';
import { recordMove } from '../../src/app/recordMove.js';
import { searchLocal } from '../../src/app/searchLocal.js';
import { searchRemote } from '../../src/app/searchRemote.js';
import { submitSave, type SubmittedSaves } from '../../src/app/submitSave.js';
import { syncIndex } from '../../src/app/syncIndex.js';
import type { BatchReceipt, WriteBatch } from '../../src/domain/batch.js';
import type { Capture } from '../../src/domain/capture.js';
import type { Move, MoveFeedback } from '../../src/domain/move.js';
import type { HostRole } from '../../src/domain/roles.js';
import type { Frecency, Hit, LocalIndex, Query } from '../../src/domain/search.js';
import type { Bookmark } from '../../src/domain/tree.js';
import type { RequestId } from '../../src/domain/values.js';
import type { BookmarkTreePort } from '../../src/ports/bookmarkTree.js';
import type { Clock } from '../../src/ports/clock.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';
import type { IdSource } from '../../src/ports/idSource.js';
import type { StoragePort } from '../../src/ports/storage.js';
import type { TransportPort } from '../../src/ports/transport.js';

// --- The table, as types ---

interface Talk {
  readonly transport: TransportPort;
  readonly ids: IdSource;
}

const ROWS = {
  'Content is captured from the open tab': [
    capture satisfies (bookmark: Bookmark, deps: { readonly content: ContentSourcePort }) => Promise<Capture>,
    2,
  ],
  'A save is submitted': [
    submitSave satisfies (bookmark: Bookmark, capture: Capture, deps: Talk & { readonly saves: SubmittedSaves }) => Promise<RequestId>,
    3,
  ],
  'Tier-1 search': [searchLocal satisfies (query: Query, index: LocalIndex, frecency: Frecency) => Hit[], 3],
  'Tier-2 search is requested': [searchRemote satisfies (query: Query, deps: Talk) => Promise<Hit[]>, 2],
  'The local index is synced': [syncIndex satisfies (deps: Talk & { readonly storage: StoragePort }) => Promise<LocalIndex>, 1],
  'A batch is applied / resumes after termination / fails midway': [
    applyBatch satisfies (
      batch: WriteBatch,
      context: BatchContext,
      deps: { readonly tree: BookmarkTreePort; readonly storage: StoragePort; readonly clock: Clock },
    ) => Promise<BatchReceipt>,
    3,
  ],
  'A receipt is delivered': [
    ackBatch satisfies (receipt: BatchReceipt, deps: Talk & { readonly storage: StoragePort }) => Promise<void>,
    2,
  ],
  'A user move becomes feedback': [recordMove satisfies (move: Move, role: HostRole) => MoveFeedback | undefined, 2],
} as const;

// --- Tests ---

describe('Trace: each extension-side Behaviors row has one application function with its signature', () => {
  it.each(Object.entries(ROWS))(
    'Given the row "%s", When its use case is imported from src/app, Then it takes its values, then one deps object',
    (_row, [fn, required]) => {
      expect(typeof fn).toBe('function');
      expect(fn.length).toBe(required);
    },
  );
});
