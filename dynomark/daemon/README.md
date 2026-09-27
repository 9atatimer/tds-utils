# dynomark daemon

The daemon runtime of Dynomark (`docs/design/DYNOMARK.DESIGN.md`, APPROVED):
it ingests saves from the extension, captures, enriches and embeds them,
places and files them through write batches the extension applies, and
serves tier-2 search and undo. It speaks transport contract v1
(`dynomark/contract/v1/`) over an owner-only unix socket.

## Layout

```
src/dynomark_daemon/
  domain/      rules and values (pure; stdlib only)
  app/         use cases, one per Behaviors row; ports as keyword deps
  ports/       Protocols: store, embedding, completion, content, transport, clock
  wire/        contract v1 models (Pydantic), codec, wire <-> domain mapping
  adapters/    sqlite_store, records (JSON rows), socket_server, dispatch,
               framing, fetch, readable, ollama, host_manifest
  testing/     in-memory fakes of every port (shared by all suites)
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
fetch_timeout_s = 15
max_bytes = 5000000
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

## Adapter notes

- Store: SQLite with FTS5 (`bm25`) for full-text candidates; vectors as
  float32 blobs, KNN by brute-force cosine in Python (about 0.27 s at
  10,000 x 768 on Python 3.11, a few ms on 3.12+ via `math.sumprod`).
  `sqlite-vec` is Assess on the tech radar (`lmde/TECH_RADAR.md`); it is
  the planned accelerator once promoted, and is not used until then.
  Migrations are versioned in code (`MIGRATIONS`, `PRAGMA user_version`);
  a newer schema is refused. `index.pull` pages by entry position (kept
  on replace), so its cursor is compact and survives data changes.
- Transport: asyncio, one loop; the use cases stay synchronous. The job
  loop is a thread that wakes on ingest, retry and snapshot, and asks the
  server to deliver events. Frames: 32 MiB in, 1 MiB out (pages shrink to
  fit; an oversize answer becomes `error` `internal`).
- Fetch: urllib with no cookie handler and no proxy, http(s) only (also on
  redirect), size-capped; readable text via `html.parser` (article, then
  main, then body; no script, style, nav, header, footer).
- Ollama: `/api/embed`, `/api/generate` with `format: json`; strict
  parsing, an unparseable answer is a retryable error.
- Not served yet (answered `error` `invalid`): `ask`, `diff.*`,
  `folder.flags.set`, `writer.status` (MVP tasks 028-030).
