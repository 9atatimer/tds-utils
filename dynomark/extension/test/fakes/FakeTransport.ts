// FakeTransport.ts -- an in-memory TransportPort with its daemon end exposed.
//
// Tests drive the daemon side by hand (nextRequest / answer / emit / drop) or
// let autoAnswer reply at once. Every frame a caller sends is kept in `sent`,
// retries included, so a test can assert on exactly what reached the wire.

import type { ErrorMessage, EventMessage, RequestMessage, ResponseMessage, ResultOf } from '../../src/wire/messages.js';
import { TransportLost, type LinkState, type LossReason, type TransportLink, type TransportPort } from '../../src/ports/transport.js';

/** What dynomark-host answers when no daemon listens (dynomark_daemon/host.py, NO_DAEMON). */
export const NO_DAEMON = 'the dynomark daemon is not running';

interface Pending {
  resolve(response: ResponseMessage): void;
  reject(error: TransportLost): void;
}

export class FakeTransport implements TransportPort, TransportLink {
  /** Every request frame sent, in order, retries included. */
  readonly sent: RequestMessage[] = [];
  /** How many connections have been opened (a send after a drop opens a new one). */
  connections = 0;

  private open = false;
  private superseded = false;
  private down = false;
  private noDaemon = false;
  private responder: ((request: RequestMessage) => ResponseMessage | undefined) | undefined;
  private readonly pending = new Map<string, Pending>();
  private readonly listeners = new Set<(event: EventMessage) => void>();
  private readonly arrivals: RequestMessage[] = [];
  private readonly waiters: ((request: RequestMessage) => void)[] = [];
  private link: LinkState = { state: 'idle' };
  private readonly linkListeners = new Set<(state: LinkState) => void>();

  /** The daemon end of the connection, shaped as the port contract's harness expects. */
  readonly daemon = {
    nextRequest: (): Promise<RequestMessage> => this.nextRequest(),
    answer: (response: ResponseMessage): Promise<void> => Promise.resolve(this.answer(response)),
    emit: (event: EventMessage): Promise<void> => Promise.resolve(this.emit(event)),
    drop: (reason: LossReason): Promise<void> => Promise.resolve(this.drop(reason)),
  };

  send<R extends RequestMessage>(request: R): Promise<ResultOf<R['type']> | ErrorMessage> {
    if (this.superseded) return Promise.reject(new TransportLost('superseded'));
    if (this.down) {
      this.sent.push(request);
      this.setLink({ state: 'disconnected', detail: 'Specified native messaging host not found.' });
      return Promise.reject(new TransportLost('disconnected'));
    }
    if (this.pending.has(request.id)) throw new Error(`FakeTransport: request ${request.id} is already in flight on this connection`);
    const fresh = !this.open;
    if (fresh) {
      this.open = true;
      this.connections += 1;
      this.setLink({ state: 'connected' });
    }
    this.sent.push(request);
    const reply = new Promise<ResponseMessage>((resolve, reject) => this.pending.set(request.id, { resolve, reject }));
    if (this.noDaemon) {
      // dynomark-host's answer_unavailable: the first frame is answered busy, then the host exits.
      if (fresh) {
        this.answer({ v: 1, type: 'error', re: request.id, code: 'busy', message: NO_DAEMON });
        void Promise.resolve().then(() => this.drop('disconnected'));
      }
      return reply as Promise<ResultOf<R['type']> | ErrorMessage>;
    }
    this.arrive(request);
    const response = this.responder?.(request);
    if (response !== undefined) this.answer(response);
    // The daemon answers X with X.result or error; the fake trusts the test's daemon to keep that pairing.
    return reply as Promise<ResultOf<R['type']> | ErrorMessage>;
  }

  onEvent(listener: (event: EventMessage) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  linkState(): LinkState {
    return this.link;
  }

  onLink(listener: (state: LinkState) => void): () => void {
    this.linkListeners.add(listener);
    return () => this.linkListeners.delete(listener);
  }

  /** The daemon is unreachable: every later send is lost at once (a host that fails to start), until reachable again. */
  unreachable(down: boolean): void {
    this.down = down;
  }

  /**
   * The host starts but no daemon listens on the socket (a daemon stopped or
   * restarting), until called with false: as dynomark-host does, the
   * first frame on each new link is answered `error` `busy` and the link then
   * drops; anything else sent on that link is lost with it.
   */
  daemonNotRunning(notRunning: boolean): void {
    this.noDaemon = notRunning;
  }

  /** Answer every later request at once with `respond`'s frame (a request it answers undefined is left in flight); undefined returns to manual answering. */
  autoAnswer(respond: ((request: RequestMessage) => ResponseMessage | undefined) | undefined): void {
    this.responder = respond;
  }

  private nextRequest(): Promise<RequestMessage> {
    const request = this.arrivals.shift();
    if (request !== undefined) return Promise.resolve(request);
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  private arrive(request: RequestMessage): void {
    const waiter = this.waiters.shift();
    if (waiter !== undefined) waiter(request);
    else this.arrivals.push(request);
  }

  private answer(response: ResponseMessage): void {
    const re = response.re;
    const pending = re === null ? undefined : this.pending.get(re);
    if (re === null || pending === undefined) throw new Error(`FakeTransport: no request ${String(re)} in flight to answer`);
    this.pending.delete(re);
    pending.resolve(response);
  }

  private emit(event: EventMessage): void {
    [...this.listeners].forEach((listener) => listener(event));
  }

  private drop(reason: LossReason): void {
    this.open = false;
    if (reason === 'superseded') this.superseded = true;
    const inFlight = [...this.pending.values()];
    this.pending.clear();
    this.arrivals.length = 0;
    inFlight.forEach((p) => p.reject(new TransportLost(reason)));
    this.setLink(reason === 'superseded' ? { state: 'superseded' } : { state: 'disconnected', detail: 'Native host has exited.' });
  }

  private setLink(state: LinkState): void {
    this.link = state;
    [...this.linkListeners].forEach((listener) => listener(state));
  }
}
