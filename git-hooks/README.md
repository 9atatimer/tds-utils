# git-hooks

Global git hooks for this environment.

## Scan every clone for coding-agent poisoning

**Goal:** before you ever open a freshly-cloned repo with a coding agent (or
build it), statically scan it for *coding-agent poisoning* — hidden or
malicious instructions planted in the files an AI agent auto-ingests — and for
the broader "runs the moment you touch it" hazards.

### Why a `post-checkout` hook (git has no post-clone hook)

There is no hook that fires on `git clone` by name. What "global git hook
templates" gives you is `init.templateDir` / `core.hooksPath`: a hooks
directory that git installs into a repo at clone/init time. Copied hooks still
only run on git *events*.

The mechanism that makes a clone-time scan possible: **`git clone` performs a
checkout at the very end, which fires `post-checkout`** — and the template's
hooks are installed *before* that checkout. So a `post-checkout` hook in your
global template runs once, right after the worktree appears.

`post-checkout` also fires on ordinary `git checkout`. We tell a clone apart
because on a clone the hook's "previous HEAD" argument is the null SHA
(`000…0`); the hook only scans in that case, so branch switching stays silent.

**Caveats:** the hook does not fire on `git clone --bare` or `--no-checkout`.
For those (or any repo you already have), run the scanner by hand —
see below. A freshly-cloned repo never imports the *source's* `.git/hooks`, so
a malicious repo cannot ship its own hook to run against you.

### Install

```sh
# Recommended: per-repo hook templates (does not disturb existing repos).
bin/install-git-hook-templates                 # init.templateDir

# Alternative: one central hooks dir for ALL repos (overrides per-repo hooks).
bin/install-git-hook-templates -m hooksPath

# Preview without changing anything:
bin/install-git-hook-templates -n
```

`bin/` must be on your `PATH` so the hook can find `clone-scan` (it already is
in this environment). The hook never blocks or fails a clone; it only reports.

### The scanner: `bin/clone-scan`

Run it directly against any directory at any time:

```sh
clone-scan path/to/repo     # exit 0 = clean, 2 = warnings found
clone-scan                  # scans the current directory
```

It **only reads files — it never executes anything from the scanned repo.**
Findings are grouped by category:

| Tag              | What it catches |
|------------------|-----------------|
| `AGENT-FILE`     | Agent instruction files present (`CLAUDE.md`, `.cursorrules`, `AGENTS.md`, MCP configs, …). Informational — this is the surface to review. |
| `HIDDEN-UNICODE` | Invisible, bidi-override (Trojan Source), or Unicode-tag characters used to smuggle instructions past a human reviewer. |
| `INJECTION`      | Prompt-injection phrasing aimed at hijacking an agent ("ignore all previous instructions", "do not tell the user", …). |
| `AGENT-EXEC`     | Configs that make an agent/editor run a command on open (`.claude` hooks, MCP server launch commands). |
| `AUTORUN`        | Code that runs on install/open — npm lifecycle scripts, `.envrc`, devcontainer/VS Code auto-run, `curl … \| sh` one-liners. |

### Tests

```sh
./test/smoketest_clone_scan.sh
```
