import type { Fold } from '../timeline/fold.js';
import { newId } from '../kernel/ids.ts';
export const gameOf = (x: string): string => `${x} // not a comment ${newId()}`;
export type Game = Fold;
