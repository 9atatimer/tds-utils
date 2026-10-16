// background.ts -- the Chrome extension's composition root: the MV3 service
// worker entry (manifest "background.service_worker"). It is the one place
// that names the chrome adapters; boot.ts registers their listeners and
// starts the runtime, whose workflow it is.

import { listenBookmarkEvents } from './adapters/chrome/bookmarkEvents.js';
import { OPEN_CHAT_COMMAND, listenCommands } from './adapters/chrome/commands.js';
import { listenOmnibox } from './adapters/chrome/omnibox.js';
import { servePages } from './adapters/chrome/pageChannel.js';
import { chromePorts } from './adapters/chrome/ports.js';
import { boot } from './boot.js';

boot({
  ports: chromePorts(),
  listenBookmarkEvents: (listener) => listenBookmarkEvents(listener),
  listenOmnibox: (handlers) => listenOmnibox(handlers),
  servePages: (answer) => servePages(answer),
  listenCommands: (openChat) => listenCommands({ [OPEN_CHAT_COMMAND]: openChat }),
});
