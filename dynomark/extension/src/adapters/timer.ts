// timer.ts -- the Timer adapter: setTimeout. A service worker's timers die
// with it; nothing durable may wait on one (the batch cursor does not).

import type { Timer } from '../ports/timer.js';

export class SystemTimer implements Timer {
  after(ms: number, callback: () => void): () => void {
    const handle = setTimeout(callback, ms);
    return () => clearTimeout(handle);
  }
}
