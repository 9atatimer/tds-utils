// transport.contract.ts -- what every TransportPort must do (design,
// "Transport contract"; contract v1 README, "Envelope" and "Endpoint"):
// requests go out with a caller-chosen id, each is answered by exactly one
// frame (X.result or error) whose re is that id, in any order; events arrive
// as a stream; a lost connection fails what is in flight so the caller can
// re-send after reconnecting; a superseded connection is never reconnected.

import { describe, expect, it } from 'vitest';
import type { EventMessage, RequestMessage, ResponseMessage } from '../../src/wire/messages.js';
import { TransportLost, type LossReason, type TransportPort } from '../../src/ports/transport.js';

/** The daemon end of the harness: what a real adapter's test double on the socket side must offer. */
export interface DaemonEnd {
  /** The next request frame to reach the daemon, in arrival order. */
  nextRequest(): Promise<RequestMessage>;
  /** Send a response frame; resolves once the transport has taken it. */
  answer(response: ResponseMessage): Promise<void>;
  /** Push an event frame; resolves once every listener has been called. */
  emit(event: EventMessage): Promise<void>;
  /** End the connection: `disconnected` (transport loss) or `superseded` (error superseded, re null). */
  drop(reason: LossReason): Promise<void>;
}

export interface TransportHarness {
  readonly transport: TransportPort;
  readonly daemon: DaemonEnd;
}

// --- Builders ---

function status(id: string): RequestMessage {
  return { v: 1, type: 'status', id };
}

function snapshotResult(re: string): ResponseMessage {
  return { v: 1, type: 'tree.snapshot.result', re };
}

function statusResult(re: string): ResponseMessage {
  return {
    v: 1,
    type: 'status.result',
    re,
    role: 'writer',
    host_id: 'mbp',
    contract_version: 1,
    models: { embedding: { id: 'nomic-embed-text', local: true }, completion: { id: 'llama3.1:8b', local: true } },
    queue_depth: 0,
  };
}

function jobUpdated(event_id: string): EventMessage {
  return {
    v: 1,
    type: 'job.updated',
    event_id,
    job: { job_id: 'job-1', node_id: '42', identity: 'https://tokio.rs/', state: 'FILED', seq: 3, attempts: 1, backfill: false },
  };
}

/** Registers the TransportPort contract suite for one implementation. */
export function describeTransportContract(name: string, make: () => TransportHarness): void {
  describe(`TransportPort contract -- ${name}`, () => {
    it('Given a request sent, When the daemon answers with re = its id, Then send resolves with that response', async () => {
      const { transport, daemon } = make();
      const reply = transport.send(status('req-1'));
      expect(await daemon.nextRequest()).toEqual(status('req-1'));
      await daemon.answer(statusResult('req-1'));
      expect(await reply).toEqual(statusResult('req-1'));
    });

    it('Given two requests in flight, When answered in reverse order, Then each send resolves with its own response', async () => {
      const { transport, daemon } = make();
      const first = transport.send(status('req-1'));
      const second = transport.send({ v: 1, type: 'tree.snapshot', id: 'req-2', snapshot: SNAPSHOT });
      await daemon.nextRequest();
      await daemon.nextRequest();
      await daemon.answer(snapshotResult('req-2'));
      await daemon.answer(statusResult('req-1'));
      expect(await first).toEqual(statusResult('req-1'));
      expect(await second).toEqual(snapshotResult('req-2'));
    });

    it('Given a request the daemon refuses, When it answers error with re = the id, Then send resolves with the error frame', async () => {
      const { transport, daemon } = make();
      const reply = transport.send({ v: 1, type: 'undo', id: 'req-9', batch_id: 'batch-1' });
      await daemon.nextRequest();
      const refusal: ResponseMessage = { v: 1, type: 'error', re: 'req-9', code: 'not_writer', message: 'reader host' };
      await daemon.answer(refusal);
      expect(await reply).toEqual(refusal);
    });

    it('Given two listeners, When the daemon emits two events, Then each gets both in order, and an unsubscribed one gets no more', async () => {
      const { transport, daemon } = make();
      const a: string[] = [];
      const b: string[] = [];
      const stopA = transport.onEvent((e) => a.push(e.event_id));
      transport.onEvent((e) => b.push(e.event_id));
      await daemon.emit(jobUpdated('evt-1'));
      await daemon.emit(jobUpdated('evt-2'));
      stopA();
      await daemon.emit(jobUpdated('evt-3'));
      expect(a).toEqual(['evt-1', 'evt-2']);
      expect(b).toEqual(['evt-1', 'evt-2', 'evt-3']);
    });

    it('Given a request in flight, When the connection is lost, Then it rejects as retryable, and a re-send with the same id is answered', async () => {
      const { transport, daemon } = make();
      const lost = transport.send(status('req-1'));
      await daemon.nextRequest();
      await daemon.drop('disconnected');
      await expect(lost).rejects.toEqual(new TransportLost('disconnected'));
      const retry = transport.send(status('req-1'));
      expect(await daemon.nextRequest()).toEqual(status('req-1'));
      await daemon.answer(statusResult('req-1'));
      expect(await retry).toEqual(statusResult('req-1'));
    });

    it('Given the connection is superseded, When anything is in flight or sent later, Then it rejects as superseded and never reconnects', async () => {
      const { transport, daemon } = make();
      const inFlight = transport.send(status('req-1'));
      await daemon.nextRequest();
      await daemon.drop('superseded');
      await expect(inFlight).rejects.toMatchObject({ reason: 'superseded' });
      await expect(transport.send(status('req-2'))).rejects.toMatchObject({ reason: 'superseded' });
    });
  });
}

const SNAPSHOT = {
  taken_at: 1,
  root_ids: { bar: '1', other: '2' },
  nodes: [{ id: '0', parent_id: null, index: 0, kind: 'folder' as const, title: '', date_added: 0 }],
};
