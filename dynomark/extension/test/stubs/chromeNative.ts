// chromeNative.ts -- a tiny chrome.runtime.connectNative stand-in with its
// daemon end exposed in the shape the TransportPort contract's harness
// expects. Messages cross as JSON copies, as Chrome's native messaging
// serializes them; a lost host fires onDisconnect with chrome.runtime.lastError
// set for the duration of the callback, as Chrome does.

import type { NativePortLike, NativeRuntimeApi } from '../../src/adapters/chrome/nativeTransport.js';
import type { LossReason } from '../../src/ports/transport.js';
import type { EventMessage, RequestMessage, ResponseMessage } from '../../src/wire/messages.js';

class StubPort implements NativePortLike {
  readonly messageListeners: ((message: unknown) => void)[] = [];
  readonly disconnectListeners: (() => void)[] = [];
  open = true;
  readonly onMessage = { addListener: (cb: (message: unknown) => void): void => void this.messageListeners.push(cb) };
  readonly onDisconnect = { addListener: (cb: () => void): void => void this.disconnectListeners.push(cb) };

  constructor(private readonly posted: (message: unknown) => void) {}

  postMessage(message: unknown): void {
    if (!this.open) throw new Error('Attempting to use a disconnected port object');
    this.posted(JSON.parse(JSON.stringify(message)) as unknown);
  }

  disconnect(): void {
    this.open = false;
  }
}

export class NativeMessagingStub implements NativeRuntimeApi {
  lastError: { message?: string } | undefined;
  /** Every host name connectNative was called with, in order. */
  readonly connects: string[] = [];
  private port: StubPort | undefined;
  private readonly arrivals: RequestMessage[] = [];
  private readonly waiters: ((r: RequestMessage) => void)[] = [];

  readonly daemon = {
    nextRequest: (): Promise<RequestMessage> => {
      const r = this.arrivals.shift();
      return r !== undefined ? Promise.resolve(r) : new Promise((resolve) => this.waiters.push(resolve));
    },
    answer: (response: ResponseMessage): Promise<void> => Promise.resolve(this.deliver(response)),
    emit: (event: EventMessage): Promise<void> => Promise.resolve(this.deliver(event)),
    drop: (reason: LossReason): Promise<void> => Promise.resolve(this.drop(reason)),
  };

  connectNative(application: string): NativePortLike {
    this.connects.push(application);
    const port = new StubPort((m) => this.arrive(m as RequestMessage));
    this.port = port;
    return port;
  }

  /** Deliver any frame, valid or not, to the open port. */
  deliver(frame: unknown): void {
    const port = this.port;
    if (port === undefined || !port.open) throw new Error('NativeMessagingStub: no open port');
    port.messageListeners.forEach((cb) => cb(JSON.parse(JSON.stringify(frame)) as unknown));
  }

  /** The open port throws on the next postMessage without firing onDisconnect (a port Chrome already closed). */
  breakPostMessage(): void {
    if (this.port !== undefined) this.port.open = false;
  }

  /** The host goes away: onDisconnect fires with lastError set to `detail`. */
  exit(detail = 'Native host has exited.'): void {
    const port = this.port;
    if (port === undefined) return;
    port.open = false;
    this.port = undefined;
    this.arrivals.length = 0;
    this.lastError = { message: detail };
    port.disconnectListeners.forEach((cb) => cb());
    this.lastError = undefined;
  }

  private drop(reason: LossReason): void {
    if (reason === 'superseded') this.deliver({ v: 1, type: 'error', re: null, code: 'superseded', message: 'a newer connection' });
    this.exit();
  }

  private arrive(request: RequestMessage): void {
    const waiter = this.waiters.shift();
    if (waiter !== undefined) waiter(request);
    else this.arrivals.push(request);
  }
}
