# Architectural Adherence -- architecture

> **Status:** DRAFT
> **Date:** 2026-10-24 (self-review panel findings folded in the same day)
> **Authors:** Todd Stumpf, Claude
> **Implements:** [DESIGN.ARCH-ADHERENCE.md](./DESIGN.ARCH-ADHERENCE.md) (status: DRAFT; this record was written ahead of the design's approval at the owner's request and is re-read against the design the day it is APPROVED)
> **As-built read:** `docs/arch/ARCHITECTURE.md` as of 2026-10-24: the proxy layer, the Ollama Gateway and OCR on Demand; no as-built exists for `bin/decide`, `chores/` or the dist tools, so their shapes were read from code

---

## Overview

One Python engine, `adherence/`, with one composition root, bound
differently per stage and called by the `adhere` CLI. Language analyzers
behind one port turn a repository into a language-neutral code model; the
domain runs every rule check over that model and emits the questions the
judged checks need; a decision port answers the questions with
probabilities through the fleet's `decide` client; a threshold policy in
the core turns probabilities into findings or abstentions. A change is
judged by measuring its head and its base and comparing the two reports
over the units they share, so the baseline is the base revision's own
score and nothing has to be stored for the ratchet to hold; the owner's
drop tickets and the change's widening come from the two declarations,
and count only with a code owner's approval on the landing PR. Findings
leave as SARIF and as the fleet's ledger records. The engine is measured
by itself.

---

## Component diagram

```
 laptop / agent / cloud            CI (adopting repo)
 +---------------------+           +--------------------------------------+
 | bin/adhere          |           | adherence.yml (reusable workflow)    |
 |  (pre-commit: the   |           |  gate job -> bin/adhere judge        |
 |   rule checks,      |           |  ci-magic-toolkit manifest line ->   |
 |   --staged, under   |           |  bin/adhere measure (for the judge)  |
 |   a deadline)       |           +------------------+-------------------+
 +----------+----------+                              |
            |                                         |
            v                                         v
 +----------------------------------------------------------------------+
 | adherence/  (uv project)                                             |
 |  cli/        entry point: parse, call the use cases, present         |
 |  container   the composition root: binds adapters per stage          |
 |  application load_declaration | measure | judge_change | explain     |
 |              | record_report                                         |
 |  domain      qualities, checks, questions, threshold, score, verdict |
 |  ports       Repository | CodeModel | Complexity | Duplication       |
 |              | Records | Decision | Review | Explanation             |
 |              | ReportStore                                           |
 |  adapters    git | python-ast (+grimp) | ts (dependency-cruiser)     |
 |              | astgrep (py/ts/js/sh) | lizard | jscpd | markdown     |
 |              | decide | no-judge | claude-cli (no tools) | none      |
 |              | github-reviews | no-reviews                           |
 |              | file-store | warehouse | fakes                        |
 +------+-----------+-----------+--------------+--------------+---------+
        |           |           |              |              |
        v           v           v              v              v
   git (base,   analyzers   decide client  adherence-ledger  GitHub
   head, tree,  (subproc,   -> door        (R2, S3 protocol) reviews
   renames)     bounded)    (laptop)       + local file      (ci only)
                            -> hosted (CI) cache
```

Dependencies point inward: `cli -> application -> domain`;
`adapters -> ports -> domain`. No domain or application module imports a
subprocess, a file system call, an environment variable or a vendor name.

---

## Seams

| Axis of change | Seam | Kind | Why it is a seam |
|---|---|---|---|
| Where the repository's files, revisions and renames come from (working tree, staged index, base and head in CI) | `RepositoryPort` | port | Real sources on day one: the laptop's tree, the hook's staged index, CI's revisions; the fake is another |
| Who approved the change, from the code host's reviews | `ReviewPort` | port | `github_reviews` in CI, `no_reviews` (no approvals) on the laptop, in the hook and in the cloud, and a fake on day one; another code host is a further adapter |
| The language, and the analyzer that reads it | `CodeModelPort`, one adapter per language, registered by file extension | port | Python, TypeScript/JavaScript and shell at the MVP; Go and GDScript are later adapters with zero core edits |
| Complexity tooling | `ComplexityPort` | port | lizard today and a fake returning fixed complexity; replaceable without touching duplication |
| Duplication tooling | `DuplicationPort` | port | jscpd today and a fake returning fixed clones; replaceable without touching complexity |
| How design records and the radar are read at a target | `RecordsPort` | port | A markdown adapter over `RepositoryPort` and a fake on day one; the fake returns different records for base and head |
| Who answers a judged question | `DecisionPort` | port | The decide client through the door, the decide client hosted, a local arena later, the `no-judge` adapter and a fake; the decision-models skill's port |
| Who writes an explanation | `ExplanationPort` | port | A generative model with no tools is one of several; `none` is a real adapter and the default |
| Where reports persist and are read back | `ReportStore` | port | A local file cache on the laptop, the warehouse in CI, a fake in tests |
| Each judged question's threshold and abstention band | `ThresholdPolicy` | policy | Retuned from the labelled set per question id without touching the checks; each entry's form follows its question's kind (Mechanism) |
| What counts as a stub, a vendor name, an environment read, a model id, a region marker, per language | `Vocabulary` | policy | Retuned as the fleet's languages and vendors change; the declaration may extend it, never empty it |
| The complexity and duplication ceilings, the judged-check budget, the analyzer bound, the evidence bound, the record statuses that count | `Limits` | parameter set | Tuned values the composition root supplies from the suite's shipped defaults; the as-built holds them |
| What a repository declares: layers, runtimes, records, radar, exemptions, floors, drop tickets | `Declaration` | parameter (a domain value read through `RepositoryPort` at the base, with the head's widening and added tickets) | Per repository, never per run |
| When a bounded run must end | `Deadline` | parameter (an instant the entry point computes) | The hook sets it from the commit-time bound and CI from the job's remaining time; laptop and cloud pass none. It is taken by every method of `RepositoryPort`, `ReviewPort`, `CodeModelPort`, `ComplexityPort`, `DuplicationPort`, `RecordsPort` and `DecisionPort`, and by `ReportStore.get`; not by `ReportStore.put`, which runs after the verdict, nor by `ExplanationPort`, which runs outside judging. Each returns `TimedOut` rather than overrun it. This record calls these the deadline-bound ports |
| How findings are presented (terminal, JSON, SARIF, PR check summary) | presenters in `cli/` | entry-point concern, not a seam | Presentation of one `Report` value; no port, because nothing behind it does I/O the domain depends on |

A judged question's kind, binary, choice or score, is fixed by this record
per question, with its id and options; the design says only that a judged
check receives a probability per allowed answer. Renaming a question's id
or option is a migration of the threshold policy and the labelled set.

---

## Module map

| Unit | Layer | Runtime |
|---|---|---|
| `domain/qualities.py` -- the closed quality set, the check catalog, each check's kind | domain | all |
| `domain/model.py` -- `CodeModel`: `Unit`, `Layer`, `Region`, `ImportEdge`, `Definition`, `Signature`, `Body` (text, stub markers, sleeps), `Reference` (symbol references and string literals), `Call` (function and constructor calls), `Access` (global and environment reads), `Write` (field writes with the owning unit), `Conditional` (with its discriminant), `Member` (fields and methods of a type), `TestCase` (calls and assertions), `Metrics` (per-function complexity, clones) | domain | all |
| `domain/declaration.py` -- `Declaration` parse and validation, exemptions, floors, drop tickets, widening merge, approval counting against the base's CODEOWNERS, the Declared-quality exemption refusal | domain | all |
| `domain/records.py` -- `DesignRecords`: behaviors, domain language, use-case surface, seams; `Radar` | domain | all |
| `domain/checks/hexagonal.py` -- Grep, Arrow, Swap, Change | domain | all |
| `domain/checks/layered.py` -- Trace, Purity (rule part and the does_io question), Wiring, Anatomy; the Two-jobs question | domain | all |
| `domain/checks/ddd.py` -- Language (rule part and question), Anemic (rule part and the rules_elsewhere question), Boundary (rule part and question); the Decision question | domain | all |
| `domain/checks/composable.py` -- Values in and out, No nesting, Helpers take values | domain | all |
| `domain/checks/injectable.py` -- Ports as keywords, No self-wiring, No reach | domain | all |
| `domain/checks/behavior.py` -- Kept test, Public surface, Real assertion; the Then-asserted question | domain | all |
| `domain/checks/complete.py` -- Stub, Complexity, Duplication; the Done and Hand-rolled questions | domain | all |
| `domain/checks/radar.py` -- Dependency, Edge only | domain | all |
| `domain/checks/declared.py` -- Covered (over a `CodeModel` and the created units) and Record kept (over two `DesignRecords`), both change-level; the declaration-edit notices | domain | all |
| `domain/questions.py` -- `Question`, `Schema`, `Decision`; `ThresholdPolicy` applied per question id: finding, pass or abstention | domain | all |
| `domain/score.py` -- per-quality `Score` over covered units; `ComparedScore` over shared and created units; `Coverage` | domain | all |
| `domain/verdict.py` -- two `Report`s and a `Change` to a `Verdict` in the design's order; provenance with renames; floors reached or not; the tickets the head adds, against the base's score | domain | all |
| `domain/finding.py` -- `Finding`, its stable identity, `Evidence` bound; `Notice` | domain | all |
| `domain/report.py` -- `Report`, `Report.not_run`, its identity (suite version, parameters digest, declaration digest, analyzer set, judge availability) | domain | all |
| `application/load.py` -- `load_declaration` | application | all |
| `application/measure.py` -- `measure` | application | all |
| `application/judge.py` -- `judge_change` | application | all |
| `application/explain.py` -- `explain` | application | all |
| `application/record.py` -- `record_report` | application | all |
| `ports/*.py` -- one `Protocol` per seam above | ports | all |
| `adapters/git.py` -- `RepositoryPort` over `git` (tree, staged index, `show <rev>:<path>`, changed paths and hunks, renames); refuses symlinks and paths resolving outside the root | adapters | all |
| `adapters/github_reviews.py` -- `ReviewPort` over the GitHub REST API with the standard library and the job's `GITHUB_TOKEN`: the landing PR's approving reviews, each reviewer, the commit reviewed, and the PR's author | adapters | all |
| `adapters/no_reviews.py` -- `ReviewPort` that returns no approvals | adapters | all |
| `adapters/python_ast.py` -- `CodeModelPort` for Python over the standard library `ast`, import resolution by `grimp` | adapters | all |
| `adapters/ts_depcruise.py` -- `CodeModelPort` for TypeScript/JavaScript: import graph and cycles from `dependency-cruiser`, the rest from `ast-grep` | adapters | all |
| `adapters/astgrep.py` -- shared structural facts for every language (definitions, bodies, references, calls, accesses, writes, conditionals, members, regions, test cases and assertions) from `ast-grep` rule files the adapter owns | adapters | all |
| `adapters/shell_astgrep.py` -- `CodeModelPort` for shell: regions, bodies, dependencies, over `ast-grep` | adapters | all |
| `adapters/lizard.py` -- `ComplexityPort` | adapters | all |
| `adapters/jscpd.py` -- `DuplicationPort` | adapters | all |
| `adapters/markdown_records.py` -- `RecordsPort` over `markdown-it-py`, reading bytes through `RepositoryPort` at the target | adapters | all |
| `adapters/decide.py` -- `DecisionPort` over the `decide` client's record format: the door's address on the laptop, the hosted configuration in CI | adapters | all |
| `adapters/no_judge.py` -- `DecisionPort` that answers every schema with the typed `unavailable` failure | adapters | all |
| `adapters/claude_cli.py` -- `ExplanationPort` over the CLI run in print mode with every tool disallowed; `adapters/no_explainer.py` | adapters | all |
| `adapters/file_store.py`, `adapters/warehouse.py` -- `ReportStore` | adapters | all |
| `adapters/fakes.py` -- an in-memory adapter per port, each deadline-bound one returning `TimedOut` once the deadline has passed, shipped so the composition root is buildable with every port faked | adapters | tests, and Swap's own evidence |
| `container.py` -- the composition root: constructs the concrete adapters and binds them by stage (`laptop`, `hook`, `ci`, `cloud`) and by the declaration's languages; takes an override per port so a test builds it with fakes | composition root | the `adhere` CLI |
| `cli/main.py` -- Click entry: `measure`, `judge`, `explain`, `declaration check`; presenters for terminal, JSON, SARIF, PR summary; computes the `Deadline` for the hook and for CI | entry point | the `adhere` CLI |
| `bin/adhere` -- the launcher that resolves the uv project, as `bin/chores` does | entry point | the laptop |
| `.github/workflows/adherence.yml` -- the reusable workflow: checkout, `bin/adhere judge --base --head`, SARIF upload in its own step, PR check summary | entry point | the `adhere` CLI, `ci` stage |

One composition root per runtime: there is one runtime, the `adhere` CLI,
and `container.py` is its composition root, the one unit that constructs
concrete adapters. `cli/main.py`, `bin/adhere` and the workflow are entry
points that call it and name no adapter; tests name fakes, which are not
concrete adapters. The hook, CI, the agent and the cloud session are
stages of that runtime; the ci-magic toolkit manifest line and the
pre-commit stage both invoke the same CLI.

---

## Use-case surface

| Design behavior | Use case (signature) | Ports |
|---|---|---|
| A repository is measured | `measure(at: Base \| Head, declaration: Declaration \| DeclarationUnreadable, *, repository: RepositoryPort, analyzers: Mapping[Language, CodeModelPort], complexity: ComplexityPort, duplication: DuplicationPort, records: RecordsPort, judge: DecisionPort, parameters: Parameters, deadline: Deadline \| None) -> Report` | RepositoryPort, CodeModelPort (via `analyzers`), ComplexityPort, DuplicationPort, RecordsPort, DecisionPort |
| A domain leak is found | (`measure`; a scenario of Grep) | CodeModelPort |
| An inward arrow holds | (`measure`; Arrow) | CodeModelPort |
| A cycle is found | (`measure`; Arrow) | CodeModelPort |
| A behavior with no home is found | (`measure`; Trace) | CodeModelPort, RecordsPort |
| A behavior with a home passes | (`measure`; Trace) | CodeModelPort, RecordsPort |
| A port in a rule is found | (`measure`; Purity, rule part and question) | CodeModelPort, DecisionPort |
| A second composition root is found | (`measure`; Wiring) | CodeModelPort |
| A missing composition root is a disagreement | (`measure`; Wiring) | CodeModelPort |
| An adapter constructed below the root is found | (`measure`; Wiring) | CodeModelPort |
| A file out of order is found | (`measure`; Anatomy) | CodeModelPort |
| A unit doing two jobs is found | (`measure`; Two-jobs question) | DecisionPort |
| A judged check answers with a confidence | (`measure`; `domain/questions` applies `ThresholdPolicy` by question id and stamps `confidence` on finding, pass and abstention alike) | DecisionPort |
| A port without a fake is found | (`measure`; Swap) | CodeModelPort |
| A named seam is missing | (`measure`; Change) | CodeModelPort, RecordsPort |
| A foreign noun is found | (`measure`; Language, rule part) | CodeModelPort, RecordsPort |
| Two spellings of one concept are found | (`measure`; Language, question) | DecisionPort |
| A hidden policy is found | (`measure`; Decision question) | DecisionPort |
| A foreign write is found | (`measure`; Boundary, rule part) | CodeModelPort |
| A write that breaks an invariant is found | (`measure`; Boundary, question) | DecisionPort |
| An anemic type is found | (`measure`; Anemic, rule part and question) | CodeModelPort, DecisionPort |
| A wire format in a signature is found | (`measure`; Values in and out) | CodeModelPort |
| A nested function is found | (`measure`; No nesting) | CodeModelPort |
| A helper that takes a port is found | (`measure`; Helpers take values) | CodeModelPort |
| A port taken by position is found | (`measure`; Ports as keywords) | CodeModelPort |
| A self-wired use case is found | (`measure`; No self-wiring) | CodeModelPort |
| A reach is found | (`measure`; No reach) | CodeModelPort |
| A behavior with no kept test is found | (`measure`; Kept test) | CodeModelPort, RecordsPort |
| A test that cannot fail is found | (`measure`; Real assertion) | CodeModelPort |
| A test past the surface is found | (`measure`; Public surface) | CodeModelPort |
| A test that skips the Then is found | (`measure`; Then-asserted question) | DecisionPort, RecordsPort |
| A stub is found | (`measure`; Stub) | CodeModelPort |
| An unfinished unit is found | (`measure`; Done question) | DecisionPort |
| A hand-rolled primitive is found | (`measure`; Hand-rolled question) | DecisionPort, RecordsPort |
| A function over the complexity ceiling is found | (`measure`; Complexity) | ComplexityPort |
| A clone over the duplication ceiling is found | (`measure`; Duplication) | DuplicationPort |
| A disallowed dependency is found | (`measure`; Dependency) | CodeModelPort, RecordsPort |
| A radar entry in the core is found | (`measure`; Edge only) | CodeModelPort, RecordsPort |
| An undeclared new unit is found | `judge_change(change: Change, *, repository: RepositoryPort, reviews: ReviewPort, analyzers: Mapping[Language, CodeModelPort], complexity: ComplexityPort, duplication: DuplicationPort, records: RecordsPort, judge: DecisionPort, reports: ReportStore, parameters: Parameters, deadline: Deadline \| None) -> Report` (Covered over `change.created`) | RepositoryPort, ReviewPort, CodeModelPort (via `analyzers`), ComplexityPort, DuplicationPort, RecordsPort, DecisionPort, ReportStore |
| A widening is honored | (`judge_change`; `load_declaration` at base and at head; with a counted approval the merged `Declaration` is passed to `measure` for the head) | RepositoryPort, ReviewPort |
| A narrowed record is found | (`judge_change`; Record kept over `RecordsPort.records` at `change.base` and at `change.head`) | RecordsPort |
| A record is read with its code | (`measure`; `RecordsPort.records(at, declaration, deadline)`) | RecordsPort |
| A one-file tool is measured | (`measure`; regions from the declaration, by marker or by lines) | CodeModelPort |
| An uncovered language is reported | (`measure`; coverage) | RepositoryPort |
| A missing design record is reported | (`measure`; coverage) | RecordsPort |
| A missing record on both sides is not inconclusive | (`judge_change`; coverage equal on both sides is not lost coverage) | RecordsPort |
| An untraceable row is a finding against the record | (`measure`; Trace) | RecordsPort |
| An undeclared repository is measured | (`load_declaration` returns `Declaration.none`; `measure` with it) | RepositoryPort |
| An unreadable declaration is not run | `load_declaration(at: Base \| Head, *, repository: RepositoryPort, deadline: Deadline \| None) -> Declaration \| DeclarationUnreadable`; `measure`, given `DeclarationUnreadable`, returns `Report.not_run` and is its one owner; the CLI and `judge_change` pass the result through | RepositoryPort |
| An unreadable edit is a notice | (`judge_change`; `load_declaration` at the head returning `DeclarationUnreadable` becomes a `Notice`, and the base's declaration alone is used) | RepositoryPort |
| An unapproved declaration is not in force | (`judge_change`; the base's declaration is in force as landed. `ReviewPort.approvals(change, deadline)` returns the landing PR's approving reviews, each with its reviewer and the commit reviewed, and the PR's author. `domain/declaration` counts an approval only if its reviewer is a code owner of `adherence.toml` by the base's CODEOWNERS, read through `RepositoryPort`, and its commit's `adherence.toml` bytes equal the head's, so approve-then-push does not pass. A CODEOWNERS team entry counts as no owner and is a `Notice`. Without a counted approval the head's widening and added tickets are ignored and the edit is a `Notice`. `no_reviews`, bound in `laptop`, `hook` and `cloud`, returns no approvals) | ReviewPort, RepositoryPort |
| An author's approval is refused | (`judge_change`; `domain/declaration` refuses an approval whose reviewer is the PR's author as `ReviewPort` reports it, never the commit's git author, and the report says why) | ReviewPort |
| A change that raises is raised | (`judge_change`; `domain/verdict`) | RepositoryPort, CodeModelPort, ReportStore |
| A change that lowers is lowered | (`judge_change`; `domain/verdict`) | RepositoryPort, CodeModelPort, ReportStore |
| A floor holds | (`judge_change`; floors from the base `Declaration`, reached at the base) | RepositoryPort, ReportStore |
| An unreached floor does not bind | (`judge_change`; the floor becomes a notice) | RepositoryPort, ReportStore |
| An introduced flaw lowers | (`judge_change`; provenance) | RepositoryPort, CodeModelPort |
| An existing flaw does not block | (`judge_change`; provenance) | RepositoryPort, CodeModelPort |
| A break on an untouched unit is introduced | (`judge_change`; provenance is absence from the base report, by identity) | CodeModelPort, ReportStore |
| A rename introduces nothing | (`judge_change`; `RepositoryPort.changed` reports renames, identity follows them) | RepositoryPort |
| Deleting clean code moves nothing | (`judge_change`; `ComparedScore`) | RepositoryPort, CodeModelPort |
| An abstention is inconclusive | (`judge_change`) | DecisionPort |
| An exhausted judged-check budget is inconclusive | (`measure`; questions past `Limits.judged_budget` become `Coverage`; `judge_change` reads coverage on touched units as inconclusive) | DecisionPort |
| A rule check that errors is coverage | (`measure`; a check function's exception is caught once at the check boundary and becomes `Coverage` naming check, unit and error) | none |
| An unreadable file is coverage | (`measure`; `RepositoryPort.read` failure becomes `Coverage` for that unit) | RepositoryPort |
| CI out of time is coverage | (`judge_change` with the `ci` stage's `deadline` set from the job's remaining time; unfinished checks are `Coverage`) | RepositoryPort, ReviewPort, CodeModelPort, ComplexityPort, DuplicationPort, RecordsPort, DecisionPort, ReportStore |
| An unavailable judge is inconclusive, never raised | (`judge_change`; judged units absent at the head leave `ComparedScore` on both sides) | DecisionPort |
| A suite that cannot run says so | (`measure` returns `Report.not_run`; `judge_change` carries it to the verdict) | RepositoryPort |
| The baseline ratchets up | (`judge_change`; the baseline is the base revision's `Report`) | ReportStore on a comparable hit; on a miss RepositoryPort, CodeModelPort, ComplexityPort, DuplicationPort, RecordsPort, DecisionPort at the base |
| A drop ticket accepts a fall | (`judge_change`; a ticket the head's declaration adds over the base's, with a counted approval, whose `from` is at least the base's score and whose `to` is at most the head's) | RepositoryPort, ReviewPort |
| A drop ticket survives a moving base | (`judge_change`; the ticket names scores and is found by comparing the two declarations, so the base commit is not consulted) | RepositoryPort |
| A drop ticket covers no second fall | (`judge_change`; a ticket already in the base's declaration is spent and honors no fall) | RepositoryPort |
| A drop ticket is shown until regained | (`measure`; a ticket in the declaration whose `from` is not yet regained is a notice; once regained, a removable notice) | RepositoryPort |
| A change cannot narrow its own declaration | (`judge_change`; everything in the head declaration but widening and added tickets is ignored and noticed) | RepositoryPort |
| An exemption carries its reason | (`measure`; `Declaration`) | RepositoryPort |
| An added exemption is inert for its change | (`judge_change`; exemptions from the base declaration only) | RepositoryPort |
| The Declared quality cannot be exempted | (`measure`; `Declaration` validation) | RepositoryPort |
| A report quotes no more than the evidence | (`measure`; `domain/finding` truncates `Evidence` to `Limits.evidence_bound`) | none |
| The same finding everywhere | (`measure`; `Finding.identity` is a digest of quality, check, the unit's symbol and layer, and the normalised evidence, with the path resolved through renames at judging) | none |
| The hook ends within its bound | (`judge_change` with `deadline`, passed into every deadline-bound port call (Seams); each returns `TimedOut` for coverage rather than overrun; `cli/main.py` computes it from the commit-time bound, and the `hook` stage binds `judge` to `no_judge` and `reviews` to `no_reviews`) | RepositoryPort (staged index), ReviewPort, CodeModelPort, ComplexityPort, DuplicationPort, RecordsPort, DecisionPort, ReportStore |
| An explanation changes nothing | `explain(finding: Finding, report: Report, *, repository: RepositoryPort, explainer: ExplanationPort) -> Explanation` | RepositoryPort, ExplanationPort |
| A disagreeing explanation shows both | (`explain`; `Explanation.agrees` is a field the presenter shows) | ExplanationPort |
| The judge is given data | (`measure`; `Schema` is fixed by the domain, the unit is the `State`) | DecisionPort |
| The explainer can act on nothing | (`explain`; `claude_cli` runs the CLI with every tool disallowed and the repository outside its working directory; the port's contract suite asserts the adapter reads no repository file and spawns nothing but the model's own process with those flags; what the model does behind those flags is the CLI's guarantee, named as such) | ExplanationPort |
| Repository code is never run | (`measure`; every adapter reads bytes and spawns only the analyzers, each told its configuration explicitly) | RepositoryPort, CodeModelPort, ComplexityPort, DuplicationPort |
| A report persists | `record_report(report: Report, *, reports: ReportStore) -> Recorded` | ReportStore |
| An unmeasurable base is inconclusive | (`judge_change`; `ReportStore.get(repo, rev, identity, deadline)` with the identity a measurement of the base carries, a report a default-branch run wrote; a miss or a mismatch measures the base again, and a base that still cannot be measured under that identity is `Verdict.inconclusive` naming what differs) | ReportStore |

`Base` and `Head` are the design's: a repository at one revision; a
working tree or a staged index is a `Head`. `Declaration` arrives as a
value: `load_declaration` reads it, and for a change `judge_change` merges
the base's with the head's widening and added tickets before calling
`measure`. `analyzers` is the mapping from each measured `Language` to its
`CodeModelPort` that the composition root built; the use case asks it
which languages are covered and reports the rest as coverage.
`Parameters` bundles `ThresholdPolicy`, `Vocabulary` and `Limits`, the
design's Parameters table as one value. `Deadline` is the instant the
design's commit-time bound, or the CI job's remaining time, becomes for
this run; `None` means unbounded; every deadline-bound port method (Seams)
takes it, and an adapter that cannot finish by it returns `TimedOut`,
which the use case records as coverage. A fake that ignores the deadline
fails the port's contract suite, so a RED test of the bound drives
`measure` with a fake that returns `TimedOut` once the deadline has
passed. Every return is a domain value: `Report` (for a change, with its
verdict, compared scores and provenance), `Explanation`, `Recorded`. The
CLI calls `judge_change` and then `record_report`, in that order, so
writing the report can never touch the verdict; reading a base from
`ReportStore` only spares a measurement of the base (Judging a change).
`Recorded` says whether the write held and, on failure, carries the
`Notice` the presenter shows beside the report.

---

## Mechanism

### Measurement

| Responsibility | Component | Seams crossed |
|---|---|---|
| Read the declaration in force | `load_declaration(at)` -> `RepositoryPort.read(declaration path, at, deadline)` -> `domain/declaration`; for a change, `judge_change` loads base and head and, with a counted approval, merges the head's widening and added tickets into the base's before calling `measure`; `measure` given `DeclarationUnreadable` returns `Report.not_run` | RepositoryPort, ReviewPort |
| Build the code model | one `CodeModelPort` per declared language over the files the declaration covers, each call carrying the `Deadline`; each returns `Unit`s with their `Layer` from the declaration's assignments (directory, file or region), or `TimedOut` | CodeModelPort |
| Measure complexity and duplication | `ComplexityPort.measure(units, deadline)` and `DuplicationPort.measure(units, deadline)` -> `Metrics`, merged into the `CodeModel` | ComplexityPort, DuplicationPort |
| Read the records | `RecordsPort.records(at, declaration, deadline)`, `RecordsPort.radar(at, declaration, deadline)` | RecordsPort |
| Run the rule checks | every target-level check in `domain/checks/*`: `(CodeModel, Declaration, DesignRecords, Radar, Parameters) -> (findings, questions, notices)`; pure; `Metrics` is part of the `CodeModel`. The change-level checks run in `judge_change`: Covered over the head `CodeModel` and `change.created`, Record kept over the base and head `DesignRecords` | none |
| Ask the judged questions | `questions` grouped per unit into one `Schema` each, within `Limits.judged_budget`; `DecisionPort.decide(state, schema, deadline)`; `ThresholdPolicy` applied in `domain/questions` | DecisionPort |
| Score and cover | `domain/score`: per quality, passing units over covered units; everything unread, unanalyzed, unanswered or cut off by the deadline into `Coverage` with its reason | none |
| Report | `Report` value with its identity; presenters shape it | none |

The declaration is TOML at the repository root, `adherence.toml`, read with
the standard library. It names: `[layers]` as path globs and regions per
layer, `[runtimes]`, `[records]` paths, `[radar]` path, `[exemptions]`
with reasons, `[floors]`, `[drop_tickets]` with quality, the score
accepted from and to, and reason. A region is declared by a marker or by
a line range. The default markers are the `# --- <Section> ---` comments
the fleet's shell and Python tools already carry (`Action functions`,
`Flow functions`, `Main`, `Predicates`, `Pure helpers`, `Entry points`),
with the section-to-layer mapping in `Vocabulary`; a file written to the
coding skill's numbered anatomy or to neither form declares its regions by
line range. In an adopting repository `adherence.toml` is a CODEOWNERS
path naming users, so tedium lands no change to it without the owner's
approval.

### Facts and judgements told apart

Each check in `domain/qualities` is typed rule or judged at the catalog.
A rule check returns `Finding`s. A judged check returns `Question`s; only
`domain/questions` turns a `Decision` into a `Finding` with `confidence`,
a pass, or an `Abstention`, by `ThresholdPolicy`. A `Finding` carries its
`kind`; presenters never infer it.

The judged questions, by id and kind; a check with a rule part runs it
first:

| Question id | Kind | State | Asked by |
|---|---|---|---|
| `two_jobs` | binary | one unit's text with its declared layer | Layered |
| `does_io` | binary | a callable a domain function takes, with its definition and call sites | Purity |
| `same_concept` | binary | two nouns, their definitions and their use sites | Language |
| `scattered_policy` | binary | the conditionals sharing a discriminant, with their units | Decision |
| `invariant_broken` | binary | a type, its owning unit, and the foreign write | Boundary |
| `rules_elsewhere` | binary | an all-fields type and the units that compute over its fields | Anemic |
| `then_asserted` | score: not asserted, partly, fully | a design row's Then and the test's body | Behavior-driven |
| `implemented` | binary | a unit's name, docstring and body | Complete |
| `hand_rolled` | choice: the radar entries that could replace it, or none | a unit's body and the radar's Adopt rows | Complete |

`ThresholdPolicy` holds one entry per question id; the form of each entry
follows its question's kind, per the decision-models skill: a binary
question thresholds the probability of yes; a choice question thresholds
the probability of its most likely option and that option names the
finding, with `none` a pass; a score question thresholds the probability
mass in the failing band, never the expected level alone. Question ids and
options are stable; the labelled set under `adherence/evals/` keys on
them, and the entry per id is chosen from that set (the decision-models
skill, Evaluation before adoption). The first adapter behind
`DecisionPort` is the `decide` client; there is no incumbent prompt to
wrap.

### Judging a change

| Responsibility | Component | Seams crossed |
|---|---|---|
| Two reports | `judge_change` measures `change.head`; for `change.base` it asks `ReportStore.get(repo, base, identity, deadline)` with the identity a measurement of the base carries: the head run's suite version, parameters digest, analyzer set and judge availability, with the base declaration's digest; it measures the base on a miss or a mismatch | ReportStore, then `measure`'s seams |
| The declaration in force | `load_declaration` at `change.base` and at `change.head`; only the head's widening (assignments for uncovered units) and the tickets it adds are used, and only with an approval `domain/declaration` counts from `ReviewPort.approvals`; every other difference is a notice | RepositoryPort, ReviewPort |
| Provenance | `domain/verdict`: `RepositoryPort.changed` gives created, deleted and renamed units; a head finding whose identity, path resolved through the renames, is absent from the base report is introduced, whatever unit it names; one present at the base is existing | RepositoryPort |
| Compared score | `domain/score`: per quality, over the units covered in both reports plus `change.created`; a deleted unit or one covered on one side only is on neither side | none |
| Verdict | `domain/verdict`, in the design's order: not run; lowered on an introduced finding, a compared score below the base's, or a score below a floor the base had reached; inconclusive on an abstention or lost judged coverage on a touched unit, or a check that ran at the base and not at the head; raised on a risen compared score; else held. A fall covered by a ticket the head adds -- base score at most its `from`, head score at least its `to` -- is a notice; a ticket already in the base's declaration is spent and covers nothing | none |
| Floors | from the base declaration; a floor the base's score has not reached is a notice, not a bound | none |
| The hook | the `hook` stage binds `RepositoryPort` to the staged index, `DecisionPort` to `no_judge` and `ReviewPort` to `no_reviews`; `cli/main.py` computes `Deadline` from `Limits.commit_time_bound`; `judge_change` starts no check past it and passes it into every deadline-bound port call (Seams); each analyzer adapter caps its subprocess at the smaller of `Limits.analyzer_bound` and the time remaining, kills it at that cap, and returns `TimedOut`; whatever did not finish is coverage | the deadline-bound ports |

The baseline is not stored. It is the base revision's report, and the base
of a landed change is the default branch, so the bar is whatever last
landed: it rises when a raised change lands and falls, past the gate,
only with a ticket. The ticket lives in the declaration the owner approves
and names scores, not a commit; it is honored only by the change that
adds it, found by comparing the base's and the head's declarations, so it
holds on the PR's merge-base and again on the staging commit tedium
builds. Once landed it is in every later base's declaration, so it is
spent: it covers no second fall, it stays a notice in every later report
until the quality regains its `from`, and then it is a removable notice.
`ReportStore` is a cache keyed by report identity and a ledger, never the
authority: `get` reads only lookup keys that default-branch runs wrote
(Persistence), and a miss or a mismatch measures again. A PR run cannot
write a lookup key, so a report a change's own run produced is never read
back as its base.

### Findings and explanations

| Responsibility | Component | Seams crossed |
|---|---|---|
| Stable identity | `domain/finding`: a digest of quality, check, the unit's symbol and layer, and the evidence with line numbers removed; the path is joined at judging through the repository's renames, so a moved file keeps its findings | none |
| Evidence bound | `domain/finding` truncates to `Limits.evidence_bound`; the ledger record carries the location and no quoted text | none |
| SARIF | `cli/presenters/sarif.py`: one SARIF `rule` per check, one `result` per finding, the identity as `partialFingerprints`, provenance and kind as properties, notices as `notifications` | none |
| PR surface | the reusable workflow uploads the SARIF to code scanning and writes the scores, notices and verdict to the job summary; the ci-magic toolkit line lets ci.magic's judge call `adhere measure --json` and quote it | the workflow |
| Explanation | `explain` gives `ExplanationPort` the finding, the unit and the rule's text; the `Explanation` value holds the prose and `agrees`; the presenter labels it. `claude_cli` runs the CLI in print mode with every tool disallowed and no working directory in the repository; `ExplanationPort`'s contract suite asserts that each adapter reads no repository file and spawns nothing but the model's own process, with the disallow flags on its command line; the model's containment behind those flags is the CLI's guarantee, not the suite's | ExplanationPort |

### Where it runs

| Stage | `RepositoryPort` | `ReviewPort` | `DecisionPort` | `ExplanationPort` | `ReportStore` | `Deadline` | Entry |
|---|---|---|---|---|---|---|---|
| `laptop` | working tree | `no_reviews` | `decide` through the door (DECIDE-ROUTE) | `claude_cli` on request, else `none` | file cache | none | `bin/adhere` |
| `hook` | staged index | `no_reviews` | `no_judge` | `none` | file cache | the commit-time bound | the pre-commit stage in `naatm-hooks` calling `bin/adhere judge --staged` |
| `ci` | base and head revisions | `github_reviews`, the job's `GITHUB_TOKEN` | `decide` hosted, token from the job's environment, never in a spawned analyzer's environment | `none` | warehouse plus file cache | the job's remaining time | `adherence.yml` |
| `cloud` | working tree | `no_reviews` | `decide` hosted if configured, else `no_judge` (design Q4; Q3 below) | `none` | file cache | none | `bin/adhere` |

### Persistence

`record_report`, called by the CLI after `judge_change` returns, writes the
report through `ReportStore.put`; the `warehouse` adapter writes one NDJSON
record per run to the `adherence-ledger` bucket under the fleet data
warehouse's standing invariants. Every `ci` run writes the scan key
`adherence/v1/dt=YYYY-MM-DD/<repo>/<rev>-<identity>.json`; only a run on
the default branch also writes the lookup key
`adherence/v1/by-rev/<repo>/<rev>/<identity>.json` that `get` reads. The
lookup key's write credential lives in a GitHub environment restricted to
the default branch; a PR run's credential cannot write `by-rev/`, and the
scoping lives in the infra module. The record holds the identity, the
scores, the compared scores, the verdict, each finding's identity, check,
path, symbol, line and provenance, the notices, the abstentions and the
coverage. No quoted code. A write failure is returned on `Recorded` with
its reason; the CLI presents it as a `Notice` beside the report, and it
never changes the verdict.

### Security mitigations

| Threat (design) | Mitigation |
|---|---|
| The code under measurement is untrusted | Every adapter reads bytes. `RepositoryPort.read` refuses a symlink -- a mode-120000 entry at a revision, a link in a working tree or index -- and any path that resolves outside the repository root, and reports it as coverage; analyzers receive only the explicit file list it accepted, with link-following off. The only subprocesses are the analyzers over those paths, each given its configuration on the command line with discovery of repository configuration disabled, and run outside the repository's working directory; nothing imports, builds or runs repository code. The analyzers are pinned by hash: the Python ones in `adherence/`'s `uv.lock`, installed with `uv sync --frozen`; the node ones in a committed `package-lock.json` with integrity hashes, installed with `npm ci --ignore-scripts`. `DecisionPort` and `ExplanationPort` carry no tool-calling surface: the `decide` client cannot call tools, and `claude_cli` runs with every tool disallowed; each port's contract suite asserts the adapter reads no repository file and spawns nothing but its own client with those flags |
| A change rewrites its own bar | `Declaration` is read at `change.base`; of the head's declaration only widening and the tickets it adds are used, and only with an approval counted from `ReviewPort` (a code owner, not the PR's author, on a commit whose declaration equals the head's); the rest is a notice; `adherence.toml` is a CODEOWNERS path naming users |
| A change rewrites its own bar, through the store | `get` reads only `by-rev/` lookup keys; those are written only by default-branch runs, under a credential held in an environment restricted to the default branch; a PR run, even one that edits the caller workflow, holds no credential that can write them, so it cannot seed its own base |
| A change writes outside the bar | Covered runs over `change.created` against the merged declaration and lowers |
| A change shrinks the contract | Record kept diffs the records at the target against the base and lowers on a removed behavior or term |
| An unavailable judge opens the gate | `DecisionPort` failures are typed (`unavailable`, `rejected`); `domain/questions` maps them to coverage; `domain/score` keeps the affected units off both sides of the compared score; `domain/verdict` yields inconclusive at best |
| Credentials | The laptop asks through the door and holds none. The `ci` job holds, and only the engine process reads: the judge's token (`decide`); the warehouse's scan-write credential and, on default-branch runs only, its lookup-write credential (`warehouse`); `GITHUB_TOKEN` scoped to `contents: read`, `pull-requests: read` and `security-events: write` (`github_reviews`; the SARIF upload uses it in its own step). Analyzers are spawned with an allowlisted environment -- `PATH`, `LANG`, and `HOME` and `TMPDIR` set to a scratch directory -- and inherit nothing else |
| Reports leak code | `Limits.evidence_bound` on the report; no quoted text in the ledger record; the bucket is private |
| A gamed probability | Rule checks do not read the text the author tunes; an introduced rule finding lowers regardless |

---

## Parameters placed

| Design-named bound | Carried by | Supplied at |
|---|---|---|
| Threshold, per judged check | `ThresholdPolicy`, one entry per question id (policy value) | the composition root, from the suite's shipped defaults, chosen from `adherence/evals/` |
| Abstention band, per judged check | `ThresholdPolicy`, one entry per question id | as above |
| Commit-time bound | `Limits.commit_time_bound`, turned into a `Deadline` by `cli/main.py` | the `hook` stage's entry, overridable by the hook's own configuration |
| (architecture-owned) analyzer bound | `Limits.analyzer_bound`, the subprocess timeout every analyzer adapter applies, cut to the time remaining before `Deadline`; the design names only the commit-time bound | the composition root |
| Judged-check budget, per run | `Limits.judged_budget` | the composition root, per stage |
| Complexity ceiling | `Limits.complexity_ceiling` | shipped default; the declaration may lower it, never raise it |
| Duplication ceiling | `Limits.duplication_ceiling` | as above |
| Floor, per quality | `Declaration.floors` | the repository's `adherence.toml` |
| Evidence bound | `Limits.evidence_bound` | the composition root |
| Measured languages (G11) | the `analyzers` mapping | the composition root, by the declaration's languages and the adapters installed |
| Stub vocabulary | `Vocabulary.stubs` | shipped default; the declaration may extend it |
| (architecture-owned) region markers | `Vocabulary.regions` (marker form to layer); the design says only that a region is a span of one file | shipped default; the declaration may extend it |
| Design-record status that counts | `Limits.record_statuses` | the composition root |

No values here. The as-built holds them.

---

## Operability

| Question | Answer |
|---|---|
| Release class | R3 at first release: a new component, a new data store (the ledger bucket), and a new required check in adopting repositories. R2 for each later analyzer or check; R1 otherwise |
| Stages and platforms | The laptop through the release worktree (`bin/tds-release`), as the other `bin/` tools; adopting repositories' CI through `adherence.yml` pinned by the refs the OCR on Demand caller pins (`uses:` and `tools_ref`, tds-utils Issue#453 names the cost of two pins); cloud sessions by the session's checkout of this repository |
| Rollout | Per repository. Adoption requires branch protection on the default branch that requires code-owner review, and a CODEOWNERS entry naming users for `adherence.toml`. The declaration lands first with every floor absent, so the first judged change is held to the base's own scores and nothing older; it is still lowered by what it itself introduces. `adherence.yml` joins `gate`'s `needs` only after one green run on the repository; the pre-commit stage is on by default once `naatm-hooks` ships it and off by the hook's own switch |
| Rollback | Remove the job from `gate`'s `needs` and the hook stage; a repository's `adherence.toml` may stay, it changes nothing without a caller |
| Data that cannot be rolled back | Ledger records are append-only and perpetual, by the warehouse's invariants |
| Data warehouse | `adherence-ledger`, provisioned in tds-internal `ops/terraform/adherence-ledger/` on the ci-magic-ledger pattern; the scan-write and lookup-write credentials on the adopting repository per the warehouse's credential chain, the lookup one in an environment restricted to the default branch |

| Failure | Seen as | Debugged by | Parameter or seam |
|---|---|---|---|
| An analyzer missing on the runner | coverage missing for that language; verdict inconclusive at best | the report's coverage reasons name the binary; the workflow's install step | `CodeModelPort` (the `analyzers` mapping) |
| The judge unavailable | every judged check as coverage; verdict inconclusive at best | `decide probe` on the laptop; the job's `DECIDE_*` variables in CI | `DecisionPort` |
| A declaration that does not parse | verdict not run with the parse error | `adhere declaration check` | `Declaration`, read through `RepositoryPort` |
| Base report missing from the store, or kept under another identity | a second measurement of the base; slower, and the only path to a verdict | the cache's path in the report; the identity mismatch noted | `ReportStore`, report identity |
| The hook over its bound | the checks that did not run listed as coverage; the commit proceeds | the report names which checks and which analyzer hit `Limits.analyzer_bound` | `Deadline`, `Limits.commit_time_bound`, `Limits.analyzer_bound` |
| A Trace that matches nothing because a signature changed shape | one finding per design row | the use-case surface in the architecture record, compared to the code's `Signature` | `CodeModelPort` (`Signature`), `RecordsPort` |

---

## Radar proposals

| Dependency | Ring proposed | Why |
|---|---|---|
| `grimp` (BSD-2) | Trial | The Python import graph with resolution, the engine under import-linter; a library, so no contract configuration to maintain |
| `dependency-cruiser` (MIT) | Trial | The TypeScript/JavaScript import graph with path resolution and cycle detection, as a CLI emitting JSON; covers the Nuxt and Workers code |
| `ast-grep` (MIT, `ast-grep-cli` on PyPI) | Trial | Tree-sitter structural matching over Python, TypeScript, JavaScript and Bash from one rule format; the adapter owns the rules. Semgrep stays the gate's security scanner and is not reused here |
| `lizard` (MIT) | Trial | Per-function complexity over Python, TypeScript and JavaScript from one tool |
| `jscpd` (MIT) | Trial | Duplication over every MVP language, with a JSON reporter |
| `markdown-it-py` (MIT) | Trial | Reads the Behaviors table, Domain Language, use-case surface and radar from the records |
| `click` (BSD-3) | Trial | The CLI's commands, options and help in `cli/main.py`; entry point only |
| `boto3` (Apache-2.0) | Trial | The S3-protocol client the `warehouse` adapter writes R2 with; adapter only |
| Claude CLI (`claude`) | Trial | The `claude_cli` explanation adapter only, on request on the laptop; receives untrusted unit text, so it runs in print mode with every tool disallowed |
| SARIF 2.1.0 | Adopt (a format, not a package) | The one finding shape the editor, code scanning and the PR all read |
| Decision models through `decide` | already Trial (`lmde/TECH_RADAR.md`) | The judge; no new row |

The GitHub REST API behind `github_reviews` is called with the standard
library; no new row.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Engine language | Python, a uv project at `adherence/`, launched by `bin/adhere` as `bin/chores` launches `chores/` | The richest analyzer for the fleet's most-measured language is the standard library's `ast`; grimp, lizard and ast-grep install by pip; the radar's Python stack (uv, Ruff, strict mypy, pytest) is Adopt; cross-language analyzers are subprocesses behind ports either way |
| One runtime | The `adhere` CLI, with stages bound in one composition root | The hook, CI, the agent and the cloud session differ only in which adapter sits behind the stage-bound ports and which deadline is set; a second root would be the same wiring twice |
| Where the baseline lives | Nowhere: it is the base revision's report, cached in `ReportStore` by report identity | A committed baseline file needs a bot commit on every landing, which tedium does not make; a derived baseline ratchets by construction, the owner's drops are tickets in the declaration, and an identity on the cache keeps a hook or an older suite's report from standing in for a CI base |
| Which declaration a change is judged under | The base's, merged with the head's widening and the tickets the head adds, with a code owner's approval; `adherence.toml` under CODEOWNERS; the merged value is passed into `measure` | Widening can only add checks and a ticket is honored only by the change that adds it; everything else from the head would let a change narrow its own judge |
| Code model, not per-language checks | Every analyzer produces one `CodeModel`; every check reads only that | Writing each check per language multiplies the checks by the languages; one model keeps each check written once |
| Structural facts from ast-grep | One rule format for stubs, nesting, regions, tests and assertions across languages | The TypeScript compiler API would need a node sidecar for what tree-sitter answers from a rule file |
| Questions batched per unit | One `Schema` per unit, every question about that unit together | The decision-models skill: each call pays to read the state again |
| Finding identity | A digest without line numbers or path; the path joined through renames at judging | The same flaw must be the same finding after an unrelated edit moves it or a rename relocates it |
| The bound is a deadline, not a clock | The entry point computes an instant; every deadline-bound port method takes it, every adapter caps its work at the time remaining and returns `TimedOut` | A clock port would be a fake that returns a constant; a deadline is a value every call can be held to, and a fake that ignores it fails the contract suite |
| Findings as SARIF | The CLI's machine format and the PR's surface | Code scanning renders SARIF at the line with no comment code to write; editors read it |
| The declaration's form | TOML at the repository root; regions by marker or by line range | Read with the standard library in Python; one visible file an owner edits; a line range covers files written to no marker convention |
| The ledger carries no quoted code | Location and identity only | The warehouse admits raw output text; this producer does not need the exemption |
| The explainer has no tools | `claude_cli` in print mode with every tool disallowed; a contract suite over the port | The unit under explanation can address the model; a model that can act is the one adapter through which that text could do anything |
| Where it lives in this repository | `adherence/` at the root with `bin/adhere`, listed in `lmde/LMDE.md` under the contract as `decide` is | The LMDE contract is a list of tools and services; `lmde/components/` holds install trees for laptop services, which this is not |

---

## Open Questions

- **Q1 Signature matching across languages.** How exact Trace's match is:
  function name plus parameter names, or also the keyword-only shape. JS
  has no keyword-only parameters, so "ports as keywords" there is an
  options object; the rule needs a per-language form in `Vocabulary`.
- **Q2 TypeScript types in signatures.** Whether Values in and out needs
  the TypeScript compiler's view of a parameter's type, or the declared
  type's name from the syntax is enough. If the former, a node sidecar
  joins `ts_depcruise`.
- **Q3 The judge off the laptop.** The design's Q4; this record binds
  `cloud` to hosted `decide` when configured and `no_judge` otherwise.
- **Q4 The labelled set's home.** `adherence/evals/` in this repository,
  or a sibling of the iae experiments that labelled passages for Clef.

---

## Rejections

- **import-linter's contracts as the configuration** -- it enforces a
  layering it is told in its own file; the suite needs the graph and
  applies the declaration, so the library beneath it (grimp) is enough.
- **tach** -- a Rust binary enforcing its own module-boundary file;
  same reason, and a second declaration format.
- **pytestarch, ArchUnitTS and kin** -- test-time assertion libraries,
  one per language, each a second place the layering is written down.
- **mille, lanekeep** -- young or unreleased layer checkers; neither
  reads a design record or a declaration of regions.
- **radon's maintainability index** -- the design rejects the metric.
- **semgrep for structural facts** -- already the gate's security
  scanner; slower per rule, LGPL, and ast-grep answers the same questions
  from a smaller rule file. It stays where it is.
- **A node engine like `bin/decide`** -- zero dependencies is right for a
  client of one HTTP route; an analyzer suite wants `ast` and the pip
  tools.
- **A second composition root for CI** -- the same wiring with the
  stage-bound adapters swapped is a stage, not a runtime.
- **A committed baseline file** -- needs a bot commit per landing.
- **Reading the head declaration whole** -- a change could exempt what it
  broke; widening and added tickets are the edits that cannot lower.
- **A daemon or language server** -- the editor surface is SARIF from the
  same CLI; a server is more surface than the design grants.
- **A port for presentation** -- presenters shape one `Report` value and
  do no I/O the domain depends on.
- **A port for the clock** -- the bound is a deadline, an instant passed
  in; a clock fake would be a constant and could not test the bound.

---

## Related Documents

- [DESIGN.ARCH-ADHERENCE.md](./DESIGN.ARCH-ADHERENCE.md) -- the design
  this implements
- [DECIDE-ROUTE.DESIGN.md](./DECIDE-ROUTE.DESIGN.md) -- the door the
  `laptop` stage asks through
- `docs/ops/decide.md` -- the `decide` client the `DecisionPort` adapter
  drives, and its hosted configuration for the `ci` stage
- `docs/arch/ARCHITECTURE.md`, `docs/arch/ocr-review/` -- the as-built this
  was written against; the reusable-workflow and two-pin pattern
- template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md` -- the
  ledger's invariants and credential chain
- template-tools `docs/design/DESIGN.CI-MAGIC-TOOLKIT.md` -- the manifest
  line that hands `adhere` to the CI judge
- `chores/` -- the Python hexagonal layout and `bin/chores` launcher this
  engine copies
- the coding skill, Section 1.2; the testing skill; the decision-models
  skill -- the rules the checks execute and the port the judge sits behind