# dynomark daemon

The daemon runtime of Dynomark (`docs/design/DYNOMARK.DESIGN.md`, APPROVED):
it ingests saves from the extension, captures, enriches and embeds them,
places and files them through write batches the extension applies, and
serves tier-2 search, undo, grounded chat (`ask`), audit and rebuild diffs,
pin/lock flags and the writer marker. It speaks transport contract v1
(`dynomark/contract/v1/`, every request type served) over an owner-only
unix socket.

## Layout

```
src/dynomark_daemon/
  domain/      rules and values (pure; stdlib only)
  app/         use cases, one per Behaviors row; ports as keyword deps
  ports/       Protocols: store, embedding, completion, content, transport, clock
  wire/        contract v1 models (Pydantic), codec, wire <-> domain mapping
  adapters/    sqlite_store, records (JSON rows), socket_server, dispatch,
               framing, fetch, readable, ollama, host_manifest
  testing/     in-memory fakes of every port (shared by all suites);
               e2e.py is the integration e2e's daemon: production wiring,
               scripted fake models (python -m, no console script)
  settings.py  Config from TOML + environment; paths
  container.py composition root: build_ports, JobLoop, Daemon
  cli.py       dynomark-daemon (Click)
  host.py      dynomark-host (native-messaging host tds.dynomark)
  logs.py      structlog JSON lines
```

## Build and test

```
cd dynomark/daemon
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

`pytest` runs three layers: `tests/unit` (fakes, no I/O), `tests/contract`
(golden files and the parametrized port suites; the SQLite store runs the
same store suite as the fake) and `tests/integration` (temp sqlite files,
unix sockets, a subprocess, `http.server` on 127.0.0.1; marker
`integration`). Select with `-m integration` or `-m "not integration"`.
The only external dependency is a real Ollama: `test_ollama_live.py`
skips when none is reachable at `$OLLAMA_HOST` with the default models.

## Install and run (macOS)

```
uv tool install ./dynomark/daemon        # puts dynomark-daemon, dynomark-host in ~/.local/bin
ollama pull nomic-embed-text
ollama pull llama3.1:8b
mkdir -p ~/.config/dynomark
printf 'role = "writer"\nhost_id = "mbp"\n' > ~/.config/dynomark/config.toml
mkdir -p -m 700 ~/.local/state/dynomark
dynomark-daemon launchd-plist > ~/Library/LaunchAgents/tds.dynomark.daemon.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/tds.dynomark.daemon.plist
dynomark-daemon install-host-manifest --extension-id <32-letter id from chrome://extensions>
dynomark-daemon check
```

`check` prints one line each for config, role, store, socket, Ollama and
models, exits 1 on any `FAIL`, and changes nothing (it opens the store
read-only and only probes the socket). Stop the agent with
`launchctl bootout gui/$(id -u)/tds.dynomark.daemon`. On Linux, run
`dynomark-daemon serve` under a user service manager instead of launchd.

## Commands

| Command | What it does |
|---|---|
| `dynomark-daemon serve` | socket server + job loop until SIGTERM/SIGINT/SIGHUP |
| `dynomark-daemon check` | config, store health, socket, Ollama reachability and models |
| `dynomark-daemon install-host-manifest --extension-id ID [--browser chrome\|chromium\|all] [--host-path P]` | writes `tds.dynomark.json` for Chrome and Chromium (macOS and Linux per-user dirs), `allowed_origins` = that one extension |
| `dynomark-daemon launchd-plist [--program P]` | prints a user LaunchAgent (`RunAtLoad`, `KeepAlive`) running `serve` |
| `dynomark-host` | started by the browser; pipes stdio frames to the socket unchanged; with no daemon it answers the first frame `error` `busy` and exits |

## Config

`$XDG_CONFIG_HOME/dynomark/config.toml` (default
`~/.config/dynomark/config.toml`). A missing file means the defaults below
with role `reader`: a fresh install never writes to the tree until told.
Unknown keys and bad values are errors that name the key.

```
host_id = "mbp"                 # default: the machine name
role = "writer"                 # default: "reader"

[models]                        # Ollama model names; Config ids are "ollama:<name>"
embedding = "nomic-embed-text"  # default (design Open Question 4, provisional)
completion = "llama3.1:8b"      # default
timeout_s = 120

[store]
path = "~/.local/state/dynomark/corpus.sqlite3"

[socket]
path = "~/.local/state/dynomark/daemon.sock"

[retry]                         # RetryPolicy
attempts = 3
initial_backoff_ms = 5000
max_backoff_ms = 300000

[capture]                       # the fetch fallback
fetch_timeout_s = 15            # for the whole fetch, not each read
max_bytes = 5000000
private_addresses = false       # true: also fetch loopback, link-local, LAN

[diffs]                         # absent: rebuilds are proposed on request only
rebuild_every_hours = 168       # the job loop proposes a rebuild this often
```

Environment: `XDG_STATE_HOME`, `XDG_CONFIG_HOME`, `DYNOMARK_SOCKET` (wins
over `[socket]`), `OLLAMA_HOST` (default `http://127.0.0.1:11434`; models
count as local only on a loopback host). The browser starts
`dynomark-host` without your shell environment, so keep the socket at a
path the config file names, not only in `DYNOMARK_SOCKET`.

## Files

`$XDG_STATE_HOME/dynomark` (default `~/.local/state/dynomark`), mode 0700:
`corpus.sqlite3` (0600, WAL), `daemon.sock` (0600), `daemon.log` (0600,
JSON lines). The socket must fit a unix socket address (104 bytes on
macOS); `serve` refuses a path it cannot bind and says so.

Goal 2 (ingest received -> `APPLIED` under 60 s at P95) is read from the
log: every filed job logs `job.applied` with `received_at`, `applied_at`
and `interval_ms` (`received_at` is null if the daemon restarted in
between; join on `job_id` with `ingest.received` then).

```
jq -r 'select(.event == "job.applied") | .interval_ms' ~/.local/state/dynomark/daemon.log
```

## MVP behaviour

- Chat (`ask`): the question retrieves the top 8 entries by the same hybrid
  search tier 2 uses; the completion answers from them; only retrieved
  identities become citations (invented ones are dropped), and each
  mentioned http(s) URL outside the corpus is listed as external.
- Diffs: `diff.propose` (kind `audit` or `rebuild`) reads the latest tree
  snapshot and shows the model the `Dynomark` outline and the user's own
  bar folders. A proposed item is kept only if it moves no pinned folder,
  touches nothing locked, moves only folders the outlines hold (never a
  root or an owned root), names no writer marker, creates no non-http(s)
  bookmark, and -- for `rebuild` -- stays inside the owned roots. Nothing
  is applied until `diff.accept`: that records `accepted_at` and offers
  the item's own batch (re-checked against the current flags); an undo of
  it carries the same item reference. The Ollama adapter proposes folder
  moves and adds only; merge rules are undefined (design Open Question 1).
- Flags: `folder.flags.set` pins or locks an owned folder by node id; a
  lock keeps placement out of that folder and its subtree, and no undo
  moves the folder (the step is dropped; contract v1 has no `locked`
  reason, so `undo.result` reports it `node_moved`).
- Writer marker: a writer keeps an empty folder `dynomark-writer:<host_id>`
  directly in `Dynomark`, created by an ordinary batch after the first
  snapshot that lacks it. A writer that sees another host's marker is in
  conflict: it offers no batches, answers `undo`, `diff.accept` and
  `folder.flags.set` with `writer_conflict`, and ends new jobs `FAILED`
  (`last_error` names the other host) after indexing them.
  `writer.status` reports it.
- Backfill: an `ingest` with `backfill` true is never offered a batch; on
  the writer, one already inside `Dynomark` is recorded as filed there
  (`FILED`, no batch), every other ends `INDEXED`.

### Changing writers

Two writers are never arbitrated automatically. To move the writer role
from host OLD to host NEW:

1. On OLD: set `role = "reader"` in `config.toml` and restart the daemon
   (`launchctl kickstart -k gui/$(id -u)/tds.dynomark.daemon`).
2. In the browser (any device; it syncs): delete the folder
   `Dynomark/dynomark-writer:<OLD host_id>`.
3. On NEW: set `role = "writer"` and restart. Its first snapshot creates
   its own marker. Undo does not cross a writer change.

If NEW is switched before the old marker is gone, it reports the conflict
(`writer.status`, the settings page) and files nothing until it is.

## Adapter notes

- Store: SQLite with FTS5 (`bm25`) for full-text candidates; vectors as
  float32 blobs, KNN by brute-force cosine in Python over an in-memory
  vector cache kept consistent with the table. The dot products cost about
  0.21 s at 10,000 x 768 with `math.sumprod` and about 0.29 s without it,
  which is why the daemon requires Python 3.12+: tier-2 P95 measured
  283-306 ms on 3.12 against Goal 4's 500 ms, and 374-448 ms on 3.11.
  `sqlite-vec` is Assess on the tech radar (`lmde/TECH_RADAR.md`); it is
  the planned accelerator once promoted, and is not used until then.
  Migrations are versioned in code (`MIGRATIONS`, `PRAGMA user_version`);
  a newer schema is refused. `index.pull` pages by entry position (kept
  on replace), so its cursor is compact and survives data changes.
- Transport: asyncio, one loop that only moves bytes; the use cases stay
  synchronous and run off it. One lane thread serves every frame and every
  event delivery in arrival order (a connection's answers stay in order);
  `ask`, `search` and `diff.propose` are admitted on the lane and then run
  on a small model pool, so a slow completion delays only its own answer.
  The job loop is a thread that wakes on ingest, retry and snapshot, and
  asks the server to deliver events. Frames: 32 MiB in, 1 MiB out (pages
  shrink to fit; an oversize answer becomes `error` `internal`; a batch
  whose offer cannot fit is never offered: it is marked REJECTED and its
  job FAILED with `batch over the 1 MiB frame limit; not offered`).
- Fetch: urllib with no cookie handler and no proxy, http(s) only (also on
  redirect), size-capped, and given up once `fetch_timeout_s` has passed.
  Each host (a redirect's too) is resolved first and refused unless every
  address it resolves to is public; the connection goes to exactly the
  address that was checked. `private_addresses = true` lifts the refusal
  for an install whose saves live on a LAN or localhost. Readable text via
  `html.parser` (article, then main, then body; no script, style, nav,
  header, footer).
- Ollama: `/api/embed`, `/api/generate` with `format: json`; strict
  parsing, an unparseable answer is a retryable error.
