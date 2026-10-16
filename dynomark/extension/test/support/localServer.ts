/// <reference types="node" />
// localServer.ts -- a throw-away HTTP server on 127.0.0.1 (an ephemeral port)
// serving fixed pages, for e2e tests that need the browser to load a real
// page without the network (background-tab capture opens a URL itself, so a
// Playwright route in a page is not enough to prove the window loaded it). A
// path can answer a 302 instead; `{origin}` in its location is the server's
// own 127.0.0.1 origin.

import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface LocalServer {
  /** The server's origin, e.g. http://127.0.0.1:43123 */
  readonly origin: string;
  /** Every path requested, in order. */
  readonly requested: string[];
  close(): Promise<void>;
}

/** A path that answers 302 to `redirect` (`{origin}` is replaced by the server's origin). */
export interface Redirect {
  readonly redirect: string;
}

/** Serve `pages` (path -> HTML, or a redirect) on 127.0.0.1; any other path is a 404. */
export function serveLocal(pages: Readonly<Record<string, string | Redirect>>): Promise<LocalServer> {
  const requested: string[] = [];
  let origin = '';
  const server: Server = createServer((req, res) => {
    const path = req.url ?? '/';
    requested.push(path);
    const body = pages[path];
    if (typeof body === 'object') {
      res.writeHead(302, { location: body.redirect.replace('{origin}', origin) });
      res.end();
      return;
    }
    res.writeHead(body === undefined ? 404 : 200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(body ?? 'not found');
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      origin = `http://127.0.0.1:${port}`;
      resolve({
        origin,
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
