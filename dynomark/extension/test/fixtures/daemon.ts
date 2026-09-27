// daemon.ts -- a scripted daemon end for FakeTransport: answers every request
// the way a contract v1 daemon would for the connection lifecycle (hello,
// tree.snapshot, events.replay, events.ack, index.pull, batch.receipt,
// ingest, move.observed), with the hello.result a test chooses.

import type { HostRole, ConnectionMode } from '../../src/domain/roles.js';
import type { OwnedRoots } from '../../src/domain/tree.js';
import type { RequestMessage, ResponseMessage } from '../../src/wire/messages.js';
import { ROOTS } from './ownedTree.js';

// --- Types ---

export interface HelloAnswer {
  readonly v?: number;
  readonly mode?: ConnectionMode;
  readonly role?: HostRole;
  readonly host_id?: string;
  readonly owned_roots?: OwnedRoots;
}

// --- Builders ---

/** A responder for FakeTransport.autoAnswer; `hello` shapes the hello.result. */
export function scriptedDaemon(hello: HelloAnswer = {}): (r: RequestMessage) => ResponseMessage {
  return (r) => {
    switch (r.type) {
      case 'hello':
        return {
          v: hello.v ?? 1,
          type: 'hello.result',
          re: r.id,
          host_id: hello.host_id ?? 'mbp',
          role: hello.role ?? 'writer',
          mode: hello.mode ?? 'full',
          owned_roots: hello.owned_roots ?? ROOTS,
        };
      case 'tree.snapshot':
        return { v: 1, type: 'tree.snapshot.result', re: r.id };
      case 'events.replay':
        return { v: 1, type: 'events.replay.result', re: r.id, count: 0 };
      case 'events.ack':
        return { v: 1, type: 'events.ack.result', re: r.id };
      case 'index.pull':
        return { v: 1, type: 'index.pull.result', re: r.id, rows: [], next_cursor: null };
      case 'batch.receipt':
        return { v: 1, type: 'batch.receipt.result', re: r.id };
      case 'move.observed':
        return { v: 1, type: 'move.observed.result', re: r.id };
      case 'status':
        return {
          v: 1,
          type: 'status.result',
          re: r.id,
          role: hello.role ?? 'writer',
          host_id: hello.host_id ?? 'mbp',
          contract_version: 1,
          models: { embedding: { id: 'nomic-embed-text', local: true }, completion: { id: 'llama3.1:8b', local: true } },
          queue_depth: 2,
        };
      case 'search':
        return { v: 1, type: 'search.result', re: r.id, hits: [], next_cursor: null };
      case 'ingest': {
        const job = {
          job_id: `job-${r.bookmark.node_id}`,
          node_id: r.bookmark.node_id,
          identity: r.bookmark.url,
          state: 'QUEUED' as const,
          seq: 1,
          attempts: 0,
          backfill: false,
        };
        return { v: 1, type: 'ingest.result', re: r.id, job };
      }
      default:
        return { v: 1, type: 'error', re: r.id, code: 'internal', message: `scripted daemon has no answer for ${r.type}` };
    }
  };
}
