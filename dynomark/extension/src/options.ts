// options.ts -- entry point of options.html: wires the page view to the
// background over the runtime message channel.

import { ChromePageClient } from './adapters/chrome/pageChannel.js';
import { mountOptions } from './ui/options.js';

void mountOptions(document, new ChromePageClient());
