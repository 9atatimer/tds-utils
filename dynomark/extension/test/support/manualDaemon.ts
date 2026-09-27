/// <reference types="node" />
// manualDaemon.ts -- the daemon end of the TransportPort contract harness
// over a real unix socket: the test answers, emits and drops by hand, frame
// by frame, as the contract suite's DaemonEnd requires. `delivered` is how
// emit learns that the extension-side listeners have seen an event.

import { createServer, type Server, type Socket } from 'node:net';
import type { LossReason } from '../../src/ports/transport.js';
import type { EventMessage, RequestMessage, ResponseMessage } from '../../src/wire/messages.js';
import { FrameDecoder, encodeFrame } from './framing.js';

export class ManualDaemon {
  private socket: Socket | undefined;
  private readonly arrivals: RequestMessage[] = [];
  private readonly waiters: ((r: RequestMessage) => void)[] = [];
  private readonly seen = new Map<string, () => void>();
  private readonly onConnect: (() => void)[] = [];

  private constructor(
    private readonly server: Server,
    readonly socketPath: string,
  ) {}

  static listen(socketPath: string): Promise<ManualDaemon> {
    return new Promise((resolve, reject) => {
      const server = createServer();
      const daemon = new ManualDaemon(server, socketPath);
      server.on('connection', (socket) => daemon.accept(socket));
      server.once('error', reject);
      server.listen(socketPath, () => resolve(daemon));
    });
  }

  /** The DaemonEnd the contract suite drives. */
  readonly end = {
    nextRequest: (): Promise<RequestMessage> => {
      const r = this.arrivals.shift();
      return r !== undefined ? Promise.resolve(r) : new Promise((resolve) => this.waiters.push(resolve));
    },
    answer: (response: ResponseMessage): Promise<void> => Promise.resolve(this.write(response)),
    emit: async (event: EventMessage): Promise<void> => {
      await this.connected();
      await new Promise<void>((resolve) => {
        this.seen.set(event.event_id, resolve);
        this.write(event);
      });
    },
    drop: (reason: LossReason): Promise<void> => {
      if (reason === 'superseded') this.write({ v: 1, type: 'error', re: null, code: 'superseded', message: 'a newer connection' });
      this.socket?.end();
      this.socket = undefined;
      this.arrivals.length = 0;
      return Promise.resolve();
    },
  };

  /** Forget the current connection and anything unread: the next test's transport starts on a fresh one. */
  reset(): void {
    this.socket?.destroy();
    this.socket = undefined;
    this.arrivals.length = 0;
  }

  /** Every extension-side listener has been called with this event. */
  delivered(event_id: string): void {
    this.seen.get(event_id)?.();
    this.seen.delete(event_id);
  }

  close(): Promise<void> {
    this.socket?.destroy();
    return new Promise((resolve) => this.server.close(() => resolve()));
  }

  /** Resolves once a connection is open (the extension opens it; the daemon never can). */
  private connected(): Promise<void> {
    if (this.socket !== undefined) return Promise.resolve();
    return new Promise((resolve) => this.onConnect.push(resolve));
  }

  private accept(socket: Socket): void {
    this.socket = socket;
    this.onConnect.splice(0).forEach((resolve) => resolve());
    const decoder = new FrameDecoder();
    socket.on('data', (chunk: Buffer) =>
      decoder.push(chunk).forEach((frame) => {
        if (socket !== this.socket) return;
        const waiter = this.waiters.shift();
        if (waiter !== undefined) waiter(frame as RequestMessage);
        else this.arrivals.push(frame as RequestMessage);
      }),
    );
    socket.on('error', () => undefined);
  }

  private write(frame: ResponseMessage | EventMessage): void {
    if (this.socket === undefined) throw new Error('manual daemon: no connection to write to');
    this.socket.write(encodeFrame(frame));
  }
}
