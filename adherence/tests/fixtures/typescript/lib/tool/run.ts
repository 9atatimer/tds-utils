import { setTimeout as sleep } from 'node:timers/promises';
import * as rules from './rules';
import { Order, classify } from './rules';
import type { Store } from './ports';

export async function closeOrder(order: Order, deps: { store: Store }): Promise<string> {
  order.status = 'closed';
  await sleep(1);
  deps.store.save(order);

  const helper = (): void => {};

  return classify(order);
}
