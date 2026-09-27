// transport.fake.test.ts -- the TransportPort fake honours the port contract,
// and records every frame a use case sends so tests can assert on the wire.

import { describe, expect, it } from 'vitest';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { describeTransportContract } from '../../port-contracts/transport.contract.js';

describeTransportContract('FakeTransport', () => {
  const transport = new FakeTransport();
  return { transport, daemon: transport.daemon };
});

describe('FakeTransport', () => {
  it('Given an auto-answering daemon, When a request is re-sent after a drop, Then both frames are recorded under one id', async () => {
    const transport = new FakeTransport();
    const first = transport.send({ v: 1, type: 'events.replay', id: 'req-1' });
    await transport.daemon.drop('disconnected');
    await expect(first).rejects.toMatchObject({ reason: 'disconnected' });
    transport.autoAnswer((req) => ({ v: 1, type: 'events.replay.result', re: req.id, count: 0 }));
    await transport.send({ v: 1, type: 'events.replay', id: 'req-1' });
    expect(transport.sent.map((r) => r.id)).toEqual(['req-1', 'req-1']);
    expect(transport.connections).toBe(2);
  });

  it('Given a request already in flight, When the same id is sent again on the same connection, Then the fake throws (a caller bug)', () => {
    const transport = new FakeTransport();
    void transport.send({ v: 1, type: 'status', id: 'req-1' });
    expect(() => transport.send({ v: 1, type: 'status', id: 'req-1' })).toThrow(/in flight/);
  });
});
