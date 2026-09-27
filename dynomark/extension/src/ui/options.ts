// options.ts -- the settings page (design, "Settings": transport selection
// and Follow Up behaviour; Security: the model choice is shown; task-030: the
// writer marker status, a conflict shown prominently; Open Question 3: the
// backfill). A view over the background: it shows the transport, daemon and
// writer status, edits the two capture settings and starts the backfill; it
// holds no state of its own.

import type { SettingsChange } from '../domain/settings.js';
import type { WriterStatus } from '../domain/writer.js';
import type { BackfillView, Overview, PageClient } from '../ports/pages.js';
import { byId, el } from './dom.js';
import { renderWriterBanner } from './writerBanner.js';

// --- Pure helpers ---

function linkText(overview: Overview): string {
  const { link } = overview;
  if (link.state === 'disconnected') return `disconnected: ${link.detail}`;
  return link.state;
}

function connectionText(overview: Overview): string {
  const c = overview.connection;
  return c === undefined ? 'no hello yet' : `contract v${c.v}, mode ${c.mode}, role ${c.role}, host ${c.host_id}`;
}

function modelText(model: { readonly id: string; readonly local: boolean }): string {
  return `${model.id} (${model.local ? 'local' : 'cloud'})`;
}

function writerText(writer: WriterStatus | undefined, error: string | undefined): string {
  if (writer === undefined) return error === undefined ? '-' : `unknown: ${error}`;
  const others = writer.other_writers.length === 0 ? 'none' : writer.other_writers.join(', ');
  return `role ${writer.role}, own marker ${writer.own_marker ? 'present' : 'absent'}, other writers: ${others}`;
}

function backfillText(backfill: BackfillView | undefined): string {
  if (backfill === undefined) return 'never run';
  return `${backfill.done} of ${backfill.total} done${backfill.running ? ', running' : ''}`;
}

// --- Rendering ---

function render(doc: Document, overview: Overview): void {
  byId(doc, 'link').textContent = linkText(overview);
  byId(doc, 'connection').textContent = connectionText(overview);
  const d = overview.daemon;
  byId(doc, 'daemon-role').textContent = d?.role ?? '-';
  byId(doc, 'daemon-host').textContent = d?.host_id ?? '-';
  byId(doc, 'daemon-embedding').textContent = d === undefined ? '-' : modelText(d.models.embedding);
  byId(doc, 'daemon-completion').textContent = d === undefined ? '-' : modelText(d.models.completion);
  byId(doc, 'daemon-queue').textContent = d === undefined ? '-' : String(d.queue_depth);
  byId(doc, 'daemon-error').textContent = overview.daemon_error ?? '';
  byId(doc, 'follow-up').textContent =
    overview.follow_up === undefined ? '-' : [overview.follow_up.root, ...overview.follow_up.names].join(' / ');
  byId(doc, 'profile').textContent = overview.settings.profile_id;
  (byId(doc, 'capture') as HTMLInputElement).checked = overview.settings.capture_from_tab;
  (byId(doc, 'capture-background') as HTMLInputElement).checked = overview.settings.capture_in_background;
  renderWriterBanner(doc, overview.writer);
  byId(doc, 'writer').textContent = writerText(overview.writer, overview.writer_error);
  byId(doc, 'backfill-progress').textContent = backfillText(overview.backfill);
  const problems = byId(doc, 'problems');
  problems.replaceChildren(...overview.problems.map((p) => el(doc, 'li', p)));
}

// --- Flow ---

async function refresh(doc: Document, client: PageClient): Promise<void> {
  const response = await client.request({ kind: 'overview' });
  if (response.ok && response.kind === 'overview') render(doc, response.overview);
  else byId(doc, 'message').textContent = response.ok ? '' : response.error;
}

async function change(doc: Document, client: PageClient, settings: SettingsChange): Promise<void> {
  const response = await client.request({ kind: 'settings.set', ...settings });
  byId(doc, 'message').textContent = response.ok ? 'saved' : response.error;
}

async function backfill(doc: Document, client: PageClient): Promise<void> {
  const response = await client.request({ kind: 'backfill.start' });
  if (!response.ok || response.kind !== 'backfill.start') {
    byId(doc, 'message').textContent = response.ok ? '' : `backfill: ${response.error}`;
    return;
  }
  byId(doc, 'backfill-progress').textContent = backfillText(response.backfill);
  byId(doc, 'message').textContent = 'backfill started';
}

// --- Entry ---

/** Fill the page and wire its controls. */
export function mountOptions(doc: Document, client: PageClient): Promise<void> {
  byId(doc, 'refresh').addEventListener('click', () => void refresh(doc, client));
  const capture = byId(doc, 'capture') as HTMLInputElement;
  capture.addEventListener('change', () => void change(doc, client, { capture_from_tab: capture.checked }));
  const background = byId(doc, 'capture-background') as HTMLInputElement;
  background.addEventListener('change', () => void change(doc, client, { capture_in_background: background.checked }));
  byId(doc, 'backfill').addEventListener('click', () => void backfill(doc, client));
  return refresh(doc, client);
}
