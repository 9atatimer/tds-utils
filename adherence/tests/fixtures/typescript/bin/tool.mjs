#!/usr/bin/env node
// tool -- a one-file tool.
import { readFileSync } from 'node:fs';

// --- Predicates ---
function isEven(n) {
  return n % 2 === 0;
}

// --- Action functions ---
function load(path) {
  globalThis.counter += 1;
  return JSON.parse(readFileSync(path, 'utf8'));
}
