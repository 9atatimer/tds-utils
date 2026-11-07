import { fold } from '@demo/core';
import { newId } from '@demo/core/domain/kernel';
const lazy = () => import('@demo/core/ports');
export const memory = [fold, newId, lazy];
