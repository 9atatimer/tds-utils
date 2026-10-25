import type { Order } from './rules';

export interface Store {
  save(order: Order): void;
}
