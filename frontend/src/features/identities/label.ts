/**
 * What to call a person: their name once someone has named them, else a label derived from the start
 * of the identity's id (presentation only, never stored as a name). The same identity has the same
 * label on every screen.
 */
export const personLabel = (identityId: string, person?: { display_name: string } | null): string =>
  person ? person.display_name : `Person ${identityId.replace(/-/g, '').slice(0, 6).toUpperCase()}`
