/// <reference types="chrome" />
// nativeTransport.ts -- the TransportPort on chrome.runtime.connectNative
// (design, seam table, "Extension <-> daemon transport"; contract v1 README,
// "Endpoint": host name tds.dynomark). Chrome frames each message; the shim
// behind the host pipes frames to the daemon's socket unchanged.
//
// The link opens lazily on the first send (or event subscription) after it
// was lost, so a caller's re-send is the reconnect; saying hello on the new
// link is the Connection's job, and deciding when to reconnect with nothing to send is the runtime's
// (it watches onLink). Every frame from the daemon is validated against the
// contract schema before anything sees it: a response that fails rejects its
// request with InvalidFrame, anything else that fails is dropped. `error`
// `superseded` (re null) ends the transport for good.

import type { Id } from '../../domain/values.js';
import { TransportLost, type LinkState, type TransportLink, type TransportPort } from '../../ports/transport.js';
import {
  EventSchema,
  ResponseSchema,
  type ErrorMessage,
  type EventMessage,
  type RequestMessage,
  type ResultOf,
} from '../../wire/messages.js';

// --- Types ---

/** The part of a chrome.runtime.Port this adapter uses. */
export interface NativePortLike {
  postMessage(message: unknown): void;
  disconnect(): void;
  readonly onMessage: { addListener(callback: (message: unknown) => void): void };
  readonly onDisconnect: { addListener(callback: () => void): void };
}

/** The part of chrome.runtime this adapter uses. */
export interface NativeRuntimeApi {
  connectNative(application: string): NativePortLike;
  readonly lastError?: { message?: string } | undefined;
}

/** A frame from the daemon that fails the contract schema, answering a request in flight. */
export class InvalidFrame extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InvalidFrame';
  }
}

interface Pending {
  resolve(frame: unknown): void;
  reject(error: Error): void;
}

// --- Constants ---

/** The native-messaging host name (contract v1 README, "Endpoint"). */
export const HOST_NAME = 'tds.dynomark';

// --- Pure helpers ---

function readableRe(frame: unknown): Id | undefined {
  if (typeof frame !== 'object' || frame === null) return undefined;
  const re = (frame as Record<string, unknown>)['re'];
  return typeof re === 'string' ? re : undefined;
}

function hasKey(frame: unknown, key: string): boolean {
  return typeof frame === 'object' && frame !== null && key in frame;
}

// --- The adapter ---

export class NativeMessagingTransport implements TransportPort, TransportLink {
  private readonly hostName: string;
  private port: NativePortLike | undefined;
  private superseded = false;
  private state: LinkState = { state: 'idle' };
  private readonly pending = new Map<Id, Pending>();
  private readonly events = new Set<(event: EventMessage) => void>();
  private readonly links = new Set<(state: LinkState) => void>();

  constructor(
    private readonly runtime: NativeRuntimeApi = chrome.runtime,
    options: { readonly hostName?: string } = {},
  ) {
    this.hostName = options.hostName ?? HOST_NAME;
  }

  send<R extends RequestMessage>(request: R): Promise<ResultOf<R['type']> | ErrorMessage> {
    if (this.superseded) return Promise.reject(new TransportLost('superseded'));
    if (this.pending.has(request.id)) return Promise.reject(new Error(`request ${request.id} is already in flight`));
    const port = this.open();
    const reply = new Promise<ResultOf<R['type']> | ErrorMessage>((resolve, reject) => {
      this.pending.set(request.id, { resolve: (frame) => resolve(frame as ResultOf<R['type']> | ErrorMessage), reject });
    });
    try {
      port.postMessage(request);
    } catch (error) {
      this.lost(port, error instanceof Error ? error.message : String(error));
    }
    return reply;
  }

  /** Listening opens the link (events only flow over an open one); a superseded transport stays closed. */
  onEvent(listener: (event: EventMessage) => void): () => void {
    this.events.add(listener);
    if (!this.superseded) this.open();
    return () => this.events.delete(listener);
  }

  linkState(): LinkState {
    return this.state;
  }

  onLink(listener: (state: LinkState) => void): () => void {
    this.links.add(listener);
    return () => this.links.delete(listener);
  }

  // --- Internals ---

  private open(): NativePortLike {
    if (this.port !== undefined) return this.port;
    const port = this.runtime.connectNative(this.hostName);
    this.port = port;
    port.onMessage.addListener((frame) => this.receive(port, frame));
    port.onDisconnect.addListener(() => this.lost(port, this.runtime.lastError?.message ?? 'disconnected'));
    this.setState({ state: 'connected' });
    return port;
  }

  private receive(port: NativePortLike, frame: unknown): void {
    if (port !== this.port) return;
    if (hasKey(frame, 're')) this.receiveResponse(frame);
    else if (hasKey(frame, 'event_id')) this.receiveEvent(frame);
  }

  private receiveResponse(frame: unknown): void {
    const parsed = ResponseSchema.safeParse(frame);
    if (!parsed.success) {
      const re = readableRe(frame);
      const pending = re === undefined ? undefined : this.pending.get(re);
      if (re !== undefined && pending !== undefined) {
        this.pending.delete(re);
        pending.reject(new InvalidFrame(`response to ${re} fails the contract schema: ${parsed.error.message}`));
      }
      return;
    }
    const response = parsed.data;
    if (response.re === null) {
      if (response.type === 'error' && response.code === 'superseded') this.supersede();
      return;
    }
    const pending = this.pending.get(response.re);
    if (pending === undefined) return;
    this.pending.delete(response.re);
    pending.resolve(response);
  }

  private receiveEvent(frame: unknown): void {
    const parsed = EventSchema.safeParse(frame);
    if (!parsed.success) return;
    [...this.events].forEach((listener) => listener(parsed.data));
  }

  /** The link under `port` is gone: everything in flight is retryable after a reconnect. */
  private lost(port: NativePortLike, detail: string): void {
    if (port !== this.port) return;
    this.port = undefined;
    this.rejectAll(new TransportLost('disconnected'));
    this.setState({ state: 'disconnected', detail });
  }

  private supersede(): void {
    const port = this.port;
    this.superseded = true;
    this.port = undefined;
    port?.disconnect();
    this.rejectAll(new TransportLost('superseded'));
    this.setState({ state: 'superseded' });
  }

  private rejectAll(error: TransportLost): void {
    const inFlight = [...this.pending.values()];
    this.pending.clear();
    inFlight.forEach((p) => p.reject(error));
  }

  private setState(state: LinkState): void {
    this.state = state;
    [...this.links].forEach((listener) => listener(state));
  }
}
