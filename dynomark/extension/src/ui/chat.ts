// chat.ts -- the chat surface (design, "The extension": Chat surface -- a
// view, not a composition root: it sends Questions to the background and
// renders Answers, Citations, "file this" and "why here"; conversation state
// lives in the page. Security: the completion model, local or cloud, is
// shown). A citation opens in one click and closes the chat; a URL the answer
// mentions that is not in the corpus is marked external and can be filed
// into Follow Up. Batches that ended PARTIAL or REJECTED and FAILED jobs are
// listed on top, each job with Retry (design, Transport contract: "they
// surface in chat and the diff view"; State Machine: FAILED -> QUEUED "user
// retries from chat or menu").

import { withTurn, type Answer, type Citation, type Question, type Turn } from '../domain/chat.js';
import type { PlacementReason } from '../domain/diff.js';
import type { Job } from '../domain/jobs.js';
import type { Url } from '../domain/values.js';
import type { PageClient, PageResponse } from '../ports/pages.js';
import { byId, el, when } from './dom.js';

// --- Types ---

export interface ChatOptions {
  /** Sent as soon as the page opens (the omnibox's Ask row). */
  readonly question: Question | undefined;
  /** Close the chat surface (after a citation opens). */
  readonly close: () => void;
}

type Batch = Extract<PageResponse, { kind: 'batch.list' }>['batches'][number];

// --- Pure helpers ---

function pathText(names: readonly string[]): string {
  return names.join(' / ');
}

/** A batch the user should see: it stopped midway or was refused, and is not retried by itself. */
function needsAttention(batch: Batch): boolean {
  return batch.state === 'PARTIAL' || batch.state === 'REJECTED';
}

// --- Rendering ---

function say(doc: Document, text: string): void {
  byId(doc, 'message').textContent = text;
}

function reasonBlock(doc: Document, reason: PlacementReason): HTMLElement {
  const block = el(doc, 'div', '', { class: 'reason' });
  block.append(
    el(doc, 'p', `Filed in ${pathText(reason.folder.names)}: ${reason.rationale}`),
    el(doc, 'p', `Neighbours: ${reason.neighbours.map((n) => n.title).join('; ') || 'none'}`, { class: 'muted' }),
    el(doc, 'p', `Model ${reason.model_id}; feedback used: ${reason.feedback_ids.length}`, { class: 'muted' }),
  );
  return block;
}

function citationItem(doc: Document, client: PageClient, options: ChatOptions, citation: Citation): HTMLElement {
  const li = el(doc, 'li');
  const open = el(doc, 'button', citation.title || citation.identity, { type: 'button', class: 'link', 'data-open': citation.identity });
  open.addEventListener('click', () => void openUrl(doc, client, options, citation.identity));
  const why = el(doc, 'button', 'why here', { type: 'button', 'data-explain': citation.identity });
  why.addEventListener('click', () => void explain(doc, client, li, citation.identity));
  li.append(open, el(doc, 'span', ` ${pathText(citation.path.names)} `, { class: 'muted' }), why);
  return li;
}

function externalItem(doc: Document, client: PageClient, options: ChatOptions, url: Url): HTMLElement {
  const li = el(doc, 'li', '', { class: 'external' });
  const open = el(doc, 'button', url, { type: 'button', class: 'link', 'data-open': url });
  open.addEventListener('click', () => void openUrl(doc, client, options, url));
  const file = el(doc, 'button', 'file this', { type: 'button', 'data-file': url });
  file.addEventListener('click', () => void fileUrl(doc, client, url));
  li.append(el(doc, 'span', 'external', { class: 'tag' }), open, file);
  return li;
}

function answerBlock(doc: Document, client: PageClient, options: ChatOptions, answer: Answer): HTMLElement {
  const block = el(doc, 'div', '', { class: 'answer' });
  block.append(el(doc, 'p', answer.text, { class: 'answer-text' }));
  if (answer.citations.length > 0) {
    const list = el(doc, 'ul', '', { class: 'citations' });
    list.append(...answer.citations.map((c) => citationItem(doc, client, options, c)));
    block.append(list);
  }
  if (answer.external_urls.length > 0) {
    const list = el(doc, 'ul', '', { class: 'externals' });
    list.append(...answer.external_urls.map((u) => externalItem(doc, client, options, u)));
    block.append(list);
  }
  return block;
}

function attentionBatch(doc: Document, batch: Batch): HTMLElement {
  const what = batch.identity ?? batch.diff_item_id ?? '';
  return el(doc, 'li', `${when(batch.created_at)} ${batch.batch_id} ${batch.state} ${what}`, { 'data-batch': batch.batch_id });
}

function attentionJob(doc: Document, client: PageClient, job: Job): HTMLElement {
  const li = el(doc, 'li', `${job.identity}: ${job.last_error ?? 'failed'} `);
  const retry = el(doc, 'button', 'Retry', { type: 'button', 'data-job': job.job_id });
  retry.addEventListener('click', () => void retryJob(doc, client, job.job_id));
  li.append(retry);
  return li;
}

// --- Flow ---

/** Every FAILED job, page by page; a cursor gone stale (retries change the list) starts again from the first page, once. */
async function allFailedJobs(client: PageClient): Promise<Job[]> {
  const jobs: Job[] = [];
  let cursor: string | undefined;
  let restarted = false;
  for (;;) {
    const response = await client.request(cursor === undefined ? { kind: 'job.list' } : { kind: 'job.list', cursor });
    if (!response.ok && response.code === 'stale_cursor' && !restarted) {
      restarted = true;
      jobs.length = 0;
      cursor = undefined;
      continue;
    }
    if (!response.ok || response.kind !== 'job.list') return jobs;
    jobs.push(...response.jobs);
    if (response.next_cursor === null) return jobs;
    cursor = response.next_cursor;
  }
}

/** List what needs the user: the newest page's PARTIAL and REJECTED batches, and every FAILED job. */
async function showAttention(doc: Document, client: PageClient): Promise<void> {
  const [batches, failedJobs] = await Promise.all([client.request({ kind: 'batch.list' }), allFailedJobs(client)]);
  const failedBatches = batches.ok && batches.kind === 'batch.list' ? batches.batches.filter(needsAttention) : [];
  byId(doc, 'attention-batches').replaceChildren(...failedBatches.map((b) => attentionBatch(doc, b)));
  byId(doc, 'attention-jobs').replaceChildren(...failedJobs.map((j) => attentionJob(doc, client, j)));
  byId(doc, 'attention').hidden = failedBatches.length === 0 && failedJobs.length === 0;
}

async function retryJob(doc: Document, client: PageClient, job_id: string): Promise<void> {
  const response = await client.request({ kind: 'job.retry', job_id });
  say(doc, response.ok ? `retry ${job_id}: queued` : `retry ${job_id}: ${response.error}`);
  await showAttention(doc, client);
}

async function openUrl(doc: Document, client: PageClient, options: ChatOptions, url: Url): Promise<void> {
  const response = await client.request({ kind: 'open', url });
  if (response.ok) options.close();
  else say(doc, `open: ${response.error}`);
}

async function explain(doc: Document, client: PageClient, item: HTMLElement, identity: string): Promise<void> {
  const response = await client.request({ kind: 'explain', identity });
  item.querySelector('.reason')?.remove();
  if (response.ok && response.kind === 'explain') item.append(reasonBlock(doc, response.reason));
  else say(doc, `why here: ${response.ok ? '' : response.error}`);
}

async function fileUrl(doc: Document, client: PageClient, url: Url): Promise<void> {
  const response = await client.request({ kind: 'file', url, title: url });
  if (!response.ok) return say(doc, `file this: ${response.error}`);
  if (response.kind === 'file') say(doc, response.created ? `Added to Follow Up: ${url}` : `Already in Follow Up: ${url}`);
}

async function showModel(doc: Document, client: PageClient): Promise<void> {
  const response = await client.request({ kind: 'overview' });
  const model = response.ok && response.kind === 'overview' ? response.overview.daemon?.models.completion : undefined;
  byId(doc, 'model').textContent = model === undefined ? 'Model unknown' : `Answers by ${model.id} (${model.local ? 'local' : 'cloud'})`;
}

// --- The page ---

/** Fill the page, send the pre-sent question if any, and wire the form. Conversation state lives here. */
export async function mountChat(doc: Document, client: PageClient, options: ChatOptions): Promise<void> {
  let turns: readonly Turn[] = [];
  let asking = false;
  const log = byId(doc, 'log');
  const ask = async (question: Question): Promise<void> => {
    if (asking || question.trim() === '') return;
    asking = true;
    say(doc, 'asking...');
    log.append(el(doc, 'p', question.trim(), { class: 'question' }));
    try {
      const response = await client.request({ kind: 'ask', question, history: turns });
      if (!response.ok || response.kind !== 'ask') return say(doc, response.ok ? '' : `ask: ${response.error}`);
      log.append(answerBlock(doc, client, options, response.answer));
      turns = withTurn(turns, { question: question.trim(), answer: response.answer.text });
      say(doc, '');
    } finally {
      asking = false;
    }
  };
  const input = byId(doc, 'question') as HTMLTextAreaElement;
  byId(doc, 'ask-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const question = input.value;
    input.value = '';
    void ask(question);
  });
  const model = showModel(doc, client);
  const attention = showAttention(doc, client);
  if (options.question !== undefined) await ask(options.question);
  await Promise.all([model, attention]);
}
