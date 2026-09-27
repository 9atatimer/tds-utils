// settings.ts -- the extension's own settings (design, "Settings": transport
// selection and Follow Up behaviour, in extension-local storage; nothing
// secret). The profile id is generated once and kept (contract v1 README,
// "Connection lifecycle", step 1).

import { newSettings, type Settings } from '../domain/settings.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';

// --- Flow ---

/** The stored settings, or new ones (with a fresh profile id) stored now. */
export async function ensureSettings(deps: { readonly storage: StoragePort; readonly ids: IdSource }): Promise<Settings> {
  const stored = await deps.storage.loadSettings();
  if (stored !== undefined) return stored;
  const fresh = newSettings(deps.ids.next());
  await deps.storage.saveSettings(fresh);
  return fresh;
}

/** Turn capture from an open tab on or off; returns the settings as stored. */
export async function setCaptureFromTab(
  settings: Settings,
  capture_from_tab: boolean,
  deps: { readonly storage: StoragePort },
): Promise<Settings> {
  const next = { ...settings, capture_from_tab };
  await deps.storage.saveSettings(next);
  return next;
}
