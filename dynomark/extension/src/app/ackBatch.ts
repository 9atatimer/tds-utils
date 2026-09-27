// ackBatch.ts -- use case "A receipt is delivered" (design, Behaviors and
// Interfaces): ack_batch(receipt, *, transport) -> none. Sends the receipt
// and releases the durable cursor once the daemon has recorded it
// (batch.receipt.result, or error not_found for that batch; contract v1,
// "One batch at a time"). The daemon keys batch.receipt on batch_id, so a
// second delivery records nothing new.

import { withoutSnapshot, type BatchReceipt } from '../domain/batch.js';
import { MAX_FRAME_TO_DAEMON_BYTES, utf8Length } from '../domain/limits.js';
import type { BatchId } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION, type MessageOf } from '../wire/messages.js';
import { DaemonError } from './errors.js';

// --- Types ---

export interface AckDeps {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly storage: StoragePort;
}

// --- Pure helpers ---

/** The batch.receipt frame, with the snapshot omitted when the frame would exceed `maxBytes`. */
function receiptFrame(receipt: BatchReceipt, id: string, maxBytes: number): MessageOf<'batch.receipt'> {
  const full = { v: CONTRACT_VERSION, type: 'batch.receipt', id, receipt } as const;
  if (receipt.snapshot === undefined || utf8Length(JSON.stringify(full)) <= maxBytes) return full;
  return { ...full, receipt: withoutSnapshot(receipt) };
}

// --- Flow ---

async function releaseCursor(batch_id: BatchId, storage: StoragePort): Promise<void> {
  if ((await storage.loadCursor())?.batch_id === batch_id) await storage.clearCursor();
}

/** Deliver the receipt; resolves once the daemon has recorded it and the cursor for its batch is released. */
export async function ackBatch(receipt: BatchReceipt, deps: AckDeps, options: { readonly max_frame_bytes?: number } = {}): Promise<void> {
  const frame = receiptFrame(receipt, deps.ids.next(), options.max_frame_bytes ?? MAX_FRAME_TO_DAEMON_BYTES);
  const response = await deps.transport.send(frame);
  if (response.type === 'error' && response.code !== 'not_found') throw new DaemonError(response);
  await releaseCursor(receipt.batch_id, deps.storage);
}
