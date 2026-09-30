// diff.ts -- the diff view (design, "Diffs": propose_diff of kind audit or
// rebuild; nothing is applied until an item is accepted, each acceptance its
// own batch; Transport contract: REJECTED and PARTIAL surface in the diff
// view; glossary: pinned, locked). Accepting is one item at a time: every
// Accept button is disabled while one is in flight. A view over the
// background, holding no state beyond what it shows.

import type { DiffItem, OutlineFolder, TreeDiff } from '../domain/diff.js';
import type { Cursor, Id } from '../domain/values.js';
import type { PageClient, PageResponse } from '../ports/pages.js';
import { byId, el, row, when } from './dom.js';
import { renderWriterBanner } from './writerBanner.js';

// --- Pure helpers ---

function batchText(item: DiffItem): string {
  if (item.accepted_at === null) return 'proposed';
  return `${item.batch_state ?? 'accepted'} ${item.batch_id ?? ''}`.trim();
}

function failure(response: PageResponse): string {
  return response.ok ? '' : `${response.error}${response.code === undefined ? '' : ` (${response.code})`}`;
}

// --- The view ---

class DiffView {
  private accepting = false;
  private openDiff: Id | undefined;

  constructor(
    private readonly doc: Document,
    private readonly client: PageClient,
  ) {}

  say(text: string): void {
    byId(this.doc, 'message').textContent = text;
  }

  async refresh(): Promise<void> {
    await Promise.all([this.loadWriter(), this.loadDiffs(), this.loadOutline()]);
    if (this.openDiff !== undefined) await this.loadItems(this.openDiff);
  }

  async propose(kind: 'audit' | 'rebuild'): Promise<void> {
    this.say(`proposing ${kind}...`);
    const response = await this.client.request({ kind: 'diff.propose', diff_kind: kind });
    if (!response.ok || response.kind !== 'diff.propose') return this.say(`propose ${kind}: ${failure(response)}`);
    this.say(`proposed ${response.diff.item_count} item(s)`);
    await this.loadDiffs();
    await this.loadItems(response.diff.diff_id);
  }

  private async loadWriter(): Promise<void> {
    const response = await this.client.request({ kind: 'overview' });
    if (response.ok && response.kind === 'overview') renderWriterBanner(this.doc, response.overview.writer);
  }

  private async loadDiffs(cursor?: Cursor): Promise<void> {
    const response = await this.client.request(cursor === undefined ? { kind: 'diff.list' } : { kind: 'diff.list', cursor });
    if (!response.ok && response.code === 'stale_cursor') return this.loadDiffs();
    if (!response.ok || response.kind !== 'diff.list') return this.say(`diffs: ${failure(response)}`);
    const rows = response.diffs.map((d) => this.diffRow(d));
    const body = byId(this.doc, 'diffs');
    if (cursor === undefined) body.replaceChildren(...rows);
    else body.append(...rows);
    this.more('diffs-more', response.next_cursor, (next) => this.loadDiffs(next));
  }

  private diffRow(diff: TreeDiff): HTMLElement {
    const open = el(this.doc, 'button', 'Open', { type: 'button', 'data-diff': diff.diff_id });
    open.addEventListener('click', () => void this.loadItems(diff.diff_id));
    return row(this.doc, [when(diff.proposed_at), diff.kind, String(diff.item_count), String(diff.unaccepted_count), open]);
  }

  private async loadItems(diff_id: Id, cursor?: Cursor): Promise<void> {
    this.openDiff = diff_id;
    const response = await this.client.request({ kind: 'diff.page', diff_id, ...(cursor === undefined ? {} : { cursor }) });
    if (!response.ok && response.code === 'stale_cursor') return this.loadItems(diff_id);
    if (!response.ok || response.kind !== 'diff.page') return this.say(`items: ${failure(response)}`);
    byId(this.doc, 'items-title').textContent = `Items of the ${response.diff.kind} proposed ${when(response.diff.proposed_at)}`;
    const rows = response.items.map((item) => this.itemRow(item));
    const body = byId(this.doc, 'items');
    if (cursor === undefined) body.replaceChildren(...rows);
    else body.append(...rows);
    this.more('items-more', response.next_cursor, (next) => this.loadItems(diff_id, next));
  }

  private itemRow(item: DiffItem): HTMLElement {
    const accept = el(this.doc, 'button', 'Accept', { type: 'button', 'data-accept': item.item_id, class: 'accept' });
    if (item.accepted_at !== null) accept.setAttribute('disabled', '');
    accept.addEventListener('click', () => void this.accept(item));
    const state = el(this.doc, 'span', batchText(item), { class: 'batch-state' });
    return row(this.doc, [item.action, item.description, String(item.operations.length), state, accept]);
  }

  private async accept(item: DiffItem): Promise<void> {
    if (this.accepting) return;
    this.accepting = true;
    const buttons = [...this.doc.querySelectorAll<HTMLButtonElement>('button.accept')];
    buttons.forEach((b) => (b.disabled = true));
    try {
      const response = await this.client.request({ kind: 'diff.accept', item_id: item.item_id });
      if (!response.ok || response.kind !== 'diff.accept') {
        this.say(`accept: ${failure(response)}`);
        if (!response.ok && response.code === 'writer_conflict') await this.loadWriter();
        return;
      }
      this.say(`accepted; batch ${response.batch_id} is being applied`);
    } finally {
      this.accepting = false;
      await this.loadItems(item.diff_id);
    }
  }

  private async loadOutline(cursor?: Cursor): Promise<void> {
    const response = await this.client.request(cursor === undefined ? { kind: 'outline' } : { kind: 'outline', cursor });
    if (!response.ok && response.code === 'stale_cursor') return this.loadOutline();
    if (!response.ok || response.kind !== 'outline') return this.say(`folders: ${failure(response)}`);
    const rows = response.folders.map((f) => this.folderRow(f));
    const body = byId(this.doc, 'outline');
    if (cursor === undefined) body.replaceChildren(...rows);
    else body.append(...rows);
    this.more('outline-more', response.next_cursor, (next) => this.loadOutline(next));
  }

  private folderRow(folder: OutlineFolder): HTMLElement {
    const flag = (name: 'pinned' | 'locked', attr: string): HTMLElement => {
      const box = el(this.doc, 'input', '', { type: 'checkbox', [attr]: folder.node_id }) as HTMLInputElement;
      box.checked = folder[name];
      box.addEventListener('change', () => void this.setFlag(folder, name, box));
      return box;
    };
    return row(this.doc, [
      folder.path.names.join(' / '),
      String(folder.item_count),
      flag('pinned', 'data-pin'),
      flag('locked', 'data-lock'),
    ]);
  }

  private async setFlag(folder: OutlineFolder, name: 'pinned' | 'locked', box: HTMLInputElement): Promise<void> {
    const response = await this.client.request({ kind: 'folder.flags', node_id: folder.node_id, path: folder.path, [name]: box.checked });
    if (response.ok) return this.say(`${folder.path.names.join(' / ')}: ${name} ${box.checked ? 'on' : 'off'}`);
    box.checked = !box.checked;
    this.say(`${name}: ${failure(response)}`);
  }

  private more(id: string, next: Cursor | null, load: (cursor: Cursor) => Promise<void>): void {
    const button = byId(this.doc, id);
    button.hidden = next === null;
    button.onclick = next === null ? null : () => void load(next);
  }
}

// --- Entry ---

/** Fill the page and wire its controls. */
export async function mountDiff(doc: Document, client: PageClient): Promise<void> {
  const view = new DiffView(doc, client);
  byId(doc, 'refresh').addEventListener('click', () => void view.refresh());
  byId(doc, 'propose-audit').addEventListener('click', () => void view.propose('audit'));
  byId(doc, 'propose-rebuild').addEventListener('click', () => void view.propose('rebuild'));
  await view.refresh();
}
