// submitSave.test.ts -- design Behaviors row "A save is submitted":
// submit_save(bookmark, capture, *, transport) -> RequestId. Given a new
// Follow Up node, When submitted twice, Then the daemon holds one job: both
// submissions share one request id (contract v1, "Delivery and replay": a
// repeat reuses the same id and body; ingest is idempotent on the node).
// Everything sent is a valid contract v1 `ingest` frame.

import { describe, expect, it } from 'vitest';
import { DaemonError } from '../../../src/app/errors.js';
import { SubmittedSaves, UrlTooLong, submitSave } from '../../../src/app/submitSave.js';
import type { Capture } from '../../../src/domain/capture.js';
import type { Bookmark } from '../../../src/domain/tree.js';
import { IngestSchema, type RequestMessage, type ResponseMessage } from '../../../src/wire/messages.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';

// --- Builders ---

function bookmark(overrides: Partial<Bookmark> = {}): Bookmark {
  return {
    node_id: '42',
    url: 'https://tokio.rs/tokio/tutorial',
    title: 'Tokio tutorial',
    path: { root: 'bar', names: ['Follow Up'] },
    date_added: 1_790_000_000_000,
    ...overrides,
  };
}

const TAB: Capture = { source: 'tab', text: 'Tokio is an asynchronous runtime.', title: 'Tutorial | Tokio' };

/** A daemon that keeps one job per (node, url), as ingest's idempotency key says, and answers ingest.result. */
function jobKeepingDaemon(): { readonly jobs: Map<string, string>; readonly respond: (r: RequestMessage) => ResponseMessage } {
  const jobs = new Map<string, string>();
  const respond = (r: RequestMessage): ResponseMessage => {
    if (r.type !== 'ingest') throw new Error(`unexpected ${r.type}`);
    const key = `${r.bookmark.node_id} ${r.bookmark.url}`;
    const job_id = jobs.get(key) ?? `job-${jobs.size + 1}`;
    jobs.set(key, job_id);
    const job = {
      job_id,
      node_id: r.bookmark.node_id,
      identity: r.bookmark.url,
      state: 'QUEUED' as const,
      seq: 1,
      attempts: 0,
      backfill: false,
    };
    return { v: 1, type: 'ingest.result', re: r.id, job };
  };
  return { jobs, respond };
}

function distinctIds(sent: readonly RequestMessage[]): string[] {
  return [...new Set(sent.map((r) => r.id))];
}

// --- Tests ---

describe('Behavior: A save is submitted -- submitSave(bookmark, capture, { transport, ids, saves })', () => {
  it('Given a new Follow Up node, When submitted twice, Then one request id reaches the wire and the daemon holds one job', async () => {
    const transport = new FakeTransport();
    const daemon = jobKeepingDaemon();
    transport.autoAnswer(daemon.respond);
    const deps = { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() };
    const first = await submitSave(bookmark(), TAB, deps);
    const second = await submitSave(bookmark(), TAB, deps);
    expect(second).toBe(first);
    expect(distinctIds(transport.sent)).toEqual([first]);
    expect(daemon.jobs.size).toBe(1);
  });

  it('Given a submission still in flight, When the same node is submitted again, Then no second frame is sent and both resolve to its id', async () => {
    const transport = new FakeTransport();
    const daemon = jobKeepingDaemon();
    const deps = { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() };
    const first = submitSave(bookmark(), TAB, deps);
    const second = submitSave(bookmark(), { source: 'none', text: '' }, deps);
    const request = await transport.daemon.nextRequest();
    await transport.daemon.answer(daemon.respond(request));
    expect(await first).toBe(request.id);
    expect(await second).toBe(request.id);
    expect(transport.sent).toHaveLength(1);
  });

  it('Given two different nodes, When each is submitted, Then each gets its own request id', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(jobKeepingDaemon().respond);
    const deps = { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() };
    const a = await submitSave(bookmark(), TAB, deps);
    const b = await submitSave(bookmark({ node_id: '43', url: 'https://serde.rs/' }), TAB, deps);
    expect(a).not.toBe(b);
    expect(distinctIds(transport.sent)).toEqual([a, b]);
  });

  it('Given a bookmark and a tab capture, When submitted, Then the frame is a valid contract v1 ingest carrying both, backfill false', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(jobKeepingDaemon().respond);
    await submitSave(bookmark(), TAB, { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() });
    const frame = IngestSchema.parse(transport.sent[0]);
    expect(frame).toMatchObject({ bookmark: bookmark(), capture: TAB, backfill: false });
  });

  it('Given a title and folder name holding lone surrogates and a title over 4,096 code points, When submitted, Then the frame is well-formed and within the caps', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(jobKeepingDaemon().respond);
    const raw = bookmark({ title: 'x'.repeat(5000) + '\uD83E', path: { root: 'bar', names: ['Follow \uDD80Up'] } });
    await submitSave(raw, TAB, { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() });
    const frame = IngestSchema.parse(transport.sent[0]);
    expect(frame.bookmark.title).toBe('x'.repeat(4096));
    expect(frame.bookmark.path.names).toEqual(['Follow �Up']);
  });

  it('Given a URL over the 65,536 code point cap, When submitted, Then it is not ingested: UrlTooLong and nothing is sent', async () => {
    const transport = new FakeTransport();
    const raw = bookmark({ url: 'https://example.com/' + 'a'.repeat(65_536) });
    await expect(submitSave(raw, TAB, { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() })).rejects.toBeInstanceOf(
      UrlTooLong,
    );
    expect(transport.sent).toEqual([]);
  });

  it('Given the daemon answers error busy, When the node is submitted again, Then it is re-sent with the same request id and body (busy: retry, same id)', async () => {
    const transport = new FakeTransport();
    const deps = { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() };
    transport.autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'busy', message: 'model loading' }));
    await expect(submitSave(bookmark(), TAB, deps)).rejects.toMatchObject({ code: 'busy' });
    transport.autoAnswer(jobKeepingDaemon().respond);
    const id = await submitSave(bookmark(), TAB, deps);
    expect(transport.sent).toHaveLength(2);
    expect(transport.sent[1]).toEqual(transport.sent[0]);
    expect(id).toBe(transport.sent[0]?.id);
  });

  it('Given the daemon answers error invalid, When submitted, Then it rejects with a DaemonError naming the code', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'invalid', message: 'bad body' }));
    const result = submitSave(bookmark(), TAB, { transport, ids: new SequentialIdSource(), saves: new SubmittedSaves() });
    await expect(result).rejects.toBeInstanceOf(DaemonError);
    await expect(result).rejects.toMatchObject({ code: 'invalid' });
  });
    await expect(submitSave(bookmark(), TAB, deps)).rejects.toBeInstanceOf(DaemonError);
    expect(transport.sent).toHaveLength(2);
  });
});
