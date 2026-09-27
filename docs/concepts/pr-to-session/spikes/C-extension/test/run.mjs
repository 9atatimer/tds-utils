// run.mjs -- spike C harness. Loads the unpacked extension into Playwright
// Chromium, serves the fixture as https://github.com/... from a local TLS
// server (host-resolver-rules), clicks the injected button, and prints what each fetch
// path (service worker vs content script) got back.
//
//   node run.mjs            serve.py up, CORS headers on
//   node run.mjs --no-cors  serve.py up, no CORS / PNA headers
//   node run.mjs --down     serve.py not started
//
// `npm install playwright` next to this file first. Chromium build is
// taken from PW_CHROME if set (the container's preinstalled build differs
// from the one this Playwright wants).
import { chromium } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { connect } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ext = join(here, "..");
const args = new Set(process.argv.slice(2));
const PR_URL = "https://github.com/9atatimer/tds-utils/pull/999";

function startServer() {
  if (args.has("--down")) return null;
  const a = [join(here, "..", "..", "serve.py"), "--fake", join(here, "sessions.tsv")];
  if (args.has("--no-cors")) a.push("--no-cors");
  const p = spawn("python3", a, { stdio: ["ignore", "inherit", "inherit"] });
  return p;
}

function tcpOpen(port) {
  return new Promise((resolve) => {
    const s = connect({ host: "127.0.0.1", port }, () => { s.destroy(); resolve(true); });
    s.on("error", () => resolve(false));
  });
}

async function waitForServer(port) {
  for (let i = 0; i < 50; i++) {
    if (await tcpOpen(port)) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`port ${port} did not come up`);
}

function startFixture(certdir) {
  spawnSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
    "-subj", "/CN=github.com", "-keyout", join(certdir, "key.pem"), "-out", join(certdir, "cert.pem")],
    { stdio: "ignore" });
  return spawn("python3", [join(here, "fixture_server.py"), certdir], { stdio: ["ignore", "inherit", "inherit"] });
}

async function main() {
  const profile = mkdtempSync(join(tmpdir(), "pr2s-"));
  const procs = [];
  try {
    const server = startServer();
    if (server) { procs.push(server); await waitForServer(47321); }
    procs.push(startFixture(profile));
    await waitForServer(443);
    await drive(profile);
  } finally {
    for (const p of procs) p.kill();
    rmSync(profile, { recursive: true, force: true });
  }
}

async function drive(profile) {
  const ctx = await chromium.launchPersistentContext(profile, {
    channel: process.env.PW_CHROME ? undefined : "chromium",
    executablePath: process.env.PW_CHROME || undefined,
    headless: true,
    args: [
      `--disable-extensions-except=${ext}`,
      `--load-extension=${ext}`,
      // The container sets HTTPS_PROXY and Chromium honours it; a laptop
      // Chrome has no such proxy. Set PW_PROXY=1 to see the proxied behaviour.
      ...(process.env.PW_PROXY ? [] : ["--no-proxy-server"]),
      // github.com is the local fixture server; no Playwright interception.
      "--host-resolver-rules=MAP github.com 127.0.0.1",
      "--ignore-certificate-errors",
    ],
  });
  try {
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on("console", (m) => { if (m.type() === "error") pageErrors.push(m.text()); });
    ctx.on("serviceworker", (w) => w.on("console", (m) => console.log("sw console:", m.text())));
    for (const w of ctx.serviceWorkers()) w.on("console", (m) => console.log("sw console:", m.text()));
    await page.goto(PR_URL);
    await page.waitForSelector("#pr2s-btn", { timeout: 10000 });
    console.log("ref:", await page.textContent("#pr2s-ref"));
    await page.click("#pr2s-btn");
    await page.waitForFunction(
      () => document.querySelector("#pr2s-sw").textContent || document.querySelector("#pr2s-direct").textContent,
      null, { timeout: 10000 }
    ).catch(() => console.log("neither path answered within 10s"));
    await page.waitForTimeout(3000);
    const sw = await page.textContent("#pr2s-sw");
    const direct = await page.textContent("#pr2s-direct");
    console.log("sw:     ", sw);
    console.log("direct: ", direct);
    for (const e of pageErrors) console.log("console.error:", e);
    const expectSw = args.has("--down") ? /error/ : /claude@9atatimer\/tds-utils=claude\/foo\+spike \(\$3\)/;
    if (!expectSw.test(sw)) {
      console.log("FAIL: service-worker path did not match", expectSw);
      process.exitCode = 1;
    } else {
      console.log("PASS");
    }
  } finally {
    await ctx.close();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
