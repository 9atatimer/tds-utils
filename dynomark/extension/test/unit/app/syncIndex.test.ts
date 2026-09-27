// syncIndex.test.ts -- design Behaviors row "The local index is synced":
// sync_index(*, transport) -> LocalIndex. Given a changed corpus, When
// synced, Then the index has one row per entry, each at most 512 bytes.
// Contract v1, "Index freshness" and "Pagination": the extension pulls from
// the first page, follows next_cursor, and swaps the new index in only when
// the last page (next_cursor null) arrives; on stale_cursor it restarts from
// the first page.

import { describe, expect, it } from 'vitest';
import { DaemonError } from '../../../src/app/errors.js';
import { syncIndex } from '../../../src/app/syncIndex.js';
import { utf8Length } from '../../../src/domain/limits.js';
import type { LocalIndexRow } from '../../../src/domain/search.js';
import { IndexPullSchema, type RequestMessage, type ResponseMessage } from '../../../src/wire/messages.js';
import { FakeStorage } from '../../fakes/FakeStorage.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';

// --- Builders ---

function row(i: number, extra: Partial<LocalIndexRow> = {}): LocalIndexRow {
  return {
    identity: `https://e${i}.example/`,
    title: `Entry ${i}`,
    path: { root: 'bar', names: ['Dynomark'] },
    tags: ['t'],
    summary: `s${i}`,
    ...extra,
  };
}

/** A daemon serving `corpus()` in pages keyed by row offset; a page error can be injected per call number. */
function pagingDaemon(corpus: () => readonly LocalIndexRow[], fault?: (call: number, r: RequestMessage) => ResponseMessage | undefined) {
  let calls = 0;
  return (r: RequestMessage): ResponseMessage => {
    if (r.type !== 'index.pull') throw new Error(`unexpected ${r.type}`);
    calls += 1;
    const injected = fault?.(calls, r);
    if (injected !== undefined) return injected;
    const offset = r.cursor === undefined ? 0 : Number(r.cursor.slice('off:'.length));
    const limit = r.limit ?? 1000;
    const rows = corpus().slice(offset, offset + limit);
    const next = offset + limit < corpus().length ? `off:${offset + limit}` : null;
    return { v: 1, type: 'index.pull.result', re: r.id, rows, next_cursor: next };
  };
}

function deps(transport: FakeTransport, storage = new FakeStorage()) {
  return { transport, ids: new SequentialIdSource(), storage };
}

// --- Tests ---

describe('Behavior: The local index is synced -- syncIndex({ transport, ids, storage })', () => {
  it('Given a corpus of 2,500 entries, When synced, Then pages are pulled from the first by next_cursor and the index has one row per entry', async () => {
    const corpus = Array.from({ length: 2500 }, (_, i) => row(i));
    const transport = new FakeTransport();
    transport.autoAnswer(pagingDaemon(() => corpus));
    const d = deps(transport);
    const index = await syncIndex(d);
    expect(index).toHaveLength(2500);
    expect(new Set(index.map((r) => r.identity)).size).toBe(2500);
    const pulls = transport.sent.map((r) => IndexPullSchema.parse(r));
    expect(pulls.map((p) => p.cursor)).toEqual([undefined, 'off:1000', 'off:2000']);
    expect(await d.storage.loadLocalIndex()).toEqual(index);
  });

  it('Given a changed corpus, When synced again, Then the index is the new corpus, one row per entry, each at most 512 bytes', async () => {
    let corpus = [row(1), row(2), row(3)];
    const transport = new FakeTransport();
    transport.autoAnswer(pagingDaemon(() => corpus));
    const d = deps(transport);
    await syncIndex(d);
    corpus = [row(1, { title: 'Renamed' }), row(3), row(4)];
    const index = await syncIndex(d);
    expect(index.map((r) => [r.identity, r.title])).toEqual([
      ['https://e1.example/', 'Renamed'],
      ['https://e3.example/', 'Entry 3'],
      ['https://e4.example/', 'Entry 4'],
    ]);
    for (const r of index) expect(utf8Length(JSON.stringify(r))).toBeLessThanOrEqual(512);
  });

  it('Given the same identity on two pages, When synced, Then the index holds one row for it (the later page wins)', async () => {
    const corpus = [row(1), row(2), row(1, { title: 'Newer' })];
    const transport = new FakeTransport();
    transport.autoAnswer(pagingDaemon(() => corpus));
    const index = await syncIndex(deps(transport), { page_limit: 2 });
    expect(index.map((r) => [r.identity, r.title])).toEqual([
      ['https://e1.example/', 'Newer'],
      ['https://e2.example/', 'Entry 2'],
    ]);
  });

  it('Given a row over 512 bytes, When synced, Then it is left out of the index and the rest are kept', async () => {
    const corpus = [row(1), row(2, { summary: 'é'.repeat(250) }), row(3)];
    const transport = new FakeTransport();
    transport.autoAnswer(pagingDaemon(() => corpus));
    expect((await syncIndex(deps(transport))).map((r) => r.identity)).toEqual(['https://e1.example/', 'https://e3.example/']);
  });

  it('Given a pull that fails on its second page, When synced, Then it rejects and the stored index is still the previous one', async () => {
    const previous = [row(9)];
    const storage = new FakeStorage();
    await storage.saveLocalIndex(previous);
    const corpus = Array.from({ length: 5 }, (_, i) => row(i));
    const transport = new FakeTransport();
    transport.autoAnswer(
      pagingDaemon(
        () => corpus,
        (call, r) => (call === 2 ? { v: 1, type: 'error', re: r.id, code: 'internal', message: 'store closed' } : undefined),
      ),
    );
    await expect(syncIndex(deps(transport, storage), { page_limit: 2 })).rejects.toBeInstanceOf(DaemonError);
    expect(await storage.loadLocalIndex()).toEqual(previous);
  });

  it('Given stale_cursor on a later page, When synced, Then the pull restarts from the first page and completes', async () => {
    const corpus = Array.from({ length: 5 }, (_, i) => row(i));
    const transport = new FakeTransport();
    transport.autoAnswer(
      pagingDaemon(
        () => corpus,
        (call, r) => (call === 2 ? { v: 1, type: 'error', re: r.id, code: 'stale_cursor', message: 'expired' } : undefined),
      ),
    );
    const index = await syncIndex(deps(transport), { page_limit: 2 });
    expect(index).toHaveLength(5);
    expect(transport.sent.map((r) => (r.type === 'index.pull' ? (r.cursor ?? 'first') : r.type))).toEqual([
      'first',
      'off:2',
      'first',
      'off:2',
      'off:4',
    ]);
  });

  it('Given stale_cursor on every later page, When synced, Then it gives up after a bounded number of restarts with a DaemonError', async () => {
    const corpus = Array.from({ length: 5 }, (_, i) => row(i));
    const transport = new FakeTransport();
    transport.autoAnswer(
      pagingDaemon(
        () => corpus,
        (_call, r) =>
          r.type === 'index.pull' && r.cursor !== undefined
            ? { v: 1, type: 'error', re: r.id, code: 'stale_cursor', message: 'expired' }
            : undefined,
      ),
    );
    await expect(syncIndex(deps(transport), { page_limit: 2 })).rejects.toMatchObject({ code: 'stale_cursor' });
    expect(transport.sent.length).toBeLessThan(20);
  });
});
