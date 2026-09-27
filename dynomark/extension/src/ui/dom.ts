// dom.ts -- the few DOM helpers the extension pages share. Text goes in as
// textContent, never as markup: titles, urls and errors come from the daemon
// and the browser.

// --- Pure helpers (over a Document) ---

/** An element with text content and attributes. */
export function el(doc: Document, tag: string, text = '', attrs: Readonly<Record<string, string>> = {}): HTMLElement {
  const node = doc.createElement(tag);
  node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

/** A table row of text cells, plus any extra cells given as elements. */
export function row(doc: Document, cells: readonly (string | HTMLElement)[]): HTMLElement {
  const tr = doc.createElement('tr');
  for (const cell of cells) {
    const td = doc.createElement('td');
    if (typeof cell === 'string') td.textContent = cell;
    else td.append(cell);
    tr.append(td);
  }
  return tr;
}

/** The element with this id; a page whose markup lacks it is a build error, reported loudly. */
export function byId(doc: Document, id: string): HTMLElement {
  const node = doc.getElementById(id);
  if (node === null) throw new Error(`page markup has no #${id}`);
  return node;
}

/** A timestamp as local date and time. */
export function when(ms: number): string {
  return new Date(ms).toLocaleString();
}
