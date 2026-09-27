// FakeNavigator.ts -- an in-memory Navigator: records every URL opened and how.

import type { Url } from '../../src/domain/values.js';
import type { Disposition, Navigator } from '../../src/ports/navigator.js';

export class FakeNavigator implements Navigator {
  readonly opened: { readonly url: Url; readonly disposition: Disposition }[] = [];

  open(url: Url, disposition: Disposition): Promise<void> {
    this.opened.push({ url, disposition });
    return Promise.resolve();
  }
}
