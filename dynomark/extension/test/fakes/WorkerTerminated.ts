// WorkerTerminated.ts -- thrown by a fake when the simulated service worker
// dies. Real termination just stops the JS; the fakes raise this instead and
// make every later call through that worker's ports fail, so no code after the
// kill can land an effect.

export class WorkerTerminated extends Error {
  constructor() {
    super('service worker terminated');
    this.name = 'WorkerTerminated';
  }
}
