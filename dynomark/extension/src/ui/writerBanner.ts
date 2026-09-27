// writerBanner.ts -- the writer-conflict banner the settings page and the
// diff view show (task-030: surfaced prominently). Changing writers is
// explicit: clear the marker on the old host, then flip the flag on the new
// one; clearing a stale marker is a user edit in the tree.

import type { WriterStatus } from '../domain/writer.js';
import { byId } from './dom.js';

// --- Pure helpers ---

/** What the banner says for a conflict. */
export function conflictText(writer: WriterStatus): string {
  const others = writer.other_writers.join(', ');
  return (
    `Writer conflict: ${others} also left a writer marker in Dynomark, so this host (${writer.host_id}) files nothing and applies no batch. ` +
    `If ${others} should stop writing, set its role to reader and delete its folder dynomark-writer:${writer.other_writers[0] ?? ''} ` +
    `from Dynomark; if it should write instead, make this host a reader. Then press Refresh.`
  );
}

// --- Rendering ---

/** Show the banner while a conflict is reported; hide it otherwise. */
export function renderWriterBanner(doc: Document, writer: WriterStatus | undefined): void {
  const banner = byId(doc, 'writer-conflict');
  banner.hidden = writer?.conflict !== true;
  banner.textContent = writer?.conflict === true ? conflictText(writer) : '';
}
