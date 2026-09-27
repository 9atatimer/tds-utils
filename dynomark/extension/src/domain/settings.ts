// settings.ts -- the extension's own settings (design, "Settings": transport
// selection and Follow Up behaviour, in extension-local storage; nothing secret).

import type { ProfileId } from './values.js';

/** Which `TransportPort` adapter the composition root wires. v1 has one. */
export type TransportSelection = 'native_messaging';

export interface Settings {
  /** Generated once (a UUIDv4) and named in every `hello`. */
  readonly profile_id: ProfileId;
  readonly transport: TransportSelection;
  /** Follow Up behaviour: read the saved page from an open tab (default), or leave capture to the daemon's fetch. */
  readonly capture_from_tab?: boolean;
}

// --- Pure helpers ---

/** The settings of a profile seen for the first time. */
export function newSettings(profile_id: ProfileId): Settings {
  return { profile_id, transport: 'native_messaging', capture_from_tab: true };
}

/** True unless the user turned tab capture off (settings saved before the field existed capture). */
export function capturesFromTab(settings: Settings): boolean {
  return settings.capture_from_tab ?? true;
}
