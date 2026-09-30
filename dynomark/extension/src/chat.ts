// chat.ts -- entry point of chat.html (the chat surface): wires the page view
// to the background over the runtime message channel. The question the
// omnibox's Ask row carried arrives in the query string (`?q=`).

import { ChromePageClient } from './adapters/chrome/pageChannel.js';
import { mountChat } from './ui/chat.js';

const question = new URLSearchParams(location.search).get('q') ?? undefined;
void mountChat(document, new ChromePageClient(), { question, close: () => window.close() });
