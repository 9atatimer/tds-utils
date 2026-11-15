# Infrastructure and tds-utils

Moved from tds-utils `AGENT.md`.

The fleet's infrastructure-as-code lives in the private infra repo
[tds-internal](https://github.com/9atatimer/tds-internal) under
`ops/terraform/`; its `docs/policy/{INFRASTRUCTURE,TERRAFORM,CREDENTIALS}.md`
are the rules and win over anything here. Load the shared `iac` skill
the moment a task touches a cloud resource or a GitHub secret.

This repo owns no long-lived cloud resource. Two things here look like
infrastructure and are not:

- `ops/terraform/remvllm/` -- a provisioning primitive inside the
  `remvllm` CLI: a TTL'd GPU spot node that `remvllm up` creates and
  `remvllm destroy` (or its watchdog) tears down, state kept per host by
  the tool, credentials read at run time with `op read` and never
  written to disk. It stays here by recorded exception (tds-internal
  `ops/terraform/README.md`, "Modules that live elsewhere"), pending the
  human's ruling in tds-internal `docs/design/DESIGN.infra-centralization.md`.
- `lmde/` -- the local managed developer environment (kind, Caddy,
  Grafana); it runs on the laptop, not in a cloud account.

Secrets this repo's workflows read, names only (registry: tds-internal
`ops/credentials/REGISTRY.md`): `GH_PAT_NAATM_PACKAGES_RO` and the
deprecated `GH_AI_TOOLS_PAT` fallback, both on the Agents secrets
surface, both `read:packages`.

`docs/design/DEPLOY-SECRETS.DESIGN.md` (`GADMIN_VAULT`) is neither
adopted nor rejected; tds-internal `docs/policy/CREDENTIALS.md` lists it
as an open question.
