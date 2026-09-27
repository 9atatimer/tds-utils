// content.js -- spike C content script: find the PR's head repo+branch in
// the page, inject a button, and on click ask two ways: via the service
// worker (the expected path) and directly from this script (to record what
// CORS / Private Network Access do to a page-context fetch to loopback).
const PORT = 47321;

function headRef() {
  // Classic PR header: <span class="... head-ref" title="owner/repo:branch">
  const el = document.querySelector(".head-ref");
  if (el) {
    const t = (el.getAttribute("title") || el.textContent).trim();
    const m = t.match(/^([^:\s]+\/[^:\s]+):(.+)$/);
    if (m) return { repo: m[1], branch: m[2].trim(), via: ".head-ref title" };
    const [, owner, repo] = location.pathname.split("/");
    return { repo: `${owner}/${repo}`, branch: t, via: ".head-ref text" };
  }
  // Fallback: the last /owner/repo/tree/<branch> link (base precedes head).
  let found = null;
  for (const a of document.querySelectorAll('a[href*="/tree/"]')) {
    const m = (a.getAttribute("href") || "").match(/^\/([^/]+\/[^/]+)\/tree\/(.+)$/);
    if (m) found = { repo: m[1], branch: decodeURIComponent(m[2]), via: "tree link" };
  }
  return found;
}

function render(target, result) {
  if (!result.ok) {
    target.textContent = `error: ${result.error}`;
    return;
  }
  const s = result.sessions;
  target.textContent = s.length
    ? s.map((x) => `${x.name} (${x.session_id})`).join(", ")
    : "no session";
}

function askServiceWorker(ref, target) {
  chrome.runtime.sendMessage({ type: "sessions", ...ref }, (resp) => {
    render(target, resp || { ok: false, error: chrome.runtime.lastError?.message || "no reply" });
  });
}

function askDirect(ref, target) {
  const url = `http://127.0.0.1:${PORT}/sessions?repo=${encodeURIComponent(ref.repo)}&branch=${encodeURIComponent(ref.branch)}`;
  fetch(url)
    .then((r) => r.json())
    .then((sessions) => render(target, { ok: true, sessions }))
    .catch((e) => render(target, { ok: false, error: String(e) }));
}

function inject(ref) {
  const anchor = document.querySelector(".head-ref") || document.body;
  const box = document.createElement("span");
  box.id = "pr2s";
  box.innerHTML =
    ` <button id="pr2s-btn" type="button">Sessions</button>` +
    ` <span id="pr2s-ref"></span>` +
    ` sw: <span id="pr2s-sw"></span>` +
    ` direct: <span id="pr2s-direct"></span>`;
  anchor.insertAdjacentElement("afterend", box);
  box.querySelector("#pr2s-ref").textContent = `${ref.repo}:${ref.branch} [${ref.via}]`;
  box.querySelector("#pr2s-btn").addEventListener("click", () => {
    askServiceWorker(ref, box.querySelector("#pr2s-sw"));
    askDirect(ref, box.querySelector("#pr2s-direct"));
  });
}

const ref = headRef();
if (ref) inject(ref);
