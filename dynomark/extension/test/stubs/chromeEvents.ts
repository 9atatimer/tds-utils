// chromeEvents.ts -- a tiny chrome.events.Event stand-in: listeners are added
// and the test fires the event with the arguments Chrome would pass.

export class EventStub<A extends unknown[], R = void> {
  readonly listeners: ((...args: A) => R)[] = [];

  addListener(callback: (...args: A) => R): void {
    this.listeners.push(callback);
  }

  /** Call every listener, returning what each returned. */
  fire(...args: A): R[] {
    return this.listeners.map((listener) => listener(...args));
  }
}
