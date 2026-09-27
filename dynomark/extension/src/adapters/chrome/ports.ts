// ports.ts -- every chrome adapter the background runtime needs, built on
// the live chrome.* APIs (the entry point's one call into this layer).

import { SystemClock } from '../clock.js';
import { CryptoIdSource } from '../idSource.js';
import { SystemTimer } from '../timer.js';
import { ChromeBookmarkTree } from './bookmarkTree.js';
import { ChromeChatSurface } from './chatSurface.js';
import { ChromeHistory } from './history.js';
import { NativeMessagingTransport } from './nativeTransport.js';
import { ChromeNavigator } from './navigator.js';
import { ChromeStorage } from './storage.js';
import { ChromeTabContent } from './tabContent.js';

/** The chrome adapters, one per port. */
export function chromePorts() {
  return {
    tree: new ChromeBookmarkTree(),
    history: new ChromeHistory(),
    content: new ChromeTabContent(),
    storage: new ChromeStorage(),
    transport: new NativeMessagingTransport(),
    clock: new SystemClock(),
    ids: new CryptoIdSource(),
    timer: new SystemTimer(),
    navigator: new ChromeNavigator(),
    surface: new ChromeChatSurface(),
  };
}
