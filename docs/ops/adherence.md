# Adherence in tds-utils: this repository is gated by its own engine

Moved from tds-utils `AGENT.md`. Read it before you run `bin/adhere` locally or answer an adherence verdict on a PR here.

`adherence.toml` declares `adherence/` by layer; `adherence-judge` in
`dist-ci.yml` judges every change in its scope (`adherence/`,
`adherence.toml` and any directory's `*/adherence.toml`, the two
records, the radar and the gate files, per `changed-scopes.sh`), except
a fork's PR, in the `ci` stage, and is in `gate`'s `needs`, so a
`lowered` change cannot land
(`docs/design/DESIGN.ARCH-ADHERENCE.md`,
`docs/design/ARCHITECTURE.ARCH-ADHERENCE.md`; the rulings log is
Issue#590). Two things to know before you measure locally:

- `bin/adhere judge` on a laptop reads no reviews: outside the `ci` stage
  the reviews port answers Unknown, so the newest landed revision of each
  `adherence.toml` stands as that file's declaration in force, approved or
  not, and the files in force are read as one (the governing
  declarations). To see what CI sees -- the newest landing a code owner
  approved or merged, read from
  GitHub -- run `GITHUB_REPOSITORY=9atatimer/tds-utils
  GITHUB_BASE_REF=master GITHUB_TOKEN=... bin/adhere --stage ci judge
  --base <sha> --head <sha>`; in the `ci` stage without those, every
  landing reads "reviews cannot be read" and the head's own declaration
  counts only as widening (G9).
- A judged check needs a judge. The hosted judge is bound in CI since
  2026-11-07 (tds-utils PR#722): `dist-ci.yml` passes
  `ADHERENCE_OP_SA_TOKEN`, and `adherence.yml` finds the judge's item by
  tag. A judged finding can lower a change there, as a rule finding can.
  On the laptop the judge is the door (`DECIDE_URL`); without it the
  judged checks are coverage, and a change that touches a unit they read
  is `inconclusive` at best, which exits 0 (Q10). `lowered` and `not run`
  are what fail.
- `Covered` lowers the verdict for every unit a change creates outside the
  declaration in force, and a change's own widening of `adherence.toml`
  counts only for PATHS it creates: a function added to a file that
  existed at the base is "not judged under for this change; it takes
  effect from the next change", so a PR cannot clear it alone. Declare
  the file first, in its own PR (PR#698 is the shape), then merge master
  into the PR that adds the function: the judge reads the declaration in
  force from the history of the merge-base, so the branch has to contain
  the declaring landing. Issue#699 asks whether the engine should key the
  widening on units instead.
- The judge fetches the engine (`bin/adhere`, `adherence/`) at the PR
  head, not at master. A branch cut before an engine change on master
  runs the old engine against the new workflow and dies on an unknown
  option (`No such option '--stage'`, PR#676, 2026-11-06). Merge master
  into the branch; nothing on the branch is wrong.
- A new application function needs a row in the architecture record's
  Use-case surface (its signature, or at least its name), or Public
  surface flags every test that calls it: the check reads the use cases
  from that section, not from the module map. PR#708 hit it when
  `check_declarations` had no row.
