// settings.ts -- the extension's own settings (design, "Settings": transport
// selection and Follow Up behaviour, in extension-local storage; nothing secret).

import type { ProfileId } from './values.js';

/** Which `TransportPort` adapter the composition root wires. v1 has one. */
export type TransportSelection = 'native_messaging';

export interface Settings {
  /** Generated once (a UUIDv4) and named in every `hello`. */
  readonly profile_id: ProfileId;
  readonly transport: TransportSelection;
}
