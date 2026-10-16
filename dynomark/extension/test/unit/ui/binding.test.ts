// binding.test.ts -- Key Decisions "Writer binding" (2026-10-16, issue #419):
// a writer daemon files for the first profile that completes a full hello;
// the extension shows, on its settings page, when this browser is served as
// a reader because the writer is bound to another profile, and how to move
// the binding (`dynomark-daemon rebind`). A reinstall must not stop filing
// silently.

import { describe, expect, it } from 'vitest';
import { bindingText, readerBindingText } from '../../../src/ui/binding.js';

describe('Writer binding -- shown on the settings page', () => {
  it('Given role reader and writer_binding other_profile, When the banner text is made, Then it says this browser is served as a reader because the writer is bound to another profile, and names rebind', () => {
    const text = readerBindingText({ role: 'reader', writer_binding: 'other_profile' });
    expect(text).toMatch(/served as a reader/);
    expect(text).toMatch(/another browser profile/);
    expect(text).toContain('dynomark-daemon rebind');
  });

  it.each([
    { role: 'writer' as const, writer_binding: 'this_profile' as const },
    { role: 'reader' as const, writer_binding: 'unbound' as const },
    { role: 'reader' as const },
    undefined,
  ])('Given %o, When the banner text is made, Then there is none', (daemon) => {
    expect(readerBindingText(daemon)).toBeUndefined();
  });

  it('Given each binding, When the row text is made, Then it says whom the writer files for', () => {
    expect(bindingText('this_profile')).toMatch(/this browser/);
    expect(bindingText('other_profile')).toMatch(/another browser profile/);
    expect(bindingText('unbound')).toMatch(/next/);
    expect(bindingText(undefined)).toBe('-');
  });
});
