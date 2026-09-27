// batchLane.ts -- batch offers, one batch at a time (contract v1 README, "One
// batch at a time", "Cursor and resume", "Delivery and replay"; design,
// "Transport contract", partial failure).
//
// Every batch.offer frame is answered with a batch.receipt, a repeat
// included (from the cursor, nothing redone). The batch whose cursor is open
// stays open until batch.receipt.result for it arrives; an offer of another
// batch meanwhile is held and applied, in the order offered, after it; right
// after every result the extension sends tree.snapshot. After a restart that
// lost an open batch's result, an offer of another batch proves the daemon
// moved on, so the open batch is answered again from its cursor first.

import { receiptFromCursor, type BatchReceipt, type WriteBatch } from '../domain/batch.js';
import { inFlightNodes } from '../domain/move.js';
import { toSnapshot } from '../domain/snapshot.js';
import type { BatchId, NodeId } from '../domain/values.js';
import { ackBatch, type AckDeps } from './ackBatch.js';
import { applyBatch, type ApplyDeps, type BatchContext } from './applyBatch.js';
import { sendTreeSnapshot } from './onConnected.js';

// --- Types ---

export type LaneDeps = ApplyDeps & AckDeps;

/** One offer frame and the promise its caller awaits (resolved once its receipt is acknowledged). */
interface Frame {
  readonly batch: WriteBatch;
  readonly resolve: () => void;
  readonly reject: (error: unknown) => void;
}

/** The batch whose cursor is open: its ops when this worker was offered it, and its receipts still awaiting a result. */
interface OpenBatch {
  readonly batch_id: BatchId;
  readonly batch: WriteBatch | undefined;
  acks: number;
}

// --- The lane ---

export class BatchLane {
  private readonly queue: Frame[] = [];
  private readonly held: Frame[] = [];
  private pumping = false;
  private open: OpenBatch | undefined;

  constructor(
    private readonly context: () => BatchContext | undefined,
    private readonly deps: LaneDeps,
  ) {}

  /** Answer one batch.offer frame; resolves when its receipt has been acknowledged. */
  offer(batch: WriteBatch): Promise<void> {
    return new Promise((resolve, reject) => {
      this.queue.push({ batch, resolve, reject });
      void this.pump();
    });
  }

  /** The nodes the open batch moves itself: a move of one of them is origin extension. */
  inFlight(): ReadonlySet<NodeId> {
    return this.open?.batch === undefined ? new Set() : inFlightNodes(this.open.batch);
  }

  // --- Flow ---

  private async pump(): Promise<void> {
    if (this.pumping) return;
    this.pumping = true;
    try {
      for (let frame = this.queue.shift(); frame !== undefined; frame = this.queue.shift()) await this.process(frame);
    } finally {
      this.pumping = false;
    }
  }

  private async process(frame: Frame): Promise<void> {
    try {
      const openId = this.open?.batch_id ?? (await this.deps.storage.loadCursor())?.batch_id;
      if (openId !== undefined && openId !== frame.batch.batch_id) {
        this.held.push(frame);
        if ((this.open?.acks ?? 0) === 0) await this.answerFromCursor();
        return;
      }
      const context = this.context();
      if (context === undefined) throw new Error('batch offered before hello: no owned roots to apply against');
      const receipt = await applyBatch(frame.batch, context, this.deps);
      this.opened(frame.batch.batch_id, frame.batch);
      void this.acknowledge(receipt, frame);
    } catch (error) {
      frame.reject(error);
    }
  }

  /** The open batch left by an earlier worker, answered again from its cursor when the cursor alone can give its receipt. */
  private async answerFromCursor(): Promise<void> {
    const cursor = await this.deps.storage.loadCursor();
    if (cursor === undefined) return this.release();
    const receipt = receiptFromCursor(cursor, toSnapshot(await this.deps.tree.readTree(), this.deps.clock.now()));
    if (receipt === undefined) return;
    this.opened(cursor.batch_id, this.open?.batch);
    void this.acknowledge(receipt, undefined);
  }

  private opened(batch_id: BatchId, batch: WriteBatch | undefined): void {
    if (this.open?.batch_id === batch_id) this.open.acks += 1;
    else this.open = { batch_id, batch, acks: 1 };
  }

  /** Deliver a receipt; on its result close the batch, send tree.snapshot, then let held offers through. */
  private async acknowledge(receipt: BatchReceipt, frame: Frame | undefined): Promise<void> {
    try {
      await ackBatch(receipt, this.deps);
    } catch (error) {
      if (this.open?.batch_id === receipt.batch_id) this.open.acks -= 1;
      frame?.reject(error);
      return;
    }
    if (this.open?.batch_id === receipt.batch_id) this.open = undefined;
    try {
      await sendTreeSnapshot(this.deps);
      frame?.resolve();
    } catch (error) {
      frame?.reject(error);
    } finally {
      this.release();
    }
  }

  private release(): void {
    if (this.open !== undefined || this.held.length === 0) return;
    this.queue.unshift(...this.held.splice(0));
    void this.pump();
  }
}
