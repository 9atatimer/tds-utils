// omnibox.ts -- the address-bar keyword `bm` (design, "The extension": Tier-1
// search, Tier-2 search; Goal 4). Each keystroke is answered at once from the
// LocalIndex (search_local, no transport call). When tier 1 is under the
// named thresholds, search_remote runs after a debounce and its hits are
// appended below tier 1 -- unless a newer keystroke arrived meanwhile. The
// Ask row always comes last (design, "Ask fall-through"). What Enter does is
// decided here (the domain's enterAction); opening a page or the chat surface
// is the runtime's.

import { enterAction, omniboxRows, type EnterAction, type OmniboxRows } from '../domain/omnibox.js';
import { appendTier2, shouldRequestTier2, type Frecency, type Hit, type LocalIndex, type Query } from '../domain/search.js';
import type { OwnedRoots } from '../domain/tree.js';
import type { IdSource } from '../ports/idSource.js';
import type { Timer } from '../ports/timer.js';
import type { TransportPort } from '../ports/transport.js';
import { searchLocal } from './searchLocal.js';
import { searchRemote } from './searchRemote.js';

// --- Constants ---

/** Quiet time after the last keystroke before tier 2 is asked. */
export const TIER2_DEBOUNCE_MS = 250;
/** Hits shown at most: with the Ask row, eight rows (the address bar shows a handful). */
export const OMNIBOX_HIT_LIMIT = 7;

// --- Types ---

export interface OmniboxDeps {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly timer: Timer;
  index(): LocalIndex;
  frecency(): Frecency;
  roots(): OwnedRoots | undefined;
  /** Hand background work to the runtime (it is awaited by idle() and its failures reported). */
  track(work: Promise<unknown>): void;
}

export type Suggest = (rows: OmniboxRows) => void;

// --- The session ---

export class OmniboxSession {
  private current: Query = '';
  private shown: readonly Hit[] = [];
  private cancelTier2: (() => void) | undefined;

  constructor(private readonly deps: OmniboxDeps) {}

  /** Answer one keystroke: tier 1 now, tier 2 appended after the debounce when tier 1 is not enough; the Ask row last. */
  input(text: Query, suggest: Suggest): void {
    this.current = text;
    this.cancelTier2?.();
    this.cancelTier2 = undefined;
    const tier1 = this.local(text);
    this.shown = tier1;
    suggest(omniboxRows(text, tier1));
    if (text.trim() === '' || !shouldRequestTier2(tier1)) return;
    this.cancelTier2 = this.deps.timer.after(TIER2_DEBOUNCE_MS, () => this.deps.track(this.tier2(text, tier1, suggest)));
  }

  /** What Enter on `text` does: the picked row, else the best hit (tier 1, or what is shown for this text), else ask. */
  enter(text: string): EnterAction {
    const best = this.local(text)[0] ?? (text === this.current ? this.shown[0] : undefined);
    return enterAction(text, this.shown, best);
  }

  private local(text: Query): Hit[] {
    const roots = this.deps.roots();
    return searchLocal(text, this.deps.index(), this.deps.frecency(), {
      limit: OMNIBOX_HIT_LIMIT,
      ...(roots === undefined ? {} : { owned_roots: roots }),
    });
  }

  private async tier2(text: Query, tier1: readonly Hit[], suggest: Suggest): Promise<void> {
    let corpus: Hit[];
    try {
      corpus = await searchRemote(text, this.deps);
    } catch {
      return;
    }
    if (text !== this.current) return;
    this.shown = appendTier2(tier1, corpus).slice(0, OMNIBOX_HIT_LIMIT);
    suggest(omniboxRows(text, this.shown));
  }
}
