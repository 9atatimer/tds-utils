// lib/tool/schema.mjs -- what a record must hold.

export const LIMIT = 3;

export const isPlainObject = (value) => value !== null && typeof value === 'object';

export function hasState(record) {
  return isPlainObject(record) && 'state' in record;
}
