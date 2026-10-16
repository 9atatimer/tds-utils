// boot.ts -- the body both background entry points share (background.ts for
// Chrome's service worker, firefoxBackground.ts for Firefox's background
// script): build the runtime over one browser's ports, register that
// browser's listeners, start. The entry points are the composition roots;
// they name the concrete adapters and hand them in here.
//
// Every browser listener is registered synchronously here, before the first
// await, because MV3 delivers the event that woke the background only to
// listeners added during its first run; the runtime queues what arrives
// before start() is done. The background can be terminated between any two
// events; nothing below keeps state that is not rebuilt on the next start.
//
// `globalThis.dynomark` is a diagnostic handle on the runtime: only this
// extension's own contexts can reach the background's global scope, and the
// e2e suite drives the omnibox through it (a headless browser has no address
// bar to type into).

import { z } from 'zod';
import { ExtensionRuntime, type RuntimePorts } from './app/runtime.js';
import type { OmniboxHandlers } from './adapters/chrome/omnibox.js';
import type { BookmarkEvent } from './ports/bookmarkEvents.js';
import type { PageRequest, PageResponse } from './ports/pages.js';

// An extension's CSP forbids eval; tell zod not to probe for it.
z.config({ jitless: true });

// --- Types ---

/** One browser's ports and the listeners it registers, as its entry point wires them. */
export interface BrowserBackground {
  readonly ports: RuntimePorts;
  listenBookmarkEvents(listener: (event: BookmarkEvent) => void): void;
  listenOmnibox(handlers: OmniboxHandlers): void;
  servePages(answer: (request: PageRequest) => Promise<PageResponse>): void;
  /** Run `openChat` when the browser fires the open-chat command. */
  listenCommands(openChat: () => void): void;
}

// --- Entry ---

/** Build the runtime over `background`'s ports, register its listeners, and start it. */
export function boot(background: BrowserBackground): ExtensionRuntime {
  const runtime = new ExtensionRuntime(background.ports);

  background.listenBookmarkEvents((event) => runtime.onBookmarkEvent(event));
  background.listenOmnibox({
    input: (text, suggest) => runtime.omniboxInput(text, suggest),
    enter: (text, disposition) => void runtime.omniboxEnter(text, disposition),
  });
  background.servePages((request) => runtime.page(request));
  background.listenCommands(() => void runtime.openChat());

  (globalThis as { dynomark?: ExtensionRuntime }).dynomark = runtime;

  runtime.start().catch((error: unknown) => {
    console.error('dynomark: start failed', error);
  });
  return runtime;
}
