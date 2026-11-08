# omp -- runbook

omp (oh-my-pi) is one of the fleet's coding agents. It launches as
`clai omp` (the `omp` alias), and its model configuration is written by
the clai pre-hooks in `clai.d/omp/pre/` at every launch. Since tds-utils
PR#759 and PR#760 (2026-11-08) it runs on the owner's GitHub Copilot
subscription alone: no Cloudflare AI Gateway, no 1Password at launch, no
local inference.

- Hooks: `clai.d/omp/pre/` (`05-provision`, `10-disable-mcp`,
  `30-cf-workers-ai`, `40-model-roles`).
- Tests: `test/smoketest_clai_omp_roles.sh`,
  `test/smoketest_clai_omp_cf_gateway.sh` (hermetic; both run in
  `dist-ci`).
- What is live is the `release` worktree (`AGENT.md`, The Release
  Worktree): a hook change on `master` reaches the machine at the next
  `bin/tds-release`.

---

## Which model does what

`40-model-roles` sets omp's roles. omp's bundled agents name a role, not
a model.

| roles | default model | override |
|---|---|---|
| `default` | `github-copilot/kimi-k3` | `CLAI_OMP_STRONG_MODEL` |
| `slow`, `plan`, `advisor` | `github-copilot/claude-opus-5.5` | `CLAI_OMP_DEEP_MODEL` |
| `smol`, `task`, `commit`, `tiny`, `memory`, `widget` | `github-copilot/claude-haiku-5.5` | `CLAI_OMP_BULK_MODEL` |

The hook also puts omp's local providers (`ollama`, `llama.cpp`,
`lm-studio`, `apple`) in `disabledProviders` and removes every fallback
chain to the gateway or to the local model. `retry.fallbackOn` is
`usage-limit`, and no chain is left, so a Copilot usage limit is shown,
not routed around.

**A listed model is not a served model.** `omp models github-copilot`
prints Copilot's catalog, and Copilot refuses some of it to omp's
integration id (`copilot-chat`): `kimi-k2.7-code`, `gpt-5.5` and
`gpt-5.4-mini` answer `400 model_not_available_for_integrator`. Before
making a model a role's default, prove it:

```
command omp -p --no-session --model github-copilot/<model> "Reply with the single word ok."
```

## Hand changes and the stamp

The hook writes only when what it wants differs from what it last wrote
(`~/.omp/agent/.tds-model-roles`). A role you change by hand stays
changed until the hook itself changes; `CLAI_OMP_REFRESH=1 omp ...`
reapplies the hook's values.

**Use the bare binary for config commands.** `omp` is an alias for
`clai omp`, so `omp config set ...` typed at a prompt runs the pre-hooks
first; a hook that owns the key reapplies it before your command runs,
and the setting looks impossible to change. Read or set config through
`command omp config ...` (or `~/.local/bin/omp`), then expect a hook that
owns the key to take it back at the next launch unless the stamp says it
was a hand change.

## The Cloudflare gateway, opt-in

`30-cf-workers-ai` writes the `cf-workers-ai` provider (Kimi on Workers
AI through the personal AI Gateway) into `~/.omp/agent/models.yml` only
with `CLAI_OMP_CF_GATEWAY=1`; opting in also wants
`CLAI_OMP_STRONG_MODEL=cf-workers-ai/@cf/moonshotai/kimi-k2.7-code`.
Without it the hook calls no `op`, writes nothing, and removes the
`models.yml` it wrote earlier (only a file carrying its marker line); a
hand-written `models.yml` is left alone.

## Routine work

- Log in: `omp login github-copilot`. Check: `command omp token
  github-copilot >/dev/null && echo ok`. Usage: `omp usage`.
- Change a default for this machine: export the override in the shell
  profile, or edit the hook by PR (the clai skill: an agent's
  configuration is clai's, never a hand edit in `$HOME`).
- Install and update: tds-utils Issue#743 (omp is installed by hand
  today; nothing provisions it).

## Troubleshooting

- **Roles come back after you set them.** You set them through the alias
  (above), or the hook changed and its stamp no longer matched. Set them
  through the bare binary, or change the hook.
- **`400 model_not_available_for_integrator`.** Copilot does not serve
  that model to omp. Pick one that answers the probe above.
- **`cf-workers-ai` is still listed, or 1Password prompts at launch.**
  A `models.yml` with the hook's marker line survived: run
  `command omp` once through `clai omp` (the hook removes it), or delete
  the file. A `models.yml` without the marker is yours.
- **`omp -p ... | tail` does not return after the answer.** omp exits
  (`Session exit recorded` in `~/.omp/logs/`), but a child keeps stdout
  open. Read the answer from the log or avoid the pipe.
