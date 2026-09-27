// transport.ts -- the TransportPort: extension <-> daemon (design, seam table,
// "Extension <-> daemon transport"; contract v1 README, "Envelope" and
// "Endpoint"). Frames are contract v1 messages already validated by the
// adapter; framing, sockets and native messaging stay behind the port.

import type { ErrorMessage, EventMessage, RequestMessage, ResultOf } from '../wire/messages.js';

// --- Types ---

/** Why a connection ended: transport loss (retry by re-sending after reconnect) or `superseded` (never reconnect). */
export type LossReason = 'disconnected' | 'superseded';

/** Rejects every send in flight when the connection ends, and every later send once `superseded`. */
export class TransportLost extends Error {
  readonly reason: LossReason;

  constructor(reason: LossReason) {
    super(`transport lost: ${reason}`);
    this.name = 'TransportLost';
    this.reason = reason;
  }
}

export interface TransportPort {
  /**
   * Send one request and resolve with the one frame whose `re` is its id:
   * its `X.result` or an `error`. Rejects with TransportLost when the
   * connection ends first; the caller re-sends with the same id and body.
   */
  send<R extends RequestMessage>(request: R): Promise<ResultOf<R['type']> | ErrorMessage>;
  /** Subscribe to daemon events, in arrival order; returns the unsubscribe. */
  onEvent(listener: (event: EventMessage) => void): () => void;
}

/** The state of the link under a transport: never opened, open, lost (with the browser's reason), or superseded for good. */
export type LinkState =
  | { readonly state: 'idle' }
  | { readonly state: 'connected' }
  | { readonly state: 'disconnected'; readonly detail: string }
  | { readonly state: 'superseded' };

/**
 * What a transport reports about its link, beside the requests it carries:
 * the runtime reconnects (and says hello again) when the link is lost while
 * nothing is in flight, and the settings page shows it.
 */
export interface TransportLink {
  linkState(): LinkState;
  /** Subscribe to link state changes; returns the unsubscribe. */
  onLink(listener: (state: LinkState) => void): () => void;
}
