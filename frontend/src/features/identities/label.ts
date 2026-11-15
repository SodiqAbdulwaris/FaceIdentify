/**
 * What to call a person: their name once someone has named them, else a label derived from the start
 * of the identity's id (presentation only, never stored as a name). The same identity has the same
 * label on every screen.
 */
export const personLabel = (identityId: string, person?: { display_name: string } | null): string =>
  person ? person.display_name : `Person ${identityId.replace(/-/g, '').slice(0, 6).toUpperCase()}`

/** Where an appearance is looked at: the camera's history for a camera face, else its image. */
export const appearanceLink = (
  sourceId: string,
  face: { face_crop: unknown } | null | undefined,
): string => (face?.face_crop ? `/cameras/${sourceId}` : `/library/source/${sourceId}`)
