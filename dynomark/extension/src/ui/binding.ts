// binding.ts -- the writer binding on the settings page (design, Key
// Decisions "Writer binding" 2026-10-16, issue #419). A writer daemon files
// for the first browser profile that completed a full hello and serves every
// other profile as a reader; an extension reinstall mints a new profile, so
// without this a reinstalled browser would stop filing with no sign of why.

import type { HostRole } from '../domain/roles.js';

// --- Types ---

/** Whom a writer daemon files for, as this browser's profile sees it (status.result writer_binding). */
export type WriterBinding = 'this_profile' | 'other_profile' | 'unbound';

// --- Pure helpers ---

/** The Daemon section's row for the binding. */
export function bindingText(binding: WriterBinding | undefined): string {
  switch (binding) {
    case 'this_profile':
      return 'the writer files for this browser';
    case 'other_profile':
      return 'the writer files for another browser profile; this one is served as a reader';
    case 'unbound':
      return 'released: the next browser profile to connect becomes the one the writer files for';
    case undefined:
      return '-';
  }
}

/** The banner shown while this browser is served as a reader because the writer is bound to another profile; undefined otherwise. */
export function readerBindingText(
  daemon: { readonly role: HostRole; readonly writer_binding?: WriterBinding } | undefined,
): string | undefined {
  if (daemon?.role !== 'reader' || daemon.writer_binding !== 'other_profile') return undefined;
  return (
    'This browser is served as a reader: the writer daemon files for another browser profile (the first that connected to it), ' +
    'so saves made here are indexed and searchable but never filed. If this profile should file (for example after the extension ' +
    'was reinstalled), run `dynomark-daemon rebind` on the daemon host, then reload the extension here.'
  );
}

// --- Rendering ---

/** Show the binding row, and the banner while this browser is served as a reader of a writer bound elsewhere. */
export function renderBinding(
  doc: Document,
  daemon: { readonly role: HostRole; readonly writer_binding?: WriterBinding } | undefined,
): void {
  const row = doc.getElementById('daemon-binding');
  if (row !== null) row.textContent = bindingText(daemon?.writer_binding);
  const banner = doc.getElementById('reader-binding');
  if (banner === null) return;
  const text = readerBindingText(daemon);
  banner.hidden = text === undefined;
  banner.textContent = text ?? '';
}
