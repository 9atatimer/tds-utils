// firefoxBackground.ts -- the Firefox extension's composition root: the MV3
// background script (dist-firefox manifest "background.scripts"; task-032).
// It is the one place that names the Firefox adapters, all built on the
// `browser` namespace; boot.ts registers their listeners and starts the
// runtime. The chat shortcut is Firefox's own `_execute_sidebar_action`, so
// the open-chat command never fires here; it is registered for parity.

import { OPEN_CHAT_COMMAND, listenCommands } from './adapters/chrome/commands.js';
import { servePages } from './adapters/chrome/pageChannel.js';
import { listenFirefoxBookmarkEvents } from './adapters/firefox/bookmarkEvents.js';
import { firefoxBrowser } from './adapters/firefox/namespace.js';
import { listenFirefoxOmnibox } from './adapters/firefox/omnibox.js';
import { firefoxPorts } from './adapters/firefox/ports.js';
import { boot } from './boot.js';

const api = firefoxBrowser();

boot({
  ports: firefoxPorts(api),
  listenBookmarkEvents: (listener) => listenFirefoxBookmarkEvents(listener, api.bookmarks),
  listenOmnibox: (handlers) => listenFirefoxOmnibox(handlers, api.omnibox),
  servePages: (answer) => servePages(answer, api.runtime),
  listenCommands: (openChat) => listenCommands({ [OPEN_CHAT_COMMAND]: openChat }, api.commands),
});
