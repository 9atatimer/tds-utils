# Spikes

Throwaway code, one question each. The findings live in `../CONCEPT.md`
under "Spike findings"; the code here is evidence, never the design, and
is deleted once phase 2 has read the findings.

| Spike | Question | Runs where |
|---|---|---|
| `A-map.zsh` | Can (owner/repo, branch) -> tmux session be answered from the live tmux server plus git, with no daemon and no state, fast enough to sit behind a click? | Linux or macOS with tmux |
| `A-verify.zsh` | Harness for A: throwaway tmux server, fixture clones, assertion, timing at 4 and 30 sessions | same |
| `serve.py` | Stand-in for the machine-side half: loopback HTTP, runs A per request, zero state. Is a stateless answer fast enough? | same |
| `B-jump.zsh` | Can a script bring Terminal.app forward on a given tmux session? | macOS only, NOT RUN |
| `C-extension/` | Can an MV3 extension on a PR page read head repo+branch, reach a loopback service, and must the fetch live in the service worker? | Playwright Chromium, against a fixture page |

Run:

```
zsh A-verify.zsh                       # spike A end to end, on a private tmux socket
zsh A-map.zsh -t                       # the map of YOUR live tmux server, timed
python3 serve.py                       # stand-in daemon over the live server
python3 serve.py --fake C-extension/test/sessions.tsv   # canned rows for spike C
zsh B-jump.zsh <session_id>            # on the Mac; NOT RUN yet

cd C-extension/test && npm install playwright    # once
PW_CHROME=<path to a chromium binary> node run.mjs [--no-cors|--down]
```

Spike C's harness starts `serve.py` and a TLS fixture server on port 443
itself (root, or a port capability), and maps `github.com` to it with
`--host-resolver-rules`. On the Mac the honest test is Chrome's
"Load unpacked" on `C-extension/` and a real PR page, with `serve.py`
running.
