# Architectural Adherence -- architecture

> **Status:** DRAFT
> **Date:** 2026-10-24
> **Authors:** Todd Stumpf, Claude
> **Implements:** [DESIGN.ARCH-ADHERENCE.md](./DESIGN.ARCH-ADHERENCE.md) (status: DRAFT; this record was written ahead of the design's approval at the owner's request and is re-read against the design the day it is APPROVED)
> **As-built read:** `docs/arch/ARCHITECTURE.md` as of 2026-10-24: the proxy layer, the Ollama Gateway and OCR on Demand; no as-built exists for `bin/decide`, `chores/` or the dist tools, so their shapes were read from code

---

## Overview

One Python engine, `adherence/`, with one composition root, the `adhere`
CLI, bound differently per stage. Language analyzers behind one port turn a
repository into a language-neutral code model; the domain runs every rule
check over that model and emits the questions the judged checks need; a
decision port answers the questions with probabilities through the fleet's
`decide` client; a threshold policy in the core turns probabilities into
findings or abstentions. A change is judged by measuring its head and its
base and comparing the two reports, so the baseline is the base revision's
own score and nothing has to be stored for the ratchet to hold. Findings
leave as SARIF and as the fleet's ledger records. The engine is measured by
itself.

---

## Component diagram

```
 laptop / agent / cloud            CI (adopting repo)
 +---------------------+           +--------------------------------------+
 | bin/adhere          |           | adherence.yml (reusable workflow)    |
 |  (pre-commit: the   |           |  gate job -> bin/adhere judge        |
 |   rule checks,      |           |  ci-magic-toolkit manifest line ->   |
 |   --staged)         |           |  bin/adhere measure (for the judge)  |
 +----------+----------+           +------------------+-------------------+
            |                                         |
            v                                         v
 +----------------------------------------------------------------------+
 | adherence/  (uv project)                                             |
 |  cli/        thin: parse, call one use case, present                 |
 |  container   the composition root: binds adapters per stage          |
 |  application measure | judge_change | explain | record_report        |
 |  domain      qualities, checks, questions, threshold, score, verdict |
 |  ports       Repository | CodeModel | Metrics | Records | Decision   |
 |              | Explanation | ReportStore                            |
 |  adapters    git | python-ast (+grimp) | ts (dependency-cruiser)     |
 |              | astgrep (py/ts/js/sh) | lizard | jscpd | markdown     |
 |              | decide | claude-cli | file-store | warehouse | fakes  |
 +------+-------------+--------------+---------------+------------------+
        |             |              |               |
        v             v              v               v
   git (base,     analyzers      decide client   adherence-ledger
   head, tree)    (subprocess)   -> door (laptop) (R2, S3 protocol)
                                 -> hosted (CI)   + local file cache
```

Dependencies point inward: `cli -> application -> domain`;
`adapters -> ports -> domain`. No domain or application module imports a
subprocess, a file system call, an environment variable or a vendor name.

---

## Seams

| Axis of change | Seam | Kind | Why it is a seam |
|---|---|---|---|
| Where the repository's files and revisions come from (working tree, staged index, base and head in CI) | `RepositoryPort` | port | Three real sources on day one: the laptop's tree, the hook's staged index, CI's two revisions; the fake is the fourth |
| The language, and the analyzer that reads it | `CodeModelPort`, one adapter per language, registered by file extension | port | Python, TypeScript/JavaScript and shell at the MVP; Go and GDScript are later adapters with zero core edits |
| Complexity and duplication tooling | `MetricsPort` | port | lizard and jscpd today; either is replaceable, and the fake returns fixed metrics |
| How design records and the radar are read | `RecordsPort` | port | Markdown today; the records could move to another form, and the fake returns a Records value |
| Who answers a judged question | `DecisionPort` | port | The decide client through the door, the decide client hosted, a local arena later, and a fake; the decision-models skill's port |
| Who writes an explanation | `ExplanationPort` | port | A generative model is one of several; `none` is a real adapter and the default |
| Where reports persist and are read back | `ReportStore` | port | A local file cache on the laptop, the warehouse in CI, a fake in tests |
| Each judged check's threshold and abstention band | `ThresholdPolicy` | policy | Retuned from the labelled set per check without touching the checks |
| What counts as a stub, a vendor name, an environment read, a model id, per language | `Vocabulary` | policy | Retuned as the fleet's languages and vendors change; the declaration may extend it, never empty it |
| The complexity and duplication ceilings, the judged-check budget, the evidence bound, the record statuses that count | `Limits` | parameter set | Tuned values the composition root supplies from the suite's shipped defaults; the as-built holds them |
| What a repository declares: layers, runtimes, records, radar, exemptions, floors, accepted drops | `Declaration` | parameter (a domain value read through `RepositoryPort` at the base revision) | Per repository, never per run |
| How findings are presented (terminal, JSON, SARIF, PR check summary) | presenters in `cli/` | entry-point concern, not a seam | Presentation of one `Report` value; no port, because nothing behind it does I/O the domain depends on |

A judged question is one axis the design already fixed: binary, choice or
score, by id, with options that are stable. Renaming a question's id or
option is a migration of the threshold policy and the labelled set.

---

## Module map

| Unit | Layer | Runtime |
|---|---|---|
| `domain/qualities.py` -- the closed quality set, the check catalog, each check's kind | domain | all |
| `domain/model.py` -- `CodeModel`: `Unit`, `Layer`, `ImportEdge`, `Signature`, `Definition`, `TestCase`, `Region` | domain | all |
| `domain/declaration.py` -- `Declaration` parse and validation, exemptions, floors, accepted drops, the self-exemption refusal | domain | all |
| `domain/records.py` -- `DesignRecords`: behaviors, domain language, use-case surface, seams; `Radar` | domain | all |
| `domain/checks/hexagonal.py` -- Grep, Arrow, Swap, Change | domain | all |
| `domain/checks/layered.py` -- Trace, Purity, Wiring, Anatomy; the Two-jobs question | domain | all |
| `domain/checks/ddd.py` -- Language (rule part and question), Anemic, Boundary (rule part and question); the Decision question | domain | all |
| `domain/checks/composable.py` -- Values in and out, No nesting, Helpers take values | domain | all |
| `domain/checks/injectable.py` -- Ports as keywords, No self-wiring, No reach, Fakeable | domain | all |
| `domain/checks/behavior.py` -- Kept test, Public surface, Real assertion; the Then-asserted question | domain | all |
| `domain/checks/complete.py` -- Stub, Complexity, Duplication; the Done and Hand-rolled questions | domain | all |
| `domain/checks/radar.py` -- Dependency, Edge only | domain | all |
| `domain/questions.py` -- `Question`, `Schema`, `Decision`; `ThresholdPolicy` applied: finding, pass or abstention | domain | all |
| `domain/score.py` -- per-quality `Score` over covered units; `Coverage` | domain | all |
| `domain/verdict.py` -- two `Report`s and a `Change` to a `Verdict`; provenance; floors and accepted drops | domain | all |
| `domain/finding.py` -- `Finding`, its stable identity, `Evidence` bound | domain | all |
| `domain/report.py` -- `Report`, `Judgement` | domain | all |
| `application/measure.py` -- `measure` | application | all |
| `application/judge.py` -- `judge_change` | application | all |
| `application/explain.py` -- `explain` | application | all |
| `application/record.py` -- `record_report` | application | all |
| `ports/*.py` -- one `Protocol` per seam above | ports | all |
| `adapters/git.py` -- `RepositoryPort` over `git` (tree, staged index, `show <rev>:<path>`, changed paths and hunks) | adapters | all |
| `adapters/python_ast.py` -- `CodeModelPort` for Python over the standard library `ast`, import resolution by `grimp` | adapters | all |
| `adapters/ts_depcruise.py` -- `CodeModelPort` for TypeScript/JavaScript: import graph and cycles from `dependency-cruiser`, definitions and signatures from `ast-grep` | adapters | all |
| `adapters/astgrep.py` -- shared structural facts for every language (definitions, nesting, stubs, sleeps, regions, test cases and assertions) from `ast-grep` rule files the adapter owns | adapters | all |
| `adapters/shell_astgrep.py` -- `CodeModelPort` for shell: Anatomy regions, Stub, Dependency, over `ast-grep` | adapters | all |
| `adapters/lizard.py`, `adapters/jscpd.py` -- `MetricsPort` | adapters | all |
| `adapters/markdown_records.py` -- `RecordsPort` over `markdown-it-py` | adapters | all |
| `adapters/decide.py` -- `DecisionPort` over the `decide` client's record format: the door's address on the laptop, the hosted configuration in CI | adapters | all |
| `adapters/claude_cli.py` -- `ExplanationPort`; `adapters/no_explainer.py` | adapters | all |
| `adapters/file_store.py`, `adapters/warehouse.py` -- `ReportStore` | adapters | all |
| `adapters/fakes.py` -- an in-memory adapter per port, shipped so the composition root is buildable with every port faked | adapters | tests, and the Fakeable check's own evidence |
| `container.py` -- the composition root: binds adapters by stage (`laptop`, `hook`, `ci`, `cloud`) and by the declaration's languages | composition root | the `adhere` CLI |
| `cli/main.py` -- Click entry: `measure`, `judge`, `explain`, `declaration check`; presenters for terminal, JSON, SARIF, PR summary | entry point | the `adhere` CLI |
| `bin/adhere` -- the launcher that resolves the uv project, as `bin/chores` does | entry point | the laptop |
| `.github/workflows/adherence.yml` -- the reusable workflow: checkout, `bin/adhere judge --base --head`, SARIF upload, PR check summary | entry point (CI) | the `adhere` CLI, `ci` stage |

One composition root per runtime: there is one runtime, the `adhere` CLI.
The hook, CI, the agent and the cloud session are stages of that runtime,
bound by `container.py`; the ci-magic toolkit manifest line and the
pre-commit stage both invoke the same CLI.

---

## Use-case surface

| Design behavior | Use case (signature) | Ports |
|---|---|---|
| A repository is measured | `measure(target: Target, *, repository: RepositoryPort, analyzers: Analyzers, metrics: MetricsPort, records: RecordsPort, judge: DecisionPort, policies: Policies, clock: Clock) -> Report` | RepositoryPort, CodeModelPort (via `Analyzers`), MetricsPort, RecordsPort, DecisionPort |
| A domain leak is found | (`measure`; a scenario of Grep) | CodeModelPort |
| An inward arrow holds | (`measure`; Arrow) | CodeModelPort |
| A cycle is found | (`measure`; Arrow) | CodeModelPort |
| A behavior with no home is found | (`measure`; Trace) | CodeModelPort, RecordsPort |
| A behavior with a home passes | (`measure`; Trace) | CodeModelPort, RecordsPort |
| A port in a rule is found | (`measure`; Purity) | CodeModelPort |
| A second composition root is found | (`measure`; Wiring) | CodeModelPort |
| A missing composition root is a disagreement | (`measure`; Wiring) | CodeModelPort |
| A port without a fake is found | (`measure`; Swap) | CodeModelPort |
| A named seam is missing | (`measure`; Change) | CodeModelPort, RecordsPort |
| A foreign noun is found | (`measure`; Language, rule part) | CodeModelPort, RecordsPort |
| Two names for one concept are judged | (`measure`; Language, question) | DecisionPort |
| A scattered decision is judged | (`measure`; Decision question) | DecisionPort |
| An anemic type is found | (`measure`; Anemic) | CodeModelPort |
| A wire format in a signature is found | (`measure`; Values in and out) | CodeModelPort |
| A nested function is found | (`measure`; No nesting) | CodeModelPort |
| A self-wired use case is found | (`measure`; No self-wiring) | CodeModelPort |
| A behavior with no kept test is found | (`measure`; Kept test) | CodeModelPort, RecordsPort |
| A test that cannot fail is found | (`measure`; Real assertion) | CodeModelPort |
| A Then not asserted is judged | (`measure`; Then-asserted question) | DecisionPort |
| A stub is found | (`measure`; Stub) | CodeModelPort |
| A hand-rolled primitive is judged | (`measure`; Hand-rolled question) | DecisionPort, RecordsPort |
| A disallowed dependency is found | (`measure`; Dependency) | CodeModelPort, RecordsPort |
| A radar entry in the core is found | (`measure`; Edge only) | CodeModelPort, RecordsPort |
| A one-file tool is measured | (`measure`; regions from the declaration) | CodeModelPort |
| An uncovered language is reported | (`measure`; coverage) | RepositoryPort |
| A missing design record is reported | (`measure`; coverage) | RecordsPort |
| An untraceable row is a finding against the record | (`measure`; Trace) | RecordsPort |
| The judge is given data | (`measure`; `Schema` is fixed by the domain, the unit is the `State`) | DecisionPort |
| Repository code is never run | (`measure`; every adapter reads bytes and spawns only the analyzers) | RepositoryPort, CodeModelPort |
| An unavailable judge is inconclusive | (`measure`; a typed `DecisionPort` failure becomes coverage) | DecisionPort |
| A change that raises is raised | `judge_change(change: Change, *, repository: RepositoryPort, analyzers: Analyzers, metrics: MetricsPort, records: RecordsPort, judge: DecisionPort, reports: ReportStore, policies: Policies, clock: Clock) -> Judgement` | all of `measure`'s, plus ReportStore |
| A change that lowers is lowered | (`judge_change`) | as above |
| A floor holds | (`judge_change`; floors from the base `Declaration`) | as above |
| An introduced flaw lowers | (`judge_change`; provenance) | as above |
| An existing flaw does not block | (`judge_change`; provenance) | as above |
| An abstention is inconclusive | (`judge_change`) | as above |
| A suite that cannot run says so | (`judge_change` and `measure`; `Verdict.not_run`) | RepositoryPort |
| The baseline ratchets up | (`judge_change`; the baseline is the base revision's `Report`) | ReportStore (a cache hit) or `measure` of the base |
| The baseline is lowered only by the owner | (`judge_change`; accepted drops from the base `Declaration`) | as above |
| A change cannot rewrite its declaration | (`judge_change`; `Declaration` read at `change.base`) | RepositoryPort |
| An exemption carries its reason | (`measure`; `Declaration`) | RepositoryPort |
| An added exemption is introduced | (`judge_change`; the two declarations differ) | RepositoryPort |
| The exemption check cannot be exempted | (`measure`; `Declaration` validation) | RepositoryPort |
| A finding is fixable | (`measure`; `Finding` carries every field) | none beyond `measure`'s |
| The same finding everywhere | (`measure`; `Finding.identity` is a digest of quality, check, unit and the normalised evidence) | none |
| The hook stays within its bound | (`measure` with `policies.commit_time_bound`; the `hook` stage binds `judge` to the `none` adapter) | RepositoryPort (staged index) |
| An explanation changes nothing | `explain(finding: Finding, report: Report, *, repository: RepositoryPort, explainer: ExplanationPort) -> Explanation` | RepositoryPort, ExplanationPort |
| A disagreeing explanation shows both | (`explain`; `Explanation.agrees` is a field the presenter shows) | ExplanationPort |
| A report persists | `record_report(report: Report, *, reports: ReportStore) -> Recorded` | ReportStore |
| The suite adheres | (`judge_change` in this repository's gate, over `adherence/` under its own declaration) | all |

`Target` is a repository at one revision or its working tree or staged
index. `Analyzers` is the mapping from language to `CodeModelPort` the
composition root built; the use case asks it which languages are covered
and reports the rest as coverage. `Policies` bundles `ThresholdPolicy`,
`Vocabulary` and `Limits`. Every return is a domain value: `Report`,
`Judgement`, `Explanation`, `Recorded`.

---

## Mechanism

### Measurement

| Responsibility | Component | Seams crossed |
|---|---|---|
| Read the declaration in force | `measure` -> `RepositoryPort.read(declaration path, rev)` -> `domain/declaration` | RepositoryPort |
| Build the code model | one `CodeModelPort` per declared language over the files the declaration covers; each returns `Unit`s with their `Layer` from the declaration's assignments (directory, file or region) | CodeModelPort |
| Read the records | `RecordsPort.records(declaration)`, `RecordsPort.radar(declaration)` | RecordsPort |
| Run the rule checks | every `domain/checks/*` function: `(CodeModel, Declaration, DesignRecords, Radar, Policies) -> (findings, questions)`; pure | none |
| Measure complexity and duplication | `MetricsPort.measure(units)` -> values the Complete checks compare to `Limits` | MetricsPort |
| Ask the judged questions | `questions` grouped per unit into one `Schema` each, within `Limits.judged_budget`; `DecisionPort.decide(state, schema)`; `ThresholdPolicy` applied in `domain/questions` | DecisionPort |
| Score and cover | `domain/score`: per quality, passing units over covered units; everything unread, unanalyzed or unanswered into `Coverage` with its reason | none |
| Report | `Report` value; presenters shape it | none |

The declaration is TOML at the repository root, `adherence.toml`, read with
the standard library. It names: `[layers]` as path globs and region markers
per layer, `[runtimes]`, `[records]` paths, `[radar]` path, `[exemptions]`
with reasons, `[floors]`, `[accepted_drops]` with reasons and the baseline
they accepted below. The region markers default to the coding skill's
section comments (`# --- Predicates ---`, `# --- Flow functions ---`,
`# --- Entry points ---`), so a one-file tool written to the skill is
declared by naming the file.

### Facts and judgements told apart

Each check in `domain/qualities` is typed rule or judged at the catalog.
A rule check returns `Finding`s. A judged check returns `Question`s; only
`domain/questions` turns a `Decision` into a `Finding` with `confidence`,
a pass, or an `Abstention`, by `ThresholdPolicy`. A `Finding` carries its
`kind`; presenters never infer it.

The judged questions, by id, each binary unless stated:

| Question id | State | Asked by |
|---|---|---|
| `two_jobs` | one unit's text with its declared layer | Layered |
| `same_concept` | two nouns, their definitions and their use sites | Language |
| `scattered_policy` | the conditionals sharing a discriminant, with their units | Decision |
| `invariant_broken` | a type, its owning unit, and the foreign write | Boundary |
| `then_asserted` (score: not asserted, partly, fully) | a design row's Then and the test's body | Behavior-driven |
| `implemented` | a unit's name, docstring and body | Complete |
| `hand_rolled` (choice: the radar entries that could replace it, or none) | a unit's body and the radar's Adopt rows | Complete |

Question ids and options are stable; the labelled set under `adherence/evals/`
keys on them, and the threshold per id is chosen from that set (the
decision-models skill, Evaluation before adoption). The first adapter behind
`DecisionPort` is the `decide` client; there is no incumbent prompt to wrap.

### Judging a change

| Responsibility | Component | Seams crossed |
|---|---|---|
| Two reports | `judge_change` measures `change.head`; for `change.base` it asks `ReportStore.get(repo, base)` and measures on a miss | ReportStore, then `measure`'s seams |
| The declaration in force | read at `change.base`; the head's declaration is diffed against it, and a difference is an introduced finding of the Declaration check | RepositoryPort |
| Provenance | `domain/verdict`: a head finding whose identity is absent from the base report and whose unit is in `change.touched` is introduced; else existing | none |
| Verdict | `domain/verdict`: scores compared per quality against the base report, the base declaration's floors and accepted drops; introduced rule findings lower; introduced judged findings lower; abstentions and coverage on touched units make inconclusive | none |
| The hook | the `hook` stage binds `RepositoryPort` to the staged index, `DecisionPort` to `none`, and passes `Limits.commit_time_bound`; `measure` stops starting new checks at the bound and reports the rest as coverage | RepositoryPort |

The baseline is not stored. It is the base revision's report, and the base
of a landed change is the default branch, so the bar is whatever last
landed: it rises when a raised change lands and falls only when the owner
lands a lowered one. The owner's reason lives in `accepted_drops`, which the
change that lowers must carry, and which is itself an introduced finding
until the score passes the accepted baseline again. `ReportStore` is a
cache and a ledger, never the authority.

### Findings and explanations

| Responsibility | Component | Seams crossed |
|---|---|---|
| Stable identity | `domain/finding`: a digest of quality, check, the unit's path and symbol, and the evidence with line numbers removed | none |
| Evidence bound | `domain/finding` truncates to `Limits.evidence_bound`; the ledger record carries the location and no quoted text | none |
| SARIF | `cli/presenters/sarif.py`: one SARIF `rule` per check, one `result` per finding, the identity as `partialFingerprints`, provenance as a property | none |
| PR surface | the reusable workflow uploads the SARIF to code scanning and writes the scores and verdict to the job summary; the ci-magic toolkit line lets ci.magic's judge call `adhere measure --json` and quote it | the workflow |
| Explanation | `explain` gives `ExplanationPort` the finding, the unit and the rule's text; the `Explanation` value holds the prose and `agrees`; the presenter labels it | ExplanationPort |

### Where it runs

| Stage | `RepositoryPort` | `DecisionPort` | `ReportStore` | Entry |
|---|---|---|---|---|
| `laptop` | working tree | `decide` through the door (DECIDE-ROUTE) | file cache | `bin/adhere` |
| `hook` | staged index | `none` | file cache | the pre-commit stage in `naatm-hooks` calling `bin/adhere judge --staged` |
| `ci` | base and head revisions | `decide` hosted, token from the job's environment, never in a spawned analyzer's environment | warehouse plus file cache | `adherence.yml` |
| `cloud` | working tree | `decide` hosted if configured, else `none` (Q4) | file cache | `bin/adhere` |

### Persistence

`record_report` writes the report to `ReportStore`; the `warehouse` adapter
writes one NDJSON record per run to the `adherence-ledger` bucket under the
fleet data warehouse's standing invariants, keyed
`adherence/v1/dt=YYYY-MM-DD/<repo>/<rev>.json`. The record holds the
scores, the verdict, each finding's identity, check, path, symbol, line and
provenance, the abstentions and the coverage. No quoted code. A write
failure is a notice in the report and never changes the verdict.

### Security mitigations

| Threat (design) | Mitigation |
|---|---|
| The code under measurement is untrusted | Every adapter reads bytes; the only subprocesses are the pinned analyzers over paths; nothing imports, builds or runs repository code. `DecisionPort` carries no tool-calling surface; the `decide` client cannot call tools |
| A change rewrites its own bar | `Declaration` is read at `change.base`; the diff is a finding |
| An unavailable judge opens the gate | `DecisionPort` failures are typed (`unavailable`, `rejected`); `domain/questions` maps them to coverage and `domain/verdict` to inconclusive at worst |
| Credentials | The laptop asks through the door and holds none; CI holds the judge's token in the job's environment only, and `adapters/*` spawn analyzers with that variable removed, as the ci-magic toolkit scrubs |
| Reports leak code | `Limits.evidence_bound` on the report; no quoted text in the ledger record; the bucket is private |
| A gamed probability | Rule checks do not read the text the author tunes; an introduced rule finding lowers regardless |

---

## Parameters placed

| Design-named bound | Carried by | Supplied at |
|---|---|---|
| Threshold, per judged check | `ThresholdPolicy` (policy value) | the composition root, from the suite's shipped defaults, chosen from `adherence/evals/` |
| Abstention band, per judged check | `ThresholdPolicy` | as above |
| Commit-time bound | `Limits.commit_time_bound` | the `hook` stage's entry, overridable by the hook's own configuration |
| Judged-check budget, per run | `Limits.judged_budget` | the composition root, per stage |
| Complexity ceiling | `Limits.complexity_ceiling` | shipped default; the declaration may lower it, never raise it |
| Duplication ceiling | `Limits.duplication_ceiling` | as above |
| Floor, per quality | `Declaration.floors` | the repository's `adherence.toml` |
| Evidence bound | `Limits.evidence_bound` | the composition root |
| Analyzer set | the `Analyzers` mapping | the composition root, by the declaration's languages and the adapters installed |
| Stub vocabulary | `Vocabulary.stubs` | shipped default; the declaration may extend it |
| Design-record status that counts | `Limits.record_statuses` | the composition root |

No values here. The as-built holds them.

---

## Operability

| Question | Answer |
|---|---|
| Release class | R3 at first release: a new component, a new data store (the ledger bucket), and a new required check in adopting repositories. R2 for each later analyzer or check; R1 otherwise |
| Stages and platforms | The laptop through the release worktree (`bin/tds-release`), as the other `bin/` tools; adopting repositories' CI through `adherence.yml` pinned by the two refs the OCR on Demand caller pins (`uses:` and `tools_ref`, tds-utils Issue#453 names the cost of two pins); cloud sessions by the session's checkout of this repository |
| Rollout | Per repository: the declaration lands first with every floor absent, so the first judged change is held or raised by construction; `adherence.yml` joins `gate`'s `needs` only after one green run on the repository; the pre-commit stage is on by default once `naatm-hooks` ships it and off by the hook's own switch |
| Rollback | Remove the job from `gate`'s `needs` and the hook stage; a repository's `adherence.toml` may stay, it changes nothing without a caller |
| Data that cannot be rolled back | Ledger records are append-only and perpetual, by the warehouse's invariants |
| Data warehouse | `adherence-ledger`, provisioned in tds-internal `ops/terraform/adherence-ledger/` on the ci-magic-ledger pattern; four secrets on the adopting repository per the warehouse's credential chain |

| Failure | Seen as | Debugged by |
|---|---|---|
| An analyzer missing on the runner | coverage missing for that language; verdict inconclusive at worst | the report's coverage reasons name the binary; the workflow's install step |
| The judge unavailable | every judged check as coverage; verdict inconclusive | `decide probe` on the laptop; the job's `DECIDE_*` variables in CI |
| A declaration that does not parse | verdict not run with the parse error | `adhere declaration check` |
| Base report missing from the store | a second measurement; slower, same verdict | the cache's path in the report; the ledger's `ReportStore.get` miss noted |
| The hook over its bound | the rule checks that did not run listed as coverage; the commit proceeds | the report names which checks; `Limits.commit_time_bound` |
| A Trace that matches nothing because a signature changed shape | one finding per design row | the use-case surface in the architecture record, compared to the code's `Signature` |

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
| SARIF 2.1.0 | Adopt (a format, not a package) | The one finding shape the editor, code scanning and the PR all read |
| Decision models through `decide` | already Trial (`lmde/TECH_RADAR.md`) | The judge; no new row |

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Engine language | Python, a uv project at `adherence/`, launched by `bin/adhere` as `bin/chores` launches `chores/` | The richest analyzer for the fleet's most-measured language is the standard library's `ast`; grimp, lizard and ast-grep install by pip; the radar's Python stack (uv, Ruff, strict mypy, pytest) is Adopt; cross-language analyzers are subprocesses behind ports either way |
| One runtime | The `adhere` CLI, with stages bound in one composition root | The hook, CI, the agent and the cloud session differ only in which adapter sits behind three ports; a second root would be the same wiring twice |
| Where the baseline lives | Nowhere: it is the base revision's report, cached in `ReportStore` | A committed baseline file needs a bot commit on every landing, which tedium does not make; a derived baseline ratchets by construction and the owner's drops are declared |
| Code model, not per-language checks | Every analyzer produces one `CodeModel`; every check reads only that | Nine checks times three languages as separate code is twenty-seven checks; one model keeps each check written once |
| Structural facts from ast-grep | One rule format for stubs, nesting, regions, tests and assertions across languages | The TypeScript compiler API would need a node sidecar for what tree-sitter answers from a rule file |
| Questions batched per unit | One `Schema` per unit, every question about that unit together | The decision-models skill: each call pays to read the state again |
| Finding identity | A digest without line numbers | The same flaw must be the same finding after an unrelated edit moves it |
| Findings as SARIF | The CLI's machine format and the PR's surface | Code scanning renders SARIF at the line with no comment code to write; editors read it |
| The declaration's form | TOML at the repository root | Read with the standard library in Python; one visible file an owner edits |
| The ledger carries no quoted code | Location and identity only | The warehouse admits raw output text; this producer does not need the exemption |
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
- **Q3 Region markers.** Whether a region may also be declared by line
  range in `adherence.toml` for files not written to the coding skill's
  section comments, or only by marker.
- **Q4 The judge off the laptop.** The design's Q4; this record binds
  `cloud` to hosted `decide` when configured and `none` otherwise.
- **Q5 The labelled set's home.** `adherence/evals/` in this repository,
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
- **A second composition root for CI** -- the same wiring with three
  adapters swapped is a stage, not a runtime.
- **A committed baseline file** -- needs a bot commit per landing.
- **A daemon or language server** -- the editor surface is SARIF from the
  same CLI; a server is more surface than the design grants.
- **A port for presentation** -- presenters shape one `Report` value and
  do no I/O the domain depends on.
- **A port for the clock** -- one value, passed in; a fake is a constant.

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
  line that hands `adhere` to the CI judge, and the credential scrub
- `chores/` -- the Python hexagonal layout and `bin/chores` launcher this
  engine copies
- the coding skill, Section 1.2; the testing skill; the decision-models
  skill -- the rules the checks execute and the port the judge sits behind
