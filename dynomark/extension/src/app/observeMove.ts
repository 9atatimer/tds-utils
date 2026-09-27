// observeMove.ts -- the extension's "Record feedback" responsibility (design,
// "The extension"): on every onMoved whose source and destination are owned,
// stamp the Move with its origin (extension for nodes the in-flight batch
// names) and the time, report it as move.observed, and apply record_move.
// The browser adapter turns parent ids into FolderPaths before calling this.
//
// A report is feedback the daemon cannot recover from the tree, so it is
// delivered at least once (contract v1, "Delivery and replay"): the frame is
// kept in storage from before it is first sent until it is answered
// move.observed.result or refused for good. A busy or internal answer comes
// on a link that stays up, so the identical frame is re-sent after a backoff;
// a lost link, or a worker that dies first, leaves it to the next full
// hello, which re-sends every kept frame this worker is not already sending.

import { backoffDelay } from '../domain/backoff.js';
import { fitPath } from '../domain/limits.js';
import { isOwnedMove, moveOrigin, type Move, type MoveFeedback } from '../domain/move.js';
import { withPendingMove, withoutPendingMove, type PendingMove } from '../domain/pendingMoves.js';
import type { HostRole } from '../domain/roles.js';
import type { FolderPath, OwnedRoots } from '../domain/tree.js';
import type { NodeId, RequestId, Url } from '../domain/values.js';
import type { Clock } from '../ports/clock.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
import type { Timer } from '../ports/timer.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION, type MessageOf } from '../wire/messages.js';
import { DaemonError, isRetryable, resultOrThrow } from './errors.js';
import { recordMove } from './recordMove.js';

// --- Types ---

type MoveFrame = MessageOf<'move.observed'>;

/** A move as the browser reported it, its parents already expressed as paths. */
export interface ObservedMove {
  readonly node_id: NodeId;
  readonly url?: Url;
  readonly from: FolderPath;
  readonly to: FolderPath;
}

export interface MoveContext {
  readonly owned_roots: OwnedRoots;
  /** The nodes whose reported move the extension itself issued (to that destination); empty when none is. */
  readonly in_flight: ReadonlySet<NodeId>;
}

export interface ReportDeps {
  readonly transport: TransportPort;
  readonly moves: ReportedMoves;
  readonly timer: Timer;
  /** Handed each retry this schedules (the caller reports its failure). */
  track(work: Promise<unknown>): void;
}

export interface ObserveDeps extends ReportDeps {
  readonly ids: IdSource;
  readonly clock: Clock;
}

// --- The kept reports ---

/**
 * The move reports not yet answered: in storage (read once per worker, then
 * written through in call order), and which of them this worker is sending
 * or waiting to re-send.
 */
export class ReportedMoves {
  private readonly active = new Set<RequestId>();
  private pending: readonly PendingMove[] | undefined;
  private loading: Promise<readonly PendingMove[]> | undefined;

  constructor(private readonly storage: StoragePort) {}

  /** The kept reports this worker is not sending; each is marked as being sent. */
  async adopt(): Promise<PendingMove[]> {
    await this.load();
    const idle = (this.pending ?? []).filter((kept) => !this.active.has(kept.id));
    for (const kept of idle) this.active.add(kept.id);
    return idle;
  }

  /** Keep `frame` until it is answered, and mark it as being sent. */
  async hold(frame: MoveFrame): Promise<void> {
    this.active.add(frame.id);
    await this.load();
    const current = this.pending ?? [];
    if (!current.some((kept) => kept.id === frame.id)) await this.store(withPendingMove(current, { id: frame.id, move: frame.move }));
  }

  /** This worker stopped sending `id` (the next full hello may send it again, while it is kept). */
  idle(id: RequestId): void {
    this.active.delete(id);
  }

  /** Forget `id`: it was answered, or refused for good. */
  async release(id: RequestId): Promise<void> {
    this.active.delete(id);
    await this.load();
    const current = this.pending ?? [];
    if (current.some((kept) => kept.id === id)) await this.store(withoutPendingMove(current, id));
  }

  private async load(): Promise<void> {
    if (this.pending !== undefined) return;
    this.loading ??= this.storage.loadPendingMoves().then(
      (moves) => moves ?? [],
      (error: unknown) => {
        this.loading = undefined;
        throw error;
      },
    );
    const stored = await this.loading;
    this.pending ??= stored;
  }

  private store(moves: readonly PendingMove[]): Promise<void> {
    this.pending = moves;
    return this.storage.savePendingMoves(moves);
  }
}

// --- Flow ---

/** Send the frame (kept first); re-send it after a backoff on busy or internal, forget it on an answer or a refusal for good. */
async function report(frame: MoveFrame, attempt: number, deps: ReportDeps): Promise<void> {
  try {
    await deps.moves.hold(frame);
    resultOrThrow(await deps.transport.send(frame));
  } catch (error) {
    if (error instanceof DaemonError && isRetryable(error.code)) retryLater(frame, attempt, deps);
    else if (error instanceof DaemonError) await deps.moves.release(frame.id);
    else deps.moves.idle(frame.id);
    throw error;
  }
  await deps.moves.release(frame.id);
}

function retryLater(frame: MoveFrame, attempt: number, deps: ReportDeps): void {
  deps.timer.after(backoffDelay(attempt), () => deps.track(report(frame, attempt + 1, deps)));
}

/** Re-send every kept report this worker is not already sending, unchanged (after a full hello). */
export async function resendMoves(deps: ReportDeps): Promise<void> {
  for (const kept of await deps.moves.adopt()) {
    deps.track(report({ v: CONTRACT_VERSION, type: 'move.observed', id: kept.id, move: kept.move }, 0, deps));
  }
}

/** Report an owned move to the daemon and return the feedback it is, if any; a move outside the owned roots is ignored. */
export async function observeMove(
  observed: ObservedMove,
  role: HostRole,
  context: MoveContext,
  deps: ObserveDeps,
): Promise<MoveFeedback | undefined> {
  if (!isOwnedMove(observed.from, observed.to, context.owned_roots)) return undefined;
  const move: Move = {
    ...observed,
    from: fitPath(observed.from),
    to: fitPath(observed.to),
    origin: moveOrigin(observed.node_id, context.in_flight),
    observed_at: deps.clock.now(),
  };
  await report({ v: CONTRACT_VERSION, type: 'move.observed', id: deps.ids.next(), move }, 0, deps);
  return recordMove(move, role);
}
