// diff.ts -- entry point of diff.html (the diff view): wires the page view to
// the background over the runtime message channel.

import { ChromePageClient } from './adapters/chrome/pageChannel.js';
import { mountDiff } from './ui/diff.js';

void mountDiff(document, new ChromePageClient());
