// options.ts -- the settings page (design, "Settings": transport selection
// and Follow Up behaviour; Security: the model choice is shown). A view over
// the background: it shows the transport and daemon status and edits the
// capture setting; it holds no state of its own.

import type { Overview, PageClient } from '../ports/pages.js';
import { byId, el } from './dom.js';

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
  const problems = byId(doc, 'problems');
  problems.replaceChildren(...overview.problems.map((p) => el(doc, 'li', p)));
}

// --- Flow ---

async function refresh(doc: Document, client: PageClient): Promise<void> {
  const response = await client.request({ kind: 'overview' });
  if (response.ok && response.kind === 'overview') render(doc, response.overview);
  else byId(doc, 'message').textContent = response.ok ? '' : response.error;
}

async function setCapture(doc: Document, client: PageClient, value: boolean): Promise<void> {
  const response = await client.request({ kind: 'settings.set', capture_from_tab: value });
  byId(doc, 'message').textContent = response.ok ? 'saved' : response.error;
}

// --- Entry ---

/** Fill the page and wire its controls. */
export function mountOptions(doc: Document, client: PageClient): Promise<void> {
  byId(doc, 'refresh').addEventListener('click', () => void refresh(doc, client));
  const capture = byId(doc, 'capture') as HTMLInputElement;
  capture.addEventListener('change', () => void setCapture(doc, client, capture.checked));
  return refresh(doc, client);
}
