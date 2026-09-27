// settings.ts -- the extension's own settings (design, "Settings": transport
// selection and Follow Up behaviour, in extension-local storage; nothing
// secret). The profile id is generated once and kept (contract v1 README,
// "Connection lifecycle", step 1).

import { newSettings, withChange, type Settings, type SettingsChange } from '../domain/settings.js';
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

/** Change the Follow Up behaviour settings (open-tab and background-tab capture); returns the settings as stored. */
export async function changeSettings(
  settings: Settings,
  change: SettingsChange,
  deps: { readonly storage: StoragePort },
): Promise<Settings> {
  const next = withChange(settings, change);
  await deps.storage.saveSettings(next);
  return next;
}
