# omp -- runbook

omp (oh-my-pi) is a coding agent. On the laptop it runs through clai like
the other agents: `macos/dot.alias` has `alias omp='clai omp'`, so every
launch runs the hooks in `clai.d/omp/pre/` first. Do not wrap or shadow
the `omp` command itself; a wrapper named `omp` on PATH loops through clai
back into itself.

- Hooks: `clai.d/omp/pre/05-provision`, `10-disable-mcp`,
  `30-cf-workers-ai`, `40-model-roles`. Each file's header is the detail;
  this page is how to run and fix it.
- Seed script: `clai.d/omp/seed-gateway-key.zsh`.
- Tests: `test/smoketest_clai_omp_cf.sh` and
  `test/smoketest_clai_omp_roles.sh`, hermetic, in `dist-ci.yml`'s
  smoketests job.
- The gateway itself is tds-internal `ops/terraform/ai-gateway`. Item
  names and ids are there, not here: this repo is public.

---

## Which model does what

omp picks a model by role. Its bundled agents name a role: `scout` and
`sonic` use `smol`, `task` uses `task`, `reviewer` uses `slow`.
`40-model-roles` sets the roles at every launch:

| Roles | Model |
|---|---|
| `default` `slow` `plan` `advisor` | GitHub Copilot (`github-copilot/claude-sonnet-5.5`) when omp holds a Copilot login; otherwise Kimi K2.7 Code on the AI Gateway |
| `smol` `task` `commit` `tiny` `memory` `widget` | `ollama/omp-coder:latest`, a local model in the everyday Ollama (port 11434, never the LMDE gateway) |

- The Copilot test is `omp token github-copilot` succeeding. Log in or out
  and the roles move at the next launch.
- On a usage limit, a model falls back down the chain Copilot -> Kimi ->
  local. Any other error (a missing credential, for one) is retried on the
  same model and then shown, never hidden behind a cheaper model
  (`retry.fallbackOn: usage-limit`, Issue#755).
- Without the local model (not pulled, or Ollama not installed) every role
  uses the strong model. When the Ollama server does not answer, the hook
  leaves the roles as they are.
- A role you change by hand stays until the hook's wanted roles change
  (Copilot login, the local model appearing or going away, or a change to
  the hook). `CLAI_OMP_REFRESH=1 omp` applies the hook's roles again.

## Setup on a laptop (once)

- Pull the local model: `ollama pull qwen3-coder:30b`. The hook builds
  `omp-coder` from it (64K context) at the next launch.
- In 1Password, tag omp's AI Gateway key item `omp-ai-gateway-key`, and the
  gateway routing item (the one with the `gateway` section holding
  `base_url` and `gateway_id`) `ai-gateway-routing`. Exactly one item may
  carry each tag.
- Seed the key, in a terminal (it refuses without one):

  ```
  zsh clai.d/omp/seed-gateway-key.zsh
  ```

  It reads the key once (approve the 1Password prompt), writes it to the
  login Keychain (service `tds.omp.cf-gateway-key`, account `omp`), and
  rewrites `~/.omp/agent/models.yml` to read it with `security`. From then
  on, a launch does not ask 1Password.
- Optional, for Copilot: `omp login github-copilot`. Without it omp uses
  Kimi.

## Routine work

- **Use Copilot:** `omp login github-copilot`, then relaunch.
- **Stop using Copilot:** `/logout` inside omp, or launch with
  `CLAI_OMP_NO_COPILOT=1 omp` for one session.
- **Rotate the gateway key:** rotate it in tds-internal, update the 1Password
  item, then run the seed script again.
- **Update omp:** omp is installed with bun, so `omp update` refuses
  ("the resolved foreign symlink target is a shebang script"). Never use
  the `curl ... | sh` installer it suggests. Update through bun:
  `bun add -g @oh-my-pi/pi-coding-agent@latest`.
- **See what is set:** `omp config get modelRoles --json`,
  `omp config get retry.fallbackChains --json`, and
  `grep apiKey ~/.omp/agent/models.yml`.

## When it goes wrong

- **1Password prompts at launch or every 30 s.** The key is not in the
  Keychain: `models.yml`'s `apiKey` still says `!op read`. Run the seed
  script. (omp runs a `!command` key once per process and again 30 s
  after a failure, so an unanswered prompt comes back.)
- **"no credential for cf-workers-ai".** The Keychain item is missing or
  the Keychain is locked. Check with
  `security find-generic-password -s tds.omp.cf-gateway-key -a omp`
  (no `-w`: it shows the item, not the key). Seed again if missing.
- **The status line says Kimi or Copilot, but the work is poor.** Look for
  `Fallback:` warnings in the session: a usage limit moved the turn to a
  cheaper model. `retry.fallbackOn` must be `usage-limit`; with `any`, a
  credential failure falls back silently (Issue#755).
- **`~/.omp/agent/models.yml` is gone** (seen on 2026-11-08, after an
  `omp login`; the cause is not found). Relaunch: `30-cf-workers-ai`
  rebuilds it from the Keychain key and the routing kept in
  `~/.omp/agent/.tds-cf-routing`, without 1Password.
- **"want exactly one 1Password item tagged ..."** A tag is on no item or
  on several. Fix the tags.
- **A new machine.** `30-cf-workers-ai` needs 1Password once for the
  routing, then never again unless `CLAI_OMP_REFRESH=1`.

## Settings the hooks read

| Variable | Effect |
|---|---|
| `CLAI_OMP_REFRESH=1` | Rewrite `models.yml` (routing read from 1Password again) and apply the roles again |
| `CLAI_OMP_NO_COPILOT=1` | Keep the strong roles on Kimi even with a Copilot login |
| `CLAI_OMP_COPILOT_MODEL` | The Copilot model for the strong roles (default `github-copilot/claude-sonnet-5.5`) |
| `CLAI_OMP_CF_KEY_REF` | An `op://` key reference to use before the Keychain is seeded |
| `CLAI_OMP_CF_OP_ITEM` | The routing item's `op://` reference, instead of the tag |
| `CLAI_OMP_LOCAL_BASE`, `CLAI_OMP_LOCAL_MODEL`, `CLAI_OMP_LOCAL_CTX` | The local model's base, name and context size |
