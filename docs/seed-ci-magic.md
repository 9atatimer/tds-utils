# seed-ci-magic -- ci.magic adoption across one owner's repositories

`bin/seed-ci-magic` reports and seeds the two things a repository owned by
a personal account needs before ci.magic (the fleet's LLM-judged PR
reviewer, `Nine-At-A-Time-Media/template-tools/packages/naatm-ci-magic`)
can run on it. Built for issue #345; discovery redone for issue #348.
Fleet context: template-tools `docs/ops/ci-magic/PLAYBOOK.ACTION-MIRROR.md`
(the mirror, its PAT), tds-internal `docs/runbook.ci-magic.md` (the
credentials), and the gates skill's "ci.magic (rung 3)" section.

## The two halves it covers

- **The `uses:` reference.** template-tools is private with Actions
  access `organization`, so its action resolves only from repositories in
  that org. A repository under `9atatimer` references the private mirror
  `9atatimer/ci-magic@main` instead (Actions access `user`). The tool
  classifies each consumer's reference as `mirror` (resolves), `org-path`
  (the template-tools path, dies at "Set up job"), or `other`.
- **The credential.** `CI_MAGIC_OP_SA_TOKEN`, a 1Password service-account
  token that opens the CI-Magic vault. An org can hold it once as an org
  secret; a personal account has no such tier, so it is a per-repository
  secret. Without it the action resolves and posts "skipped: missing
  credential" -- a green skip, not a review.

## Commands

```
seed-ci-magic [-o OWNER] [-s SECRET] [-r OPREF] [-n] status
seed-ci-magic [-o OWNER] [-s SECRET] [-r OPREF] [-n] seed [OWNER/REPO ...]
```

- `status` -- one line per repository of the owner that carries
  `.github/workflows/ci-magic.yml`: `USES` (mirror / org-path / other),
  `SECRET` (when it was last set, or `-`), `LAST-RUN` (conclusion and
  time of the newest ci.magic run). Exit 0 only when every consumer is
  on the mirror and seeded; 1 when one is not; 2 when that could not be
  determined (a listing or lookup failed for a reason other than 404, shown
  as `error` in the column). The exit code is safe to gate on.
- `seed` -- sets the secret on every consumer, or on the repositories
  named, reading the value from 1Password through one pipe; the value is
  never a variable, argument, or line of output. Idempotent, so it is
  also the re-seed after a rotation. `-n` prints the plan and reads and
  sets nothing. `seed` refuses to act on an incomplete consumer set: if
  discovery or any lookup fails, nothing is seeded and it exits 2.
- Defaults: owner `9atatimer`, secret `CI_MAGIC_OP_SA_TOKEN`, op reference
  the CI-Magic service account recorded in tds-internal's credential
  registry ("ci.magic reviewer"). `-o`, `-s`, `-r` override.

Needs `gh` authenticated as an account that can read the owner's
repositories and their Actions secrets metadata, and, for `seed`, `op`
with 1Password unlocked.

## How it finds consumers, and why not code search

Discovery is `gh repo list <owner> --limit 1000 --no-archived`, then one
contents lookup per repository for the workflow file. That is ~140 lookups
and about 80 seconds for the 9atatimer account, and it is deliberate.

The first version used GitHub code search (`user:<owner>
path:.github/workflows ci-magic`). Code search is an eventually-consistent
index, not an inventory: minutes after one consumer's workflow changed,
the search reported `total_count` 4 and returned 3 items, silently
dropping that consumer from `status` and from bulk `seed` (issue #348). A
candidate set with a silent hole makes the exit code a lie, and a tool
whose job is "is everything seeded" cannot be built on it. The smoke
test's fake `gh` refuses code search outright, so the suite cannot go
green on a return to it.

If the 80 seconds ever matter: parallel lookups, or a `pushed_at` cutoff,
are the levers. Search is not.

## Failure semantics

A 404 on the workflow file means "not a consumer" and the repository is
not listed. Any other failure (auth, rate limit, outage) on the listing,
the workflow lookup, or the secret lookup is reported and turns the exit
code to 2, because "could not tell" must never read as "ready" or as "not
a consumer". These came out of the Codex review on PR #346; the cases are
in `test/smoketest_seed_ci_magic.sh`.

## Test

`test/smoketest_seed_ci_magic.sh`, hermetic: fake `gh` and `op` on `PATH`
backed by a fixture directory, every write recorded to a log, and an
assertion that the token never appears in the tool's output. Wired into
`dist-ci.yml`'s smoketests job.

## When a new repository is created under 9atatimer

Its ci.magic workflow must reference the mirror (template-base still seeds
the org path -- Nine-At-A-Time-Media/template-base Issue#92) and it must
be seeded. `seed-ci-magic status` says which is missing; `seed-ci-magic
seed` fixes the second. The terraform form of seeding is tds-internal
Issue#114.
