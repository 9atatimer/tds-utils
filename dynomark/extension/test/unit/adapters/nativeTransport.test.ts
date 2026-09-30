// nativeTransport.test.ts -- the TransportPort on chrome.runtime.connectNative
// (contract v1 README, "Endpoint": host name tds.dynomark) runs the port
// contract over a tiny stand-in for native messaging; frames from the daemon
// are validated against the contract schema before anything sees them, and
// the link's state is observable for reconnection and the settings page.

import { describe, expect, it } from 'vitest';
import { InvalidFrame, NativeMessagingTransport } from '../../../src/adapters/chrome/nativeTransport.js';
import type { LinkState } from '../../../src/ports/transport.js';
import { TransportLost } from '../../../src/ports/transport.js';
import type { EventMessage } from '../../../src/wire/messages.js';
import { describeTransportContract } from '../../port-contracts/transport.contract.js';
import { NativeMessagingStub } from '../../stubs/chromeNative.js';

describeTransportContract('NativeMessagingTransport (stubbed connectNative)', () => {
  const stub = new NativeMessagingStub();
  return { transport: new NativeMessagingTransport(stub), daemon: stub.daemon };
});

// --- Builders ---

const STATUS = { v: 1 as const, type: 'status' as const };

function setup(options: { readonly hostName?: string } = {}) {
  const stub = new NativeMessagingStub();
  const transport = new NativeMessagingTransport(stub, options);
  const states: LinkState[] = [];
  transport.onLink((s) => states.push(s));
  return { stub, transport, states };
}

// --- Tests ---

describe('NativeMessagingTransport', () => {
  it('Given no host name, When the first request is sent, Then it connects to tds.dynomark, once, and the link is connected', async () => {
    const { stub, transport, states } = setup();
    void transport.send({ ...STATUS, id: 'req-1' });
    void transport.send({ ...STATUS, id: 'req-2' });
    await stub.daemon.nextRequest();
    expect(stub.connects).toEqual(['tds.dynomark']);
    expect(transport.linkState()).toEqual({ state: 'connected' });
    expect(states).toEqual([{ state: 'connected' }]);
  });

  it('Given a host name, When a request is sent, Then that host is connected', async () => {
    const { stub, transport } = setup({ hostName: 'tds.dynomark_test' });
    void transport.send({ ...STATUS, id: 'req-1' });
    await stub.daemon.nextRequest();
    expect(stub.connects).toEqual(['tds.dynomark_test']);
  });

  it('Given the host fails, When the port disconnects, Then the link is disconnected with chrome.runtime.lastError as detail', async () => {
    const { stub, transport, states } = setup();
    const lost = transport.send({ ...STATUS, id: 'req-1' });
    await stub.daemon.nextRequest();
    stub.exit('Specified native messaging host not found.');
    await expect(lost).rejects.toEqual(new TransportLost('disconnected'));
    expect(states.at(-1)).toEqual({ state: 'disconnected', detail: 'Specified native messaging host not found.' });
  });

  it('Given superseded, When the error arrives, Then the link is superseded and connectNative is never called again', async () => {
    const { stub, transport } = setup();
    const inFlight = transport.send({ ...STATUS, id: 'req-1' });
    await stub.daemon.nextRequest();
    await stub.daemon.drop('superseded');
    await expect(inFlight).rejects.toMatchObject({ reason: 'superseded' });
    await expect(transport.send({ ...STATUS, id: 'req-2' })).rejects.toMatchObject({ reason: 'superseded' });
    expect(stub.connects).toHaveLength(1);
    expect(transport.linkState()).toEqual({ state: 'superseded' });
  });

  it('Given a response that fails the schema, When it arrives for a request in flight, Then that request rejects InvalidFrame and the link stays up', async () => {
    const { stub, transport } = setup();
    const bad = transport.send({ ...STATUS, id: 'req-1' });
    const good = transport.send({ ...STATUS, id: 'req-2' });
    await stub.daemon.nextRequest();
    await stub.daemon.nextRequest();
    stub.deliver({ v: 1, type: 'status.result', re: 'req-1', role: 'boss' });
    await expect(bad).rejects.toBeInstanceOf(InvalidFrame);
    stub.deliver({ v: 1, type: 'events.replay.result', re: 'req-2', count: 0 });
    expect(await good).toMatchObject({ re: 'req-2' });
    expect(transport.linkState()).toEqual({ state: 'connected' });
  });

  it('Given an event that fails the schema or a request-shaped frame, When it arrives, Then no listener sees it', async () => {
    const { stub, transport } = setup();
    const seen: EventMessage[] = [];
    transport.onEvent((e) => seen.push(e));
    void transport.send({ ...STATUS, id: 'req-1' });
    await stub.daemon.nextRequest();
    stub.deliver({ v: 1, type: 'job.updated', event_id: 'evt-1', job: { job_id: 'j' } });
    stub.deliver({ v: 1, type: 'status', id: 'req-9' });
    stub.deliver({
      v: 1,
      type: 'diff.proposed',
      event_id: 'evt-2',
      diff: { diff_id: 'd', kind: 'audit', proposed_at: 1, item_count: 1, unaccepted_count: 1 },
    });
    expect(seen.map((e) => e.event_id)).toEqual(['evt-2']);
  });

  it('Given a response for no request in flight, When it arrives, Then it is ignored', async () => {
    const { stub, transport } = setup();
    const reply = transport.send({ ...STATUS, id: 'req-1' });
    await stub.daemon.nextRequest();
    stub.deliver({ v: 1, type: 'events.replay.result', re: 'req-unknown', count: 0 });
    stub.deliver({ v: 1, type: 'events.replay.result', re: 'req-1', count: 0 });
    expect(await reply).toMatchObject({ re: 'req-1' });
  });

  it('Given the port is already gone when a request is posted, When postMessage throws, Then the request rejects as a disconnect', async () => {
    const { stub, transport } = setup();
    void transport.send({ ...STATUS, id: 'req-1' }).catch(() => undefined);
    await stub.daemon.nextRequest();
    stub.breakPostMessage();
    await expect(transport.send({ ...STATUS, id: 'req-2' })).rejects.toEqual(new TransportLost('disconnected'));
  });
});
