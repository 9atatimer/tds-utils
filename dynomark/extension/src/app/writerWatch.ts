// writerWatch.ts -- what the extension knows of a writer conflict (design,
// Key Decisions "Two writers", MVP; task-030; contract v1, "Writer marker
// (MVP)"). The daemon reads markers from the tree and reports them in
// writer.status; a writer_conflict refusal is a report too. While a conflict
// is reported the extension applies no batch -- but it asks again first,
// because the report may be stale: clearing a stale marker is a user edit in
// the tree, after which the daemon, given a fresh snapshot, stops reporting it.

import type { WriterStatus } from '../domain/writer.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';

// --- Types ---

interface Talk {
  readonly transport: TransportPort;
  readonly ids: IdSource;
}

// --- The watch ---

export class WriterWatch {
  private last: WriterStatus | undefined;
  /** A request was refused writer_conflict since the last status. */
  private refused = false;
  private confirming: Promise<void> | undefined;

  /** The last status the daemon reported; undefined before the first. */
  status(): WriterStatus | undefined {
    return this.last;
  }

  /** True while a conflict is reported. */
  conflict(): boolean {
    return this.refused || this.last?.conflict === true;
  }

  /** Ask writer.status and keep the answer. */
  async refresh(deps: Talk): Promise<WriterStatus> {
    const r = resultOrThrow(await deps.transport.send({ v: CONTRACT_VERSION, type: 'writer.status', id: deps.ids.next() }));
    this.last = { role: r.role, host_id: r.host_id, own_marker: r.own_marker, other_writers: r.other_writers, conflict: r.conflict };
    this.refused = false;
    return this.last;
  }

  /** A request was answered writer_conflict. */
  noteRefusal(): void {
    this.refused = true;
  }

  /** While a conflict is reported, ask again (one question at a time); a failed ask keeps the report. Never rejects. */
  confirm(deps: Talk): Promise<void> {
    if (!this.conflict()) return Promise.resolve();
    this.confirming ??= this.refresh(deps).then(
      () => undefined,
      () => undefined,
    );
    const confirming = this.confirming;
    void confirming.finally(() => {
      if (this.confirming === confirming) this.confirming = undefined;
    });
    return confirming;
  }
}
