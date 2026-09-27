// sw.js -- spike C service worker: the only place an extension fetch can
// carry host_permissions, so this is where the loopback call lives.
const PORT = 47321;

function sessionsUrl(repo, branch) {
  return `http://127.0.0.1:${PORT}/sessions?repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}`;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "sessions") return false;
  console.log("sw: fetching", sessionsUrl(msg.repo, msg.branch));
  fetch(sessionsUrl(msg.repo, msg.branch))
    .then((r) => r.json())
    .then((sessions) => sendResponse({ ok: true, sessions }))
    .catch((e) => sendResponse({ ok: false, error: String(e) }));
  return true; // keep the channel open for the async reply
});
