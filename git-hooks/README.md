# git-hooks

Global git hooks for this environment.

## `template/hooks/post-checkout` — clone-time security audit

Installed via a global hook template (`init.templateDir`), this hook fires once
after every `git clone` and runs `bin/clone-audit` against the new worktree to
catch **coding-agent poisoning** and auto-execution hazards *before* you run any
tooling in the repo.

Git has no post-clone hook; `post-checkout` is the mechanism (it runs after a
clone's initial checkout, and template hooks are never transferred from the
remote). Full rationale, threat model, install, and clone-variant behavior:

→ **[docs/clone-audit.md](../docs/clone-audit.md)**

Quick start:

```sh
bin/install-git-hook-templates     # wire it up (computes absolute paths)
clone-audit path/to/repo           # run the scanner by hand anytime
./test/smoketest_clone_audit.sh    # tests
```

## `pre-push` — DONOTSUBMIT guard

Blocks a push if `DONOTSUBMIT` appears anywhere in `HEAD`. Per-repo; not part of
the global template (kept separate so it doesn't auto-install into every clone).
