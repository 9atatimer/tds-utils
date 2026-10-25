import { Order } from './rules';
import type { Store } from './ports';

@injectable()
export class FsStore implements Store {
  constructor(private readonly root: string) {
    this.opened = true;
  }

  save(order: Order): void {
    const home = process.env.HOME;
    console.log(home, 'claude-opus', order);
  }
}
