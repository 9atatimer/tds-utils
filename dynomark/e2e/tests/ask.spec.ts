// ask.spec.ts -- grounded chat (design Goal 5) against the real daemon: the
// chat page asks, the daemon retrieves from its corpus and the (scripted)
// completion answers citing the filed bookmark's identity and one URL
// outside the corpus; the answer shows the citation, which opens the page,
// and marks the other URL external.

import { EXTERNAL_URL, PAGES, READING, TOKIO, filing } from '../support/scenario.js';
import { expect, test } from '../support/world.js';

test('Given a filed page, When the chat page asks about it, Then the answer cites the filed bookmark and marks an out-of-corpus URL external (Goal 5)', async ({
  world,
}) => {
  const pages = await world.serve(PAGES);
  const url = pages.url(TOKIO.path);
  const script = {
    ...filing(1),
    answer: [{ text: 'The Tokio tutorial explains cancellation at await points.', cited: [url], urls: [EXTERNAL_URL] }],
  };
  await world.start({ role: 'writer', hostId: 'mbp', script });
  await world.saveAndFile(url, TOKIO.title, READING);

  const chat = await world.browser.extensionPage(`chat.html?q=${encodeURIComponent('how does tokio cancel a task')}`);
  await expect(chat.locator('.answer-text').first()).toHaveText('The Tokio tutorial explains cancellation at await points.');
  await expect(chat.locator(`.citations button[data-open="${url}"]`)).toHaveText(TOKIO.title);
  await expect(chat.locator('li.external')).toContainText(EXTERNAL_URL);
  await expect(chat.locator('#model')).toContainText('(local)');

  await chat.locator(`button[data-explain="${url}"]`).click();
  await expect(chat.locator('.reason').first()).toContainText('Reading');
});
