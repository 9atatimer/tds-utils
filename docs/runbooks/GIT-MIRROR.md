# Git Mirror (git-remote-s3) Install Runbook

`git-remote-s3` is the remote helper that lets a `git push` to `origin`
also mirror to S3/R2 via a secondary `s3://` push URL on the same remote.
See `naatm-git-mirror` in `template-tools/` for the org-level enrollment
flow; this runbook is just about getting the **helper binary** installed
correctly on a workstation.

## TL;DR -- install it the right way

```sh
uv tool install git-remote-s3
which git-remote-s3   # must resolve to ~/.local/bin/git-remote-s3
```

That is the entire install. The shim lives in `~/.local/bin/` and points
at a self-contained uv-managed venv under
`~/.local/share/uv/tools/git-remote-s3/`. It is **user-global** -- the
same binary services every repo across `~/workplace/`, with no per-repo
coupling.

PATH sanity check: `~/.local/bin` must come **before** `~/.pyenv/shims`
in `$PATH`. Verify with:

```sh
echo "$PATH" | tr ':' '\n' | grep -nE '(pyenv|local/bin)'
```

## How to recognize you have the wrong install

Failure signature on `git push`:

```
pyenv: version `3.11.5' is not installed (set by /path/to/repo/.python-version)
fatal: remote helper 's3' aborted session
```

The GitHub push itself succeeds (assuming `origin` has both URLs); only
the s3:// secondary push fails. Diagnostic:

```sh
which git-remote-s3
# Wrong: /Users/<you>/.pyenv/shims/git-remote-s3   <-- pyenv shim
# Right: /Users/<you>/.local/bin/git-remote-s3     <-- uv tool shim
```

## Repair recipe (migrating from a bad pip install)

If `git-remote-s3` was previously installed via `pip install` into a
pyenv-managed Python (the wrong way), do this once:

```sh
# 1. Find which pyenv Python has it
pyenv whence git-remote-s3
# -> prints e.g. "3.12.4"

# 2. Confirm package location (sanity check)
~/.pyenv/versions/<version>/bin/pip show git-remote-s3

# 3. Uninstall from that pyenv Python and rehash
~/.pyenv/versions/<version>/bin/pip uninstall -y git-remote-s3
pyenv rehash

# 4. Install the right way
uv tool install git-remote-s3

# 5. Verify the shim now resolves to ~/.local/bin/
which git-remote-s3
```

After this, `git push` from any enrolled repo should succeed both to
GitHub and to the s3:// mirror URL.

## Why pyenv shims break this (the "why" so future-you trusts the fix)

A `pip install` inside a pyenv-managed Python drops a shim at
`~/.pyenv/shims/<tool>`. That shim is **not** a copy of the binary --
it is a small bash script that, on every invocation:

1. Walks up from `cwd` looking for a `.python-version` file
2. Reads the version from that file (or `$PYENV_VERSION`, or
   `~/.pyenv/version`)
3. Re-dispatches the call through `pyenv exec <tool>` using the
   resolved version

The consequence: a "globally installed" tool is actually
**version-dispatched per directory**. If you `cd` into a repo whose
`.python-version` pins a Python that pyenv does not have installed,
the shim aborts before the tool ever runs. Hence the
`remote helper 's3' aborted session` error -- pyenv refused to
dispatch, git saw the helper exit non-zero.

`uv tool install` sidesteps this entirely. It creates one isolated
venv per tool with its own pinned Python and drops a shim at
`~/.local/bin/<tool>` that is **hard-coded to that venv**. No directory
lookups, no `.python-version` reading, no collision with project
hermetic state. This is the textbook reason the Python ecosystem moved
from "pip install in pyenv" to `pipx` / `uv tool install` for CLI
utilities.

## Related

- `~/workplace/naatm/template-tools/packages/naatm-git-mirror/` --
  the enrollment scripts that add the `s3://` push URL to a repo's
  `origin` and configure the pre-push hook
- `~/workplace/naatm/template-tools/docs/design/DESIGN.S3GIT.md` --
  the design doc that motivated the S3/R2 mirror as a GitHub-outage
  fallback
