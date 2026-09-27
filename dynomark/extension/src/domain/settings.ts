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
  /** Follow Up behaviour on the writer: open a save no tab shows in a background tab and read it (default on). */
  readonly capture_in_background?: boolean;
}

/** The settings a page may change. */
export interface SettingsChange {
  readonly capture_from_tab?: boolean;
  readonly capture_in_background?: boolean;
}

// --- Pure helpers ---

/** The settings of a profile seen for the first time. */
export function newSettings(profile_id: ProfileId): Settings {
  return { profile_id, transport: 'native_messaging', capture_from_tab: true, capture_in_background: true };
}

/** The settings with `change` applied. */
export function withChange(settings: Settings, change: SettingsChange): Settings {
  return {
    ...settings,
    ...(change.capture_from_tab === undefined ? {} : { capture_from_tab: change.capture_from_tab }),
    ...(change.capture_in_background === undefined ? {} : { capture_in_background: change.capture_in_background }),
  };
}

/** True unless the user turned tab capture off (settings saved before the field existed capture). */
export function capturesFromTab(settings: Settings): boolean {
  return settings.capture_from_tab ?? true;
}

/** True unless the user turned background-tab capture off (settings saved before the field existed capture). */
export function capturesInBackground(settings: Settings): boolean {
  return settings.capture_in_background ?? true;
}
