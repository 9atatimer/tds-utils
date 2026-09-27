// values.ts -- the scalar values of the ubiquitous language (design, "Ubiquitous
// language"; contract v1 README, "Envelope" and "Size limits").
//
// Plain aliases: the domain names what a string means, the wire checks its
// shape. Ids are opaque -- compare byte-for-byte, never parse.

/** Milliseconds since the Unix epoch, UTC. */
export type EpochMs = number;

/** An opaque id chosen by its owner (request ids by the extension; job, batch, event, diff and item ids by the daemon). */
export type Id = string;

/** The caller-chosen id of one transport request; the delivery guarantee keys on it. A UUIDv4, never reused for a different body. */
export type RequestId = Id;

/** The daemon's id for one `WriteBatch`. */
export type BatchId = Id;

/** The daemon's id for one `Job`. */
export type JobId = Id;

/** The daemon's id for one durable event; unique and never reused. */
export type EventId = Id;

/** The browser profile's id, generated once by the extension and kept in its settings. */
export type ProfileId = Id;

/** A browser bookmark node id, per profile (Chrome: decimal string; Firefox: guid). */
export type NodeId = string;

/** The daemon host's id from its Config. */
export type HostId = string;

/** A raw URL exactly as the browser reports it. The extension never normalizes. */
export type Url = string;

/** The normalized URL of a corpus entry. Computed only by the daemon; the extension may echo, open or look one up, never compute one. */
export type Identity = string;

/** A bookmark, folder or page title. */
export type Title = string;

/** An opaque pagination cursor minted by the daemon. */
export type Cursor = string;
