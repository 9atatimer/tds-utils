/// <reference types="node" />
// fakeDaemon.ts -- a scriptable contract v1 daemon on a unix socket, for
// tests that run the real extension in a real browser: the browser starts
// the pipe host (pipe-host.mjs), which pipes to this socket. Every frame the
// extension sends is validated against the contract schema (a frame that
// fails is kept in `invalid`, and the connection is closed as the contract
// says) and recorded; the lifecycle requests are answered as a writer daemon
// would; batch offers are durable until a receipt for them is recorded, and
// re-sent on events.replay.

import { createServer, type Server, type Socket } from 'node:net';
import { unlinkSync } from 'node:fs';
import type { LocalIndexRow } from '../../src/domain/search.js';
import type { WriteBatch } from '../../src/domain/batch.js';
import type { Job } from '../../src/domain/jobs.js';
import { RequestSchema, type EventMessage, type RequestMessage, type ResponseMessage, type ResultOf } from '../../src/wire/messages.js';
import { FrameDecoder, encodeFrame } from './framing.js';

// --- Types ---

/** One request as it reached the daemon, with the connection it came on (1-based, in connect order). */
export interface Received {
  readonly conn: number;
  readonly frame: RequestMessage;
}

interface Conn {
  readonly id: number;
  readonly socket: Socket;
  hello: boolean;
  snapshot: boolean;
  closed: boolean;
}

interface Waiter {
  readonly match: (r: Received) => boolean;
  readonly resolve: (r: Received) => void;
}

type Answer = (r: RequestMessage) => ResponseMessage | undefined;

// --- Constants ---

export const FAKE_HOST_ID = 'e2e-host';
const DEFAULT_WAIT_MS = 20_000;

// --- The daemon ---

export class FakeDaemon {
  readonly received: Received[] = [];
  readonly invalid: unknown[] = [];
  /** What index.pull returns (one page). */
  indexRows: LocalIndexRow[] = [];
  /** What search returns (one page). */
  searchHits: ResultOf<'search'>['hits'][number][] = [];
  /** What batch.list returns (one page). */
  batches: ResultOf<'batch.list'>['batches'][number][] = [];
  /** What job.list returns (one page). */
  failedJobs: Job[] = [];
  /** Answers tried before the built-in ones; undefined falls through. */
  extra: Answer = () => undefined;

  private readonly conns = new Map<number, Conn>();
  private readonly offers = new Map<string, WriteBatch>();
  private readonly receipts = new Map<string, Extract<RequestMessage, { type: 'batch.receipt' }>['receipt']>();
  private readonly waiters = new Set<Waiter>();
  private readonly closeWaiters: (() => void)[] = [];
  private nextConn = 0;
  private nextJob = 0;

  private constructor(
    private readonly server: Server,
    readonly socketPath: string,
  ) {}

  /** Listen on `socketPath` (a fresh path in a private temp directory). */
  static listen(socketPath: string): Promise<FakeDaemon> {
    return new Promise((resolve, reject) => {
      const server = createServer();
      const daemon = new FakeDaemon(server, socketPath);
      server.on('connection', (socket) => daemon.accept(socket));
      server.once('error', reject);
      server.listen(socketPath, () => resolve(daemon));
    });
  }

  /** Offer a batch: durable until its receipt is recorded; sent now to every connection past its first tree.snapshot. */
  offer(batch: WriteBatch): void {
    this.offers.set(batch.batch_id, batch);
    for (const conn of this.conns.values()) if (conn.snapshot && !conn.closed) this.sendOffer(conn, batch);
  }

  /** The first request after index `from` that matches, waiting for it if need be. */
  waitFor(
    match: (frame: RequestMessage) => boolean,
    options: { readonly from?: number; readonly timeoutMs?: number } = {},
  ): Promise<RequestMessage> {
    const test = (r: Received) => match(r.frame);
    const found = this.received.slice(options.from ?? 0).find(test);
    if (found !== undefined) return Promise.resolve(found.frame);
    return new Promise((resolve, reject) => {
      const waiter: Waiter = {
        match: test,
        resolve: (r) => {
          clearTimeout(timer);
          resolve(r.frame);
        },
      };
      const timer = setTimeout(() => {
        this.waiters.delete(waiter);
        reject(new Error(`fake daemon: no matching request; received ${this.received.map((r) => `${r.conn}:${r.frame.type}`).join(' ')}`));
      }, options.timeoutMs ?? DEFAULT_WAIT_MS);
      this.waiters.add(waiter);
    });
  }

  /** Resolves once no connection is open. */
  allClosed(): Promise<void> {
    if ([...this.conns.values()].every((c) => c.closed)) return Promise.resolve();
    return new Promise((resolve) => this.closeWaiters.push(resolve));
  }

  /** How many connections have been opened. */
  connections(): number {
    return this.nextConn;
  }

  /** Every request of `type`, in arrival order. */
  of<T extends RequestMessage['type']>(type: T): Extract<RequestMessage, { type: T }>[] {
    return this.received.map((r) => r.frame).filter((f): f is Extract<RequestMessage, { type: T }> => f.type === type);
  }

  close(): Promise<void> {
    for (const conn of this.conns.values()) conn.socket.destroy();
    return new Promise((resolve) => {
      this.server.close(() => {
        try {
          unlinkSync(this.socketPath);
        } catch {
          // already gone
        }
        resolve();
      });
    });
  }

  // --- Connections ---

  private accept(socket: Socket): void {
    this.nextConn += 1;
    const conn: Conn = { id: this.nextConn, socket, hello: false, snapshot: false, closed: false };
    this.conns.set(conn.id, conn);
    const decoder = new FrameDecoder();
    socket.on('data', (chunk: Buffer) => decoder.push(chunk).forEach((frame) => this.receive(conn, frame)));
    socket.on('close', () => {
      conn.closed = true;
      if ([...this.conns.values()].every((c) => c.closed)) this.closeWaiters.splice(0).forEach((resolve) => resolve());
    });
    socket.on('error', () => undefined);
  }

  private receive(conn: Conn, raw: unknown): void {
    const parsed = RequestSchema.safeParse(raw);
    if (!parsed.success) {
      this.invalid.push(raw);
      conn.socket.destroy();
      return;
    }
    const received: Received = { conn: conn.id, frame: parsed.data };
    this.received.push(received);
    const answer = this.answer(conn, parsed.data);
    if (answer !== undefined) this.write(conn, answer);
    for (const waiter of [...this.waiters]) {
      if (!waiter.match(received)) continue;
      this.waiters.delete(waiter);
      waiter.resolve(received);
    }
  }

  private write(conn: Conn, frame: ResponseMessage | EventMessage): void {
    if (!conn.closed) conn.socket.write(encodeFrame(frame));
  }

  private sendOffer(conn: Conn, batch: WriteBatch): void {
    this.write(conn, { v: 1, type: 'batch.offer', event_id: `evt-${batch.batch_id}`, batch });
  }

  // --- Answers ---

  private answer(conn: Conn, r: RequestMessage): ResponseMessage | undefined {
    return this.extra(r) ?? this.builtIn(conn, r);
  }

  private builtIn(conn: Conn, r: RequestMessage): ResponseMessage | undefined {
    switch (r.type) {
      case 'hello':
        conn.hello = true;
        return {
          v: 1,
          type: 'hello.result',
          re: r.id,
          host_id: FAKE_HOST_ID,
          role: 'writer',
          mode: 'full',
          owned_roots: {
            follow_up: r.follow_up,
            dynomark: { root: 'bar', names: ['Dynomark'] },
            graveyard: { root: 'bar', names: ['Graveyard'] },
          },
        };
      case 'tree.snapshot':
        conn.snapshot = true;
        return { v: 1, type: 'tree.snapshot.result', re: r.id };
      case 'events.replay': {
        const pending = conn.snapshot ? [...this.offers.values()] : [];
        pending.forEach((batch) => this.sendOffer(conn, batch));
        return { v: 1, type: 'events.replay.result', re: r.id, count: pending.length };
      }
      case 'events.ack':
        return { v: 1, type: 'events.ack.result', re: r.id };
      case 'index.pull':
        return { v: 1, type: 'index.pull.result', re: r.id, rows: this.indexRows, next_cursor: null };
      case 'ingest':
        return { v: 1, type: 'ingest.result', re: r.id, job: this.jobFor(r) };
      case 'move.observed':
        return { v: 1, type: 'move.observed.result', re: r.id };
      case 'batch.receipt':
        if (!this.receipts.has(r.receipt.batch_id)) this.receipts.set(r.receipt.batch_id, r.receipt);
        this.offers.delete(r.receipt.batch_id);
        return { v: 1, type: 'batch.receipt.result', re: r.id };
      case 'status':
        return {
          v: 1,
          type: 'status.result',
          re: r.id,
          role: 'writer',
          host_id: FAKE_HOST_ID,
          contract_version: 1,
          models: { embedding: { id: 'nomic-embed-text', local: true }, completion: { id: 'llama3.1:8b', local: true } },
          queue_depth: 3,
        };
      case 'search':
        return { v: 1, type: 'search.result', re: r.id, hits: this.searchHits, next_cursor: null };
      case 'batch.list':
        return { v: 1, type: 'batch.list.result', re: r.id, batches: this.batches, next_cursor: null };
      case 'job.list':
        return { v: 1, type: 'job.list.result', re: r.id, jobs: this.failedJobs, next_cursor: null };
      default:
        return { v: 1, type: 'error', re: r.id, code: 'internal', message: `fake daemon has no answer for ${r.type}` };
    }
  }

  private jobFor(r: Extract<RequestMessage, { type: 'ingest' }>): Job {
    this.nextJob += 1;
    return {
      job_id: `job-${this.nextJob}`,
      node_id: r.bookmark.node_id,
      identity: r.bookmark.url,
      state: 'QUEUED',
      seq: 1,
      attempts: 0,
      backfill: r.backfill,
    };
  }
}
