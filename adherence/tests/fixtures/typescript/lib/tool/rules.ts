// lib/tool/rules.ts -- the order rules.
import { LIMIT } from './schema.mjs';

export class Order {
  total: number;
  status = 'open';

  isLarge(): boolean {
    return this.total > LIMIT;
  }
}

export function classify(order: Order, { strict = false }: { strict?: boolean } = {}): string {
  if (order.status === 'open') {
    return 'pending';
  }
  return 'done';
}

export function unfinished(order: Order): number {
  throw new NotImplementedError();
}
