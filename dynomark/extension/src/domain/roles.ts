// roles.ts -- the host's role and the connection's mode (design, "HostRole";
// contract v1, "Connection lifecycle").

/** `writer` files; `reader` only indexes. Only the writer's batches ever reach the tree. */
export type HostRole = 'writer' | 'reader';

/** What a connection may do after the version handshake: everything, the read-only set, or nothing but hello. */
export type ConnectionMode = 'full' | 'read_only' | 'refused';
