// contentSource.ts -- the extension-side ContentSourcePort: page content from
// an open tab (design, seam table, "Where page content comes from"; the daemon
// holds the fetch half of the fallback chain). The use case turns what this
// returns into a Capture; extraction to readable text is the adapter's job.

import type { TabContent } from '../domain/capture.js';
import type { Url } from '../domain/values.js';

export interface ContentSourcePort {
  /** The readable content of a tab showing exactly `url`; undefined when none does or none can be read. Never throws for those. */
  readTab(url: Url): Promise<TabContent | undefined>;
}
