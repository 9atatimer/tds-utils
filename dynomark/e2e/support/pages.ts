/// <reference types="node" />
// pages.ts -- a throw-away HTTP server on 127.0.0.1 (an ephemeral port)
// serving fixed pages: the pages a scenario opens in a tab and saves, and
// the only origin the browser may reach (no network). The daemon's fetch
// fallback may read them too; that is still 127.0.0.1.

import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface PageServer {
  /** The server's origin, e.g. http://127.0.0.1:43123 */
  readonly origin: string;
  /** Every path requested, in order. */
  readonly requested: string[];
  /** The absolute URL of `path`. */
  url(path: string): string;
  close(): Promise<void>;
}

/** Serve `pages` (path -> HTML) on 127.0.0.1; any other path is a 404. */
export function servePages(pages: Readonly<Record<string, string>>): Promise<PageServer> {
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
      const origin = `http://127.0.0.1:${port}`;
      resolve({
        origin,
        requested,
        url: (path) => `${origin}${path}`,
        close: () =>
          new Promise((done) => {
            server.close(() => done());
            server.closeAllConnections();
          }),
      });
    });
  });
}
