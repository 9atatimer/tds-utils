// background.ts -- the extension's composition root: the MV3 service worker
// entry (manifest "background.service_worker"). It is the one place that
// names concrete adapters; the workflow is ExtensionRuntime's.
//
// Every browser listener is registered synchronously here, before the first
// await, because MV3 delivers the event that woke the worker only to
// listeners added during its first run; the runtime queues what arrives
// before start() is done. The worker can be terminated between any two
// events; nothing below keeps state that is not rebuilt on the next start.
//
// `globalThis.dynomark` is a diagnostic handle on the runtime: only this
// extension's own contexts can reach a service worker's global scope, and the
// e2e suite drives the omnibox through it (a headless browser has no address
// bar to type into).

import { z } from 'zod';
import { listenBookmarkEvents } from './adapters/chrome/bookmarkEvents.js';
import { listenOmnibox } from './adapters/chrome/omnibox.js';
import { servePages } from './adapters/chrome/pageChannel.js';
import { chromePorts } from './adapters/chrome/ports.js';
import { ExtensionRuntime } from './app/runtime.js';

// An extension's CSP forbids eval; tell zod not to probe for it.
z.config({ jitless: true });

const runtime = new ExtensionRuntime(chromePorts());

listenBookmarkEvents((event) => runtime.onBookmarkEvent(event));
listenOmnibox({
  input: (text, suggest) => runtime.omniboxInput(text, suggest),
  enter: (text, disposition) => void runtime.omniboxEnter(text, disposition),
});
servePages((request) => runtime.page(request));

(globalThis as { dynomark?: ExtensionRuntime }).dynomark = runtime;

runtime.start().catch((error: unknown) => {
  console.error('dynomark: start failed', error);
});
