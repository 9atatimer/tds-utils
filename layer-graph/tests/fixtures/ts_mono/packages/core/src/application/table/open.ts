import {
  newId,
} from '../../domain/kernel/ids.ts';
import type { Port } from '../../ports/index.ts';
import { z } from 'zod';
export const openTable = (p: Port): string => newId() + String(z);
