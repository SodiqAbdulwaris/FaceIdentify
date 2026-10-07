/**
 * What to call a person nobody has named yet. The same identity has the same label on every
 * screen (names and corrections arrive with M5), taken from the start of its id.
 */
export const personLabel = (identityId: string): string =>
  `Person ${identityId.replace(/-/g, '').slice(0, 6).toUpperCase()}`
