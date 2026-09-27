// navigator.ts -- the Navigator port: open a URL in the browser (design, "The
// extension", Tier-1 search: Enter opens the hit by navigating to its
// identity; contract v1 README, "Identity").

import type { Url } from '../domain/values.js';

/** Where to open it, as the omnibox reports the user's choice. */
export type Disposition = 'currentTab' | 'newForegroundTab' | 'newBackgroundTab';

export interface Navigator {
  open(url: Url, disposition: Disposition): Promise<void>;
}
