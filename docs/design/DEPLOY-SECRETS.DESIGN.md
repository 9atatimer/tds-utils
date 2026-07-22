# Deployment Secrets Convention (GADMIN_VAULT)

> **Status:** DRAFT
> **Date:** 2026-07-22
> **Authors:** Todd Stumpf, Claude
> **Depends on:** none

---

## Overview

Deployment credentials (Cloudflare, Supabase, other SaaS API tokens) are today
reached through ad-hoc, per-repo 1Password references and inconsistent GitHub
secret names. This design defines a single convention: one env-named vault
(`GADMIN_VAULT`), one env-named service-account token that opens it, and a
mechanical `op://` naming scheme so the SAME workflow template and the SAME
laptop command resolve a repo's deploy credentials with the vault name as the
only per-repo knob.

---

## Motivation (the mess this replaces)

The current handbook-publish workflows reach their deploy credential with:

```yaml
env:
  OP_SERVICE_ACCOUNT_TOKEN: ${{ secrets.CI_MAGIC_OP_SA_TOKEN || secrets.OP_SERVICE_ACCOUNT_TOKEN }}
  CLOUDFLARE_API_TOKEN: op://<vault>/Cloudflare Handbook Publisher/credential
```

Three problems:

1. **A review-scoped secret is reused for deploy.** `CI_MAGIC_OP_SA_TOKEN`
   names a service account provisioned for the ci.magic PR reviewer (scoped to
   the CI-Magic vault). Using it as the primary deploy token either forces that
   SA to be over-scoped onto the deploy vault, or it silently never resolves and
   the `||` fallback carries every real deploy. Either way the name lies about
   what the token is for.
2. **The `||` fallback is dead weight.** GitHub already falls a repo secret
   through to an org secret of the same name; the explicit `||` chain
   reimplements that badly and hides which token actually fired.
3. **The `op://` path is hardcoded per repo.** `op://<vault>/Cloudflare
   Handbook Publisher/credential` cannot be lifted into a shared template --
   every repo would fork the template to edit that string.

---

## Goals

1. **One vault knob per repo** -- a workflow/template resolves deploy
   credentials knowing only `GADMIN_VAULT`; nothing else in the credential path
   varies by repo.
2. **One token name, everywhere** -- the SA token lives under a single secret
   name at rest (`GADMIN_OP_SA_TOKEN`), sourced identically on a laptop
   (direnv) and in CI (repo secret, falling through to org secret).
3. **Mechanical references** -- given the ENV name a deploy step needs, the
   `op://` reference is computable, never hand-authored per repo.
4. **No cross-purpose token reuse** -- the deploy token is distinct from the
   ci.magic review token and any personal token; its scope is exactly the
   deploy vault, read-only.
5. **Same command on laptop and CI** -- one `gadmin` entry point hydrates the
   environment from the vault in both contexts, so there is one code path to
   test.

---

## Non-Goals

- **git-crypt.** The `deploy-dev`/`deploy-prod` git-crypt (GPG) path solves a
  different problem -- decrypting repo-embedded files at rest -- and is left
  entirely alone by this design. `GADMIN_VAULT` governs only live op-vault
  credentials pulled at deploy time.
- **Provisioning the vault or the SA.** This doc defines the contract a deploy
  consumes; creating vaults, minting service accounts, and populating items are
  operator actions, not covered here.
- **Owning the repo-specific workflows.** Repo workflows are customized and
  installed at the repo level. `template-base` carries reference examples only;
  they are not published from `template-tools`.
- **Rotating secrets.** Rotation cadence and mechanism are out of scope.

---

## Architecture Overview

```
   Laptop (.envrc / direnv)            GitHub Actions
   +-------------------------+         +-----------------------------+
   | GADMIN_VAULT=<vault>    |         | GADMIN_VAULT (repo var)     |
   | GADMIN_OP_SA_TOKEN=...   |         | secrets.GADMIN_OP_SA_TOKEN  |
   +-----------+-------------+         +--------------+--------------+
               |                                      |
               |            both export               |
               v                                      v
        +--------------------------------------------------------+
        |  gadmin deploy                                          |
        |    maps GADMIN_OP_SA_TOKEN -> OP_SERVICE_ACCOUNT_TOKEN, |
        |    then op run --env-file, vault = GADMIN_VAULT         |
        +----------------------------+---------------------------+
                                     |
                    resolves op://$GADMIN_VAULT/<ENVVAR>/credential
                                     |
                                     v
                    +--------------------------------+
                    |  deploy step (wrangler, etc.)  |
                    |  reads CLOUDFLARE_API_TOKEN,... |
                    +--------------------------------+
```

---

## Design

### The two environment variables

| Variable | Role | Laptop source | CI source |
|----------|------|---------------|-----------|
| `GADMIN_VAULT` | Names the 1Password vault holding this repo's deploy creds. | `.envrc` (direnv) | repo-level Actions **variable** (`vars.GADMIN_VAULT`), or a literal in the workflow |
| `GADMIN_OP_SA_TOKEN` | The service-account token that opens `GADMIN_VAULT`, read-only. | `.envrc` (direnv) | `secrets.GADMIN_OP_SA_TOKEN` (repo secret, falling through to org secret) |

`GADMIN_OP_SA_TOKEN` is the name at rest **everywhere** -- laptop `.envrc` and
CI both export exactly that. `op` and `1password/load-secrets-action` require
the token under the fixed name `OP_SERVICE_ACCOUNT_TOKEN`, so the
`GADMIN_OP_SA_TOKEN -> OP_SERVICE_ACCOUNT_TOKEN` mapping is done in exactly one
place: inside `gadmin deploy`, immediately before it invokes `op`. No caller --
laptop or workflow -- sets `OP_SERVICE_ACCOUNT_TOKEN` itself, so the at-rest
name stays the single source of truth (Goal 2).

### The op:// naming convention

Every deploy credential is stored as one 1Password item in `GADMIN_VAULT`:

- **Item title** == the environment variable the deploy step expects
  (e.g. `CLOUDFLARE_API_TOKEN`, `SUPABASE_SERVICE_ROLE_KEY`).
- **Field** == `credential` (item type: API Credential, or Password with the
  secret in the `credential`/`password` field -- pick one and hold it; this doc
  assumes `credential`).

The reference is therefore always computable:

```
op://$GADMIN_VAULT/<ENVVAR>/credential
```

A deploy declares the ENV names it needs; the resolver expands each. No repo
hand-writes an `op://` path. Example `.env`-style manifest a deploy step feeds
to `op run`:

```
CLOUDFLARE_API_TOKEN=op://GADMIN_VAULT_PLACEHOLDER/CLOUDFLARE_API_TOKEN/credential
```

(where `GADMIN_VAULT_PLACEHOLDER` is substituted from `$GADMIN_VAULT` at run
time -- `op` expands `op://` refs but not shell vars inside the ref, so the
vault segment is templated before `op run` sees it).

### `gadmin deploy` (unified entry point)

One verb hydrates the environment and execs the real deploy, identically on a
laptop and in CI:

```
gadmin deploy -- <deploy-command> [args...]

  1. Require GADMIN_VAULT and GADMIN_OP_SA_TOKEN in env; fail loud if unset.
  2. Map internally: OP_SERVICE_ACCOUNT_TOKEN=$GADMIN_OP_SA_TOKEN (the only
     place this fixed tooling name is set; not exported back to the caller).
  3. Build the op:// manifest for the ENV names the repo declares it needs.
  4. exec: op run --env-file <manifest> -- <deploy-command>
```

Because both contexts set the same two variables, the invocation is byte-for-byte
identical -- the laptop and the Action run the same code path. Where the repo
declares its required ENV names is an implementation detail (a small per-repo
manifest file, e.g. `deploy/secrets.env`); this doc fixes the contract, not the
file's location.

### Reference workflow (lives in template-base as an example)

```yaml
      - name: Deploy
        env:
          GADMIN_VAULT: ${{ vars.GADMIN_VAULT }}
          GADMIN_OP_SA_TOKEN: ${{ secrets.GADMIN_OP_SA_TOKEN }}
        run: gadmin deploy -- npm run deploy:cf
```

No `||` fallback: `secrets.GADMIN_OP_SA_TOKEN` resolves to an org secret of the
same name when no repo secret is defined -- **provided** that org secret exists
and its visibility policy grants this repo access; otherwise the reference is
empty and the deploy must fail closed (see Security Considerations), not fall
back to an ambient credential. The point is that no `||` expression is needed,
not that an org secret is automatically present. No hardcoded `op://` path:
`gadmin deploy` builds it from `GADMIN_VAULT`.

---

## Security Considerations

- **Least privilege.** The SA behind `GADMIN_OP_SA_TOKEN` is granted read-only
  access to exactly one vault (`GADMIN_VAULT`) and never the personal Private
  vault. Blast radius on token compromise is one repo's deploy creds.
- **No cross-purpose reuse.** The deploy token is distinct from the ci.magic
  review token; a leak of one does not expose the other's vault.
- **Fork PRs get nothing -- but only under `pull_request`.** A `pull_request`
  workflow triggered from a fork runs without repo/org secrets, so a deploy
  there cannot resolve its token and must fail closed rather than fall back to
  an ambient credential. This does NOT hold for `pull_request_target`, which
  runs in the base-repo context WITH secrets against fork-authored code -- an
  exfiltration vector. Deploy jobs MUST NOT use `pull_request_target`; gate
  deploys on `push`/`workflow_dispatch`/`release` (or a manual environment
  approval), never on a fork-influenced trigger.
- **No secret in the repo.** `op://` references are committed; resolved values
  never are. `GADMIN_VAULT` is a vault *name*, not a secret, but is still a
  sensitive identifier -- keep concrete vault names in the private repo, not in
  public templates.
- **Token never echoed.** `gadmin deploy` must not print
  `OP_SERVICE_ACCOUNT_TOKEN`; rely on `op run` to inject resolved values into
  the child process env, not into logs.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vault named by env, not baked into templates | `GADMIN_VAULT` | Makes one template serve every repo; the only per-repo knob. |
| Token secret name at rest | `GADMIN_OP_SA_TOKEN` | Binds the token to gadmin's deploy scope; avoids colliding with a personal/other `OP_SERVICE_ACCOUNT_TOKEN` in the same shell. |
| Where the `GADMIN_OP_SA_TOKEN -> OP_SERVICE_ACCOUNT_TOKEN` mapping happens | Inside `gadmin deploy` only | The tooling name is hard-required by `op`; confining the map to `gadmin deploy` keeps `GADMIN_OP_SA_TOKEN` the single at-rest name across laptop and CI (callers never set `OP_SERVICE_ACCOUNT_TOKEN`). |
| Drop the `\|\|` fallback chain | Rely on GH repo->org secret resolution | GitHub already does repo-then-org fallback for a same-named secret; the explicit chain hid which token fired. |
| Item title == ENV var, field == `credential` | Mechanical `op://` refs | Deploy declares ENV names; references compute without per-repo authoring. |
| One vault per repo, SA scoped to it | Isolation | Bounds blast radius; one template still works because only `GADMIN_VAULT` changes. |
| Templates live in template-base, not published | Reference examples only | Repo workflows are customized per repo; template-tools ships packages, not repo workflows. |

---

## Open Questions

1. **Field name -- `credential` vs `password`.** API Credential items expose
   `credential`; Login/Password items expose `password`. Pick one and require
   it, or have `gadmin deploy` try both? Leaning: require `credential` (API
   Credential item type) and document it.
2. **Where the required-ENV manifest lives.** A per-repo `deploy/secrets.env`
   with `op://` refs, versus `gadmin deploy --env NAME1,NAME2`, versus a
   `gadmin.d/` extension declaring them. Leaning: a committed manifest file so
   the required set is reviewable in-repo.
3. **`GADMIN_VAULT` as Actions variable vs literal.** `vars.GADMIN_VAULT` keeps
   the name out of the workflow text (good for the sensitive-identifier stance),
   at the cost of one more thing to configure per repo. Literal-in-workflow is
   simpler but names the vault in a possibly-public file.
4. **Does `gadmin` gain a `deploy` verb, or does this extend `naatm-deploy`?**
   The dispatcher lives in tds-utils; the deploy package lives in
   template-tools. Contract ownership vs implementation locus.

---

## Rejections

- **Keep `CI_MAGIC_OP_SA_TOKEN` as the deploy token** -- names a review-scoped
  SA; reusing it for deploy is exactly the coupling this design removes.
- **Explicit `secrets.A || secrets.B` fallback** -- GitHub's native
  repo->org secret fallback already covers it; the `||` only obscured which
  token resolved.
- **Per-repo hardcoded `op://` paths** -- blocks a shared template; every repo
  would fork the workflow to edit the item string.
- **One shared deploy vault across all repos** -- larger blast radius and
  forces one SA to span every repo's creds; rejected in favor of per-repo
  vaults.
- **Publishing repo workflows from template-tools** -- repo deploys are
  inherently customized; a published one-size workflow would be edited on
  install anyway. template-base examples are the right altitude.

---

## Future Considerations

- **Migration of existing workflows.** Rewriting the handbook-publish and CF
  Worker deploys onto this contract is follow-up work tracked per repo, not part
  of adopting the convention.
- **Non-Cloudflare providers.** Supabase and other SaaS tokens follow the same
  item-title==ENV-name scheme with no change to the contract.
- **Secret rotation tooling.** A `gadmin` verb to rotate a vault item and update
  the repo/org secret in one step could sit on top of this convention later.

---

## Related Documents

- `docs/design/DESIGN.leak-prevention.md` -- secret-handling stance this aligns with.
- `Nine-At-A-Time-Media/template-base` repo, `.github/workflows/` -- where the reference deploy workflow example lands (a different repo, not a path in tds-utils).
