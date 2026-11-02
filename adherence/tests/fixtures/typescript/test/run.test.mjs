import { test } from 'node:test';
import assert from 'node:assert/strict';
import { closeOrder } from '../lib/tool/run.ts';

test('closeOrder saves', async () => {
  assert.equal(await closeOrder(order(), { store }), 'pending');
});

test('nothing', () => {
  closeOrder(null, {});
});

describe('order', () => {
  it('is large', () => {
    expect(isLarge(5)).toBe(true);
  });
});
