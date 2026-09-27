// history.ts -- entry point of history.html (also the action popup): wires
// the page view to the background over the runtime message channel.

import { ChromePageClient } from './adapters/chrome/pageChannel.js';
import { mountHistory } from './ui/history.js';

void mountHistory(document, new ChromePageClient());
