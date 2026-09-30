/// <reference types="node" />
// localServer.ts -- a throw-away HTTP server on 127.0.0.1 (an ephemeral port)
// serving fixed pages, for e2e tests that need the browser to load a real
// page without the network (background-tab capture opens a URL itself, so a
// Playwright route in a page is not enough to prove the window loaded it).

import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface LocalServer {
  /** The server's origin, e.g. http://127.0.0.1:43123 */
  readonly origin: string;
  /** Every path requested, in order. */
  readonly requested: string[];
  close(): Promise<void>;
}

/** Serve `pages` (path -> HTML) on 127.0.0.1; any other path is a 404. */
export function serveLocal(pages: Readonly<Record<string, string>>): Promise<LocalServer> {
  const requested: string[] = [];
  const server: Server = createServer((req, res) => {
    const path = req.url ?? '/';
    requested.push(path);
    const body = pages[path];
    res.writeHead(body === undefined ? 404 : 200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(body ?? 'not found');
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      resolve({
        origin: `http://127.0.0.1:${port}`,
        requested,
        close: () =>
          new Promise((done) => {
            server.close(() => done());
            server.closeAllConnections();
          }),
      });
    });
  });
}
