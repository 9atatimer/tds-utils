#!/usr/bin/env node
// pipe-host.mjs -- the e2e stand-in for the native-messaging shim (contract
// v1 README, "Framing": the host is a transparent byte pipe). Chrome starts it
// on connectNative('tds.dynomark'); it connects to the unix socket named by
// $DYNOMARK_SOCKET (the e2e fake daemon) and copies bytes both ways, never
// parsing a frame. It exits when either side closes.

import { createConnection } from 'node:net';

function main() {
  const path = process.env.DYNOMARK_SOCKET;
  if (path === undefined || path === '') process.exit(2);
  const socket = createConnection(path);
  process.stdin.pipe(socket);
  socket.pipe(process.stdout);
  process.stdin.on('end', () => socket.end());
  socket.on('close', () => process.exit(0));
  socket.on('error', () => process.exit(1));
}

main();
