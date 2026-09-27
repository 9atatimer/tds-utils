// roles.ts -- the host's role and the connection's mode (design, "HostRole";
// contract v1, "Connection lifecycle").

/** `writer` files; `reader` only indexes. Only the writer's batches ever reach the tree. */
export type HostRole = 'writer' | 'reader';

/** What a connection may do after the version handshake: everything, the read-only set, or nothing but hello. */
export type ConnectionMode = 'full' | 'read_only' | 'refused';

// --- Constants ---

/** The requests a `read_only` connection still serves: the design's "search and chat continue" (contract v1, Connection lifecycle). */
export const READ_ONLY_REQUESTS: ReadonlySet<string> = new Set([
  'hello',
  'status',
  'events.replay',
  'events.ack',
  'index.pull',
  'search',
  'ask',
  'placement.explain',
]);

// --- Predicates ---

/** True when a connection in `mode` may send a request of `type`: full everything, read_only the read-only set, refused only hello. */
export function isPermitted(mode: ConnectionMode, type: string): boolean {
  if (mode === 'full') return true;
  if (mode === 'read_only') return READ_ONLY_REQUESTS.has(type);
  return type === 'hello';
}

// --- Pure helpers ---

/** The mode the contract's version table gives: equal full, extension newer read_only, extension older refused. */
export function modeFor(extension_v: number, daemon_v: number): ConnectionMode {
  if (extension_v === daemon_v) return 'full';
  return extension_v > daemon_v ? 'read_only' : 'refused';
}
