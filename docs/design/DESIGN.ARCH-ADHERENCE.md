# Architectural Adherence

> **Status:** DRAFT
> **Date:** 2026-10-24
> **Authors:** Todd Stumpf, Claude
> **Depends on:** [LMDE](./LMDE.DESIGN.md); the decide route, [DECIDE-ROUTE](./DECIDE-ROUTE.DESIGN.md) (DRAFT), for the laptop's judge; template-tools [ci.magic toolkit](https://github.com/Nine-At-A-Time-Media/template-tools/blob/main/docs/design/DESIGN.CI-MAGIC-TOOLKIT.md) for the CI judge's hand-off; template-tools [the data warehouse](https://github.com/Nine-At-A-Time-Media/template-tools/blob/main/docs/design/ARCHITECTURE.DATA-WAREHOUSE.md) for durable reports
> **Origin:** [concept: arch-adherence](../concepts/arch-adherence/CONCEPT.md); Slater, [arXiv 2512.04273](https://arxiv.org/pdf/2512.04273)

---

## Overview

Adherence is the suite that measures how well a repository's code keeps
the structure the SDLC asks of it: layered, hexagonal, domain-driven,
composable, injectable, behavior-driven, complete and on the tech radar.
It turns the coding skill's review-time tests into checks that run, scores
each quality, refuses a change that lowers a score, and names every flaw
well enough that an agent can fix it. It is product, not tooling: the
gate, the merge bot, the hooks and the agents all code against its verdict.

---

## Problem and approach

**The problem.** The fleet's structural rules exist only as prose. The
coding skill names nine mechanical tests and the testing skill asks that
each be written as a real test, but nothing in any repository executes
them. A reviewer applies them when attentive and skips them when not. An
agent that imports a vendor into the domain, stubs a use case, or writes a
test with no assertion produces a green suite and a clean review, and the
drift compounds silently. Slater measured exactly this on LLM-written code:
an 80% violation rate from a weaker model, hidden behind a higher
maintainability index that was an artifact of writing less. The paper's
remedy, a rule-based guardrail whose report is fed back to the agent, does
not exist for our languages and our rules.

**The approach.**

- One closed set of qualities, each defined by the SDLC's own rules, each
  with named checks and a score.
- Three kinds of check, told apart in every report: a rule check that is a
  fact, a judged check that is a bounded judgement with a confidence, and
  an explanation that is prose on request and never a verdict.
- A repository declares its layers, runtimes and design records once; a
  change is judged under a declaration it cannot rewrite.
- The design and architecture records are inputs: Trace and Language read
  the Behaviors table and the Domain Language, never a restatement.
- A baseline per quality that only ratchets up on its own; a change that
  would lower it does not land.
- Findings carry provenance: a flaw a change introduced blocks it, a flaw
  that predates it is reported and does not.
- The same findings in the terminal, the pre-commit hook, CI, and an
  agent's self-review loop.

**Tradeoffs.**

| Given up | Why it is worth it |
|---|---|
| A repository must declare its layers before layer checks run | Inferring layers from paths would guess, and a guess that is wrong fails the wrong file; a declaration is a sentence the owner writes once |
| A repository without a design record gets no Trace or Language score | Those checks compare code to a contract; with no contract there is nothing to compare, and a made-up contract would be a design nobody reviewed |
| Judged checks can abstain, so some flaws go unreported | An abstention is honest; a forced answer at low confidence would fail clean changes and teach everyone to ignore the suite |
| Adopting on a repository that does not adhere starts with a low baseline, not a fixed bar | A bar nobody clears is switched off; a ratchet from wherever the repository stands is a bar that holds |
| Existing flaws never block a change | A change is judged on what it did; blocking it for its neighbours' debt punishes the wrong author and stalls every repository at adoption |
| One more required check and one more hook stage | It replaces a review-time ritual that was not being performed |
| Scores are comparable only against the same repository's past | Repositories differ in size, language and declaration; a cross-repository number would invite a comparison it cannot support (Q2) |

---

## Goals

- **G1 Every quality is measured.** Each quality in the Qualities table
  has at least one check, and every run reports a score for it or says
  why it could not.
- **G2 Facts and judgements are told apart.** Every finding says whether
  a rule check or a judged check produced it, and a judged finding carries
  its confidence.
- **G3 Inconclusive never fails.** An abstention, an unavailable judge, or
  a check that did not run never lowers a verdict on its own.
- **G4 Not run is loud.** A check that could not run is reported as
  coverage missing, with the reason. The absence of findings is never
  reported as adherence.
- **G5 Regression is refused.** A change whose score on any quality falls
  below the baseline, or below the owner's floor, gets the verdict
  lowered.
- **G6 The bar ratchets.** A change that lands with a raised score raises
  the baseline with nothing to configure. Lowering a baseline is an
  owner's act, recorded with a reason, visible in every later report.
- **G7 Existing flaws do not block.** Every finding is marked introduced
  or existing. Only introduced findings and a lowered score move a
  verdict.
- **G8 Findings are fixable.** A finding names the unit, the quality, the
  check, and the evidence. A layer finding also names the layer the unit
  is in and the layer it reached.
- **G9 One declaration.** A repository states once which units are in
  which layer, which runtimes it has, where its design records are, and
  what it exempts. The declaration a change is judged under is never one
  the change wrote.
- **G10 Design records are read, not restated.** Trace reads the design's
  Behaviors table and the architecture record's use-case surface.
  Language reads the design's Domain Language. The suite holds no copy of
  either.
- **G11 Many languages, one suite.** Python, TypeScript with JavaScript,
  and shell are measured at the MVP. A unit in a language with no
  analyzer is reported as uncovered, never passed.
- **G12 Layers are not directories.** A file that keeps domain,
  application and wiring as three regions is measured by the same checks
  as a package that keeps them as directories.
- **G13 Runs where the developer is.** The suite runs on demand on the
  laptop, in the pre-commit hook, as a required check in CI, and in an
  agent's self-review before a PR. A finding is the same finding in all
  four.
- **G14 Commit time is bounded.** The checks that run at commit finish
  within the commit-time bound. Checks that cannot run where somebody is
  waiting.
- **G15 Explanations on demand.** Any finding can be explained in prose.
  The explanation is labelled as such and changes no score and no verdict.
- **G16 Reports persist.** Every run's report is kept durably, so
  adherence over time, per repository and per quality, is a query.
- **G17 Exemptions are visible and reasoned.** An exemption carries a
  reason, appears in every report it affects, and an exemption a change
  adds is itself an introduced finding.
- **G18 The code under measurement is data.** The suite never executes
  the repository's code, and nothing in that code can instruct a judge.
- **G19 The suite adheres.** The suite's own repository measures the
  suite with the suite, in its own gate.

---

## Non-Goals

- **Fixing code.** The suite reports; the agent or the human repairs. A
  self-correcting loop is the agent's loop with the report as input.
- **Replacing review.** Human and agentic review stay; the suite removes
  the structural checklist from what they must carry.
- **Functional correctness and test coverage.** The test suite and the
  testing skill's thresholds own those.
- **Prose and record quality.** Markdown rules are the skill lint and the
  publicity guard; design-record quality is designomatic.
- **Style and formatting.** Ruff, Prettier and ESLint already hold those
  and are not re-implemented.
- **Security scanning.** gitleaks, trivy and semgrep in the pre-commit
  gate own that.
- **A score comparable across repositories.** Deferred; see Q2.
- **Languages beyond the MVP three.** Go and GDScript are later
  analyzers, not later designs.
- **A hosted service or a dashboard.** Reports persist; a view over them
  is a later consumer of the data.
- **Judging a repository with no declaration on layer checks.** It gets
  the checks that need none and a coverage report naming the rest.
- **Owning the SDLC's rules.** The skills define the qualities; the suite
  executes them. A rule change is a skill change first.

---

## Design

### The qualities and their checks

The quality set is closed by this record. Each check below is named in the
problem's language; the coding skill, Section 1.2, is the authority for the
nine that carry its names. Kind is R for a rule check and J for a judged
check; a check listed as R/J has a rule part and a judged part, and the
judged part runs only on what the rule part could not decide.

| Quality | Adherence means | Checks |
|---|---|---|
| Layered | Rules, workflow and wiring are three separate jobs | Trace (R): every design behavior resolves to one application unit, by the use-case surface's signature. Purity (R): no domain unit takes a port, a callable that does I/O, or a clock. Wiring (R): exactly one composition root per declared runtime, and nothing below it names a concrete adapter. Anatomy (R): a file's regions run header, imports, constants, flags, predicates, helpers, flow, entry, in that order. Two jobs (J): a unit that does two of rules, workflow and wiring |
| Hexagonal | The core depends on no mechanism | Grep (R): no domain or application unit names a vendor, an SDK, the environment, the filesystem, the network, or a model id. Arrow (R): every import crosses inward and no import cycle exists. Swap (R): every port has at least one fake and the core imports only the port. Change (R): every seam the architecture record names exists as exactly one port, policy or parameter |
| Domain-driven | Each concept is named once, in the problem's words, with one owner | Language (R/J): every noun in a use-case signature is defined in the design's Domain Language under that spelling; the judged part asks whether two differently spelled nouns are one concept. Decision (J): a choice spread across conditionals on the same discriminant instead of one named policy. Boundary (R/J): a value type whose fields are written outside its owning unit; the judged part asks whether that write can break an invariant. Anemic (R): a type that is all fields and no behavior while its rules live elsewhere |
| Composable | A use case can be called by another with nothing in front | Values in and out (R): no use-case signature carries a wire format, an SDK type or an adapter handle. No nesting (R): no function defined inside another. Helpers take values (R): no pure helper takes a port or a callable |
| Injectable | Dependencies arrive at the flow function and never below it | Ports as keywords (R): every port a use case takes is a named dependency after the values. No self-wiring (R): no use case constructs an adapter. No reach (R): no use case or domain unit reads a global, a singleton, or the environment. Fakeable (R): every composition root can be built with every port faked |
| Behavior-driven | Every kept test asserts a design behavior through the public surface | Kept test (R): every design behavior has a test that calls its use case by the surface's signature. Then asserted (J): that test asserts the row's Then, not merely that nothing raised. Public surface (R): no test reaches past a use case into a helper or an internal. Real assertion (R): no test without an assertion and no placeholder assertion |
| Complete | The code does the work it claims to | Stub (R): no `pass`, `NotImplemented`, `TODO`, "logic goes here", or sleep standing in for work, in a non-test unit. Done (J): a unit whose body does not implement what its name and docstring claim. Hand-rolled (J): a primitive written by hand where a radar-adopted library provides it. Complexity (R): no function over the complexity ceiling. Duplication (R): no clone over the duplication ceiling |
| Radar-true | Every dependency is one the radar allows | Dependency (R): every dependency a change introduces is on Adopt or Trial of the radar the repository names. Edge only (R): every radar entry is imported from an adapter, never from the core |

Kept test and Then asserted together are the Trace test's other half: Trace
says the behavior has a home in the code; these say it has a home in the
suite.

### Units and layers

A unit is what a check is over: a file, a function, a type, a module, an
import edge, a design behavior, or a test. Every unit the declaration
covers is in exactly one layer: domain, application, ports, adapters,
composition root, or test. A unit the declaration does not cover is
unassigned; it is counted in coverage, never scored.

Layers are not directories. A declaration may assign a whole directory, a
file, or a region of a file marked by the file's own section comments, so
a one-file tool and a package are measured alike (G12).

### The declaration

A repository declares, once, in one place:

- which units are in which layer, and which runtimes it has;
- where its design records are;
- which radar it is held to;
- its exemptions, each with a reason;
- its floors, if the owner has set any.

The declaration a change is judged under is the one in force before the
change, never the one the change carries (G9). A change that edits the
declaration is judged under the old one and reports the edit as an
introduced finding, so the next change is judged under the new one. When
the declaration and the code disagree, for example a declared runtime with
no composition root, the suite reports the disagreement as a finding and
does not guess which is right.

### Design records as input

Trace, Language, Change and Kept test read the approved records of the
code under measurement: the Behaviors table, the Domain Language, the
use-case surface and the seam list. The suite never holds a copy (G10). A
record that is missing, or still in draft, leaves those checks with no
contract; they report coverage missing and name the record. A behavior
row written in a way nothing could trace to a function, with no nameable
action or observation, is itself a finding against the record.

### Measurement

A run measures a repository, or a change in it, and produces a report:

- a score per quality: the units that pass every check of that quality,
  as a fraction of the units that quality's checks covered;
- the findings, each with its kind, its provenance, and its evidence;
- the abstentions, per judged check;
- coverage: every unit and check that did not run, and why.

A judged check puts one bounded question about one unit to the judge and
gets back a probability. The suite's threshold policy turns the probability
into a finding, a pass, or an abstention; the judge never decides that. A
judged finding carries its confidence (G2). The judge is given the unit as
data to be judged, never as instructions (G18).

A rule check is reproducible: the same code and the same declaration give
the same result on every machine.

### Judging a change

A verdict judges a change against the repository's baseline:

| Verdict | Meaning |
|---|---|
| raised | At least one score rose and none fell; no introduced finding from a rule check |
| held | No score moved; no introduced finding from a rule check |
| lowered | A score fell below the baseline or a floor, or a rule check found an introduced flaw |
| inconclusive | No score fell and no rule check found an introduced flaw, but a judged check abstained or did not run on a unit the change touched |
| not run | The suite could not measure; the reason is reported |

Only lowered fails a gate. Inconclusive and not run never read as pass
(G3, G4). An introduced finding from a judged check above its threshold
makes the verdict lowered; one inside the abstention band makes it
inconclusive.

Provenance: a finding is introduced when the unit it names is one the
change created or edited and the finding was absent before the change;
otherwise it is existing (G7).

The baseline per quality moves up when a change with the verdict raised
lands. It moves down only by the owner, with a reason, and the move is a
row in every later report until the score passes the old baseline again
(G6). A floor is a bound the owner sets below which a score counts as
lowered whatever the baseline says.

### Findings and explanations

A finding names: the quality, the check, the kind, the unit, the evidence
(at most the offending line and its location), the provenance, and for a
layer check the layer the unit is in and the layer it reached (G8). The
same finding is produced in the terminal, the hook, CI and the agent's
self-review, and it carries a stable identity so the four can be joined.

An explanation is prose about one finding, produced only when asked,
labelled as an explanation, and never an input to a score or a verdict
(G15). It may disagree with the finding; when it does, the finding stands
and the disagreement is shown.

### Where it runs

| Place | What runs | Bound |
|---|---|---|
| The laptop, on demand | Every check | None |
| The pre-commit hook | The rule checks over the staged change | The commit-time bound (G14) |
| CI, as a required check | Every check over the pull request's change | The gate's own time |
| An agent's self-review | Every check over its diff, before the PR | None |
| A cloud session | The rule checks; judged checks when a judge is reachable (Q4) | None |

The same declaration, the same baseline, the same findings in each. A place
that cannot run a judged check reports it as coverage missing, never as a
pass.

### Exemptions

An owner may exempt a unit from a check, or dismiss one finding, with a
reason. The reason is in the declaration and in every report the exemption
touches (G17). An exemption added by a change is an introduced finding of
its own, so a change cannot quietly exempt what it broke. No exemption can
exempt the check that reports exemptions.

---

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| A repository is measured | Given a declared repository, When a run is asked for, Then the report holds a score for every quality and the findings behind each |
| A domain leak is found | Given a domain unit that names a vendor, the environment, the filesystem, the network or a model id, When Grep runs, Then a finding names the unit, the symbol and the layer it reached |
| An inward arrow holds | Given a repository whose every import crosses inward, When Arrow runs, Then there is no Arrow finding |
| A cycle is found | Given two units that import each other, When Arrow runs, Then one finding names the cycle |
| A behavior with no home is found | Given a design behavior that no application unit carries by the surface's signature, When Trace runs, Then a finding names the behavior and the record it came from |
| A behavior with a home passes | Given a design behavior carried by one application unit with the surface's signature, When Trace runs, Then there is no Trace finding for it |
| A port in a rule is found | Given a domain function that takes a port, a callable that does I/O, or a clock, When Purity runs, Then a finding names the function and the parameter |
| A second composition root is found | Given a declared runtime with two places that name concrete adapters, When Wiring runs, Then a finding names both |
| A missing composition root is a disagreement | Given a declared runtime with no composition root, When Wiring runs, Then a finding says the declaration and the code disagree, and names the runtime |
| A port without a fake is found | Given a port with no fake behind it anywhere in the repository, When Swap runs, Then a finding names the port |
| A named seam is missing | Given a seam the architecture record names with no port, policy or parameter in the code, When Change runs, Then a finding names the seam |
| A foreign noun is found | Given a use-case signature with a noun the Domain Language does not define, When Language runs, Then a finding names the noun and the signature |
| Two names for one concept are judged | Given two nouns the Domain Language spells differently, When Language's judged part runs, Then the finding, pass or abstention carries a confidence |
| A scattered decision is judged | Given conditionals on the same discriminant in more than one unit, When Decision runs, Then the finding, pass or abstention carries a confidence |
| An anemic type is found | Given a type that is all fields while its rules live in another unit, When Anemic runs, Then a finding names the type and the unit holding its rules |
| A wire format in a signature is found | Given a use case whose signature carries a wire format, an SDK type or an adapter handle, When Values in and out runs, Then a finding names the parameter |
| A nested function is found | Given a function defined inside another in a non-test unit, When No nesting runs, Then a finding names both |
| A self-wired use case is found | Given a use case that constructs an adapter, When No self-wiring runs, Then a finding names the use case and the adapter |
| A behavior with no kept test is found | Given a design behavior whose use case no test calls by the surface's signature, When Kept test runs, Then a finding names the behavior |
| A test that cannot fail is found | Given a test with no assertion, When Real assertion runs, Then a finding names the test |
| A Then not asserted is judged | Given a test that calls a behavior's use case, When Then asserted runs, Then the finding, pass or abstention carries a confidence |
| A stub is found | Given a non-test function whose body is a stub, When Stub runs, Then a finding names the function |
| A hand-rolled primitive is judged | Given a function that implements what a radar-adopted library provides, When Hand-rolled runs, Then the finding, pass or abstention carries a confidence |
| A disallowed dependency is found | Given a change that introduces a dependency not on Adopt or Trial of the declared radar, When Dependency runs, Then a finding names the dependency and the ring it is on, or that it is absent |
| A radar entry in the core is found | Given a domain or application unit that imports a radar entry, When Edge only runs, Then a finding names the unit and the entry |
| A one-file tool is measured | Given a file whose declaration assigns its regions to layers, When a run is asked for, Then the layer checks score its regions as they would score packages |
| An uncovered language is reported | Given a unit in a language with no analyzer, When a run is asked for, Then coverage names the unit and the language, and no score counts it as passing |
| A missing design record is reported | Given a declared repository whose design record is absent or in draft, When a run is asked for, Then Trace, Language, Change and Kept test report coverage missing and name the record, and the other qualities are scored |
| An untraceable row is a finding against the record | Given a behavior row with no nameable action or observation, When Trace runs, Then a finding names the row and the record |
| A change that raises is raised | Given a change on which one score rose and none fell and no rule check found an introduced flaw, When it is judged, Then the verdict is raised |
| A change that lowers is lowered | Given a change on which one score fell below the baseline, When it is judged, Then the verdict is lowered and the report names the quality |
| A floor holds | Given a score above the baseline but below the owner's floor, When the change is judged, Then the verdict is lowered and the report names the floor |
| An introduced flaw lowers | Given a change that creates a unit a rule check fails, When it is judged, Then the verdict is lowered and the finding is marked introduced |
| An existing flaw does not block | Given a unit a rule check failed before the change and the change did not touch it, When the change is judged, Then the finding is marked existing and the verdict is not lowered by it |
| An abstention is inconclusive | Given a change whose only unresolved item is a judged check that abstained on a unit it touched, When it is judged, Then the verdict is inconclusive, never lowered |
| An unavailable judge is inconclusive | Given no judge reachable, When a change is judged, Then every judged check reports coverage missing, the rule checks are scored, and the verdict is inconclusive at worst |
| A suite that cannot run says so | Given a repository the suite cannot measure, When a run is asked for, Then the verdict is not run with the reason, and nothing reads as a pass |
| The baseline ratchets up | Given a change with the verdict raised, When it lands, Then the baseline for each risen quality is the new score, with nothing configured |
| The baseline is lowered only by the owner | Given a change with the verdict lowered, When it lands by the owner's say, Then the baseline moves only if the owner lowered it with a reason, and that reason is in every later report |
| A change cannot rewrite its declaration | Given a change that edits the declaration, When it is judged, Then it is judged under the declaration in force before it, and the edit is an introduced finding |
| An exemption carries its reason | Given an exempted unit, When a run reports, Then the exemption and its reason appear beside the check it silenced |
| An added exemption is introduced | Given a change that adds an exemption, When it is judged, Then the exemption is an introduced finding |
| The exemption check cannot be exempted | Given a declaration that exempts the check that reports exemptions, When a run is asked for, Then the exemption is refused and reported |
| A finding is fixable | Given any finding, When an agent reads it, Then it holds the quality, the check, the kind, the unit, the evidence and the provenance, and a layer finding names the layer reached |
| The same finding everywhere | Given one flaw, When the laptop, the hook, CI and the self-review each run, Then each reports a finding with the same identity |
| The hook stays within its bound | Given a staged change, When the pre-commit hook runs, Then the rule checks finish within the commit-time bound or the hook reports which did not, and never blocks past the bound |
| An explanation changes nothing | Given a finding, When an explanation is asked for, Then prose labelled as an explanation is returned and the score and verdict are unchanged |
| A disagreeing explanation shows both | Given an explanation that disagrees with its finding, When it is shown, Then the finding stands and the disagreement is visible |
| The judge is given data | Given a unit whose text addresses the judge, When a judged check runs, Then the text is judged as the unit's content and nothing in it changes which question is asked |
| Repository code is never run | Given any run, When it completes, Then no code from the repository under measurement was executed |
| A report persists | Given a completed run, When it reports, Then the report is kept durably with the repository, the change and the time, and a failure to keep it never changes the verdict |
| The suite adheres | Given the suite's own repository, When its gate runs, Then the suite measures itself and its verdict counts |

---

## State Machine

### A run

```
+-----------+    +-----------+    +----------+    +----------+
| requested |--->| declared  |--->| measured |--->| reported |
+-----------+    +-----------+    +----------+    +----------+
      |                |
      v                v
+-----------+    +-----------+
|  not run  |    | undeclared|---> measured (coverage names the rest)
+-----------+    +-----------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| requested | declared | the declaration in force is read | it exists and is well-formed |
| requested | undeclared | no declaration | the repository has none |
| requested | not run | the suite cannot proceed | no analyzer for any unit, or the repository cannot be read |
| declared, undeclared | measured | every check that can run has run | always |
| measured | reported | the report is written and, for a change, the verdict is set | always; a failure to persist is noted, not fatal |

### The baseline

```
+--------+    +------+    +-----------+
| absent |--->| set  |<-->| ratcheted |
+--------+    +------+    +-----------+
                 ^              |
                 |  owner, with reason
                 +--------------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| absent | set | the owner adopts the suite on the repository | the first report's scores become the baseline |
| set, ratcheted | ratcheted | a change with the verdict raised lands | the risen scores become the baseline |
| set, ratcheted | set | the owner lowers a baseline | a reason is recorded and shown until the old baseline is passed again |

---

## Domain Language

- **Quality.** One of the eight named structural properties in the
  Qualities table. Invariant: the set is closed by this record.
- **Check.** One named test of one quality over one kind of unit. Every
  check is a rule check or a judged check.
- **Rule check.** A check whose result is a fact: the same code and
  declaration give the same result everywhere. Carries no confidence and
  cannot abstain.
- **Judged check.** A check that puts one bounded question about one unit
  to the judge and receives a probability. Carries a confidence and may
  abstain.
- **Judge.** Whatever answers a judged check's question with a
  probability. Invariant: the judge never sets a threshold and never sees
  the unit as instructions.
- **Analyzer.** Whatever performs rule checks for one language.
- **Explanation.** Prose about one finding, produced on request.
  Invariant: never an input to a score or a verdict.
- **Unit.** What a check is over: a file, a function, a type, a module, an
  import edge, a design behavior, or a test.
- **Layer.** Domain, application, ports, adapters, composition root, or
  test. Invariant: a covered unit is in exactly one.
- **Runtime.** A declared entry the repository can be run as, each with
  one composition root.
- **Declaration.** A repository's statement of its layers, runtimes,
  design records, radar, exemptions and floors. Invariant: the one a
  change is judged under is not one the change wrote.
- **Design record.** The approved design and architecture records of the
  code under measurement, read for their Behaviors table, Domain
  Language, use-case surface and seam list.
- **Design behavior.** One row of a design record's Behaviors table.
- **Run.** One measurement of a repository or a change.
- **Change.** A repository's head against its base, or a working tree
  against its base.
- **Report.** A run's outcome: the scores, findings, abstentions and
  coverage, and for a change the verdict.
- **Score.** Per quality, the units that pass every check of that quality
  as a fraction of the units covered. Invariant: between zero and one.
- **Finding.** One check failing on one unit: the quality, check, kind,
  unit, evidence, provenance, and for a layer check the layer reached.
  Invariant: carries a stable identity.
- **Evidence.** The location and at most the offending line.
- **Provenance.** Introduced, when the change made the finding appear on a
  unit it touched; else existing.
- **Abstention.** A judged check's answer when its probability is inside
  the abstention band. Counted as inconclusive, never as a pass or a
  finding.
- **Coverage.** Every unit and check a run did not perform, with the
  reason.
- **Baseline.** The repository's recorded score per quality that the next
  change is held to. Invariant: moves up on its own, down only by the
  owner with a reason.
- **Floor.** An owner-set score per quality below which a change is
  lowered whatever the baseline.
- **Verdict.** Raised, held, lowered, inconclusive, or not run. Invariant:
  only lowered fails a gate.
- **Exemption.** An owner's statement that a unit is not checked by one
  check, or that one finding is dismissed, with a reason. Invariant:
  cannot cover the check that reports exemptions.
- **Owner.** The human who owns the repository under measurement.

---

## Parameters

| Bound | Constraint |
|---|---|
| Threshold, per judged check | The probability above which a judged check is a finding; chosen from a labelled set per check, never by eye |
| Abstention band, per judged check | The probabilities that are neither a finding nor a pass; non-empty for every judged check |
| Commit-time bound | How long the pre-commit hook may take; short enough that a developer does not bypass it |
| Judged-check budget, per run | How many judged questions one run may ask; large enough for a typical change, bounded so a large change degrades to abstentions and coverage, never to a hung run |
| Complexity ceiling | The per-function complexity above which Complexity finds; a ratchet, never raised to fit a file |
| Duplication ceiling | The clone size above which Duplication finds; a ratchet |
| Floor, per quality | Set by the owner, or absent |
| Evidence bound | How much of a unit a finding may quote; at most the offending line |
| Analyzer set | The languages the suite measures; at least Python, TypeScript with JavaScript, and shell |
| Stub vocabulary | The markers Stub recognises; extended by the owner, never emptied |
| Design-record status that counts | Which statuses make a record readable for Trace and Language; at least APPROVED and IMPLEMENTED |

---

## Security Considerations

- **The code under measurement is untrusted.** A unit can carry text
  addressed to the judge. The suite performs only static reading of the
  repository and never imports, builds or executes it (G18). A judged
  question is fixed by the suite; the unit is its data. A judge that could
  act on text is kept out of any tool-calling loop.
- **A change can try to rewrite its own bar.** The declaration, the
  baseline and the exemptions a change is judged under are the ones in
  force before it (G9, G17). The edit itself is reported.
- **An unavailable judge must not open the gate.** A judge that cannot be
  reached yields coverage missing and at worst inconclusive, never a pass
  or a raised verdict (G3, G4).
- **The suite holds no credential of its own on the laptop.** Asking the
  judge there is done the way every local tool asks, through the decide
  route, which holds the credential. In CI the judge's credential is never
  in the environment of anything the suite spawns.
- **Reports may name files and symbols.** A report holds paths, symbol
  names and at most one quoted line per finding, never a file's body.
  Where reports persist, they persist where the fleet's other evaluation
  records do, with that store's privacy.
- **A gamed probability.** The author of a change controls the units a
  judged check reads, so a threshold is a target. The rule checks do not
  move with the text, and an introduced finding from a rule check is
  lowered whatever the judged checks say.

---

## Ships where

Two stages: the owner's laptop, as an LMDE component, and the adopting
repositories' CI as a required check. A cloud agent session runs it on
demand. No nonprod stage; the runbook names the stand-in.

---

## Key Decisions

| Decision | Choice | Rationale | Origin |
|---|---|---|---|
| Product or tooling | Product: design, architecture and as-built records | The gate, the hooks, the merge bot and the agents code against its verdict, so it is not self-contained | the sdlc skill, Product or tooling |
| The qualities | A closed set of eight, each defined by an SDLC rule | The suite executes the skills' rules; it does not invent its own | Todd, 2026-10-24 (concept); the coding skill, Section 1.2 |
| Kinds of check | Rule, judged, explanation; told apart in every report | A fact and a judgement fail differently and are trusted differently | the decision-models skill, The ladder |
| Inconclusive never fails | An abstention or an unrun check is at worst inconclusive | A forced low-confidence verdict fails clean changes and teaches everyone to ignore the suite | ci.magic's inconclusive verdict; Slater's maintainability paradox |
| The bar | A per-repository, per-quality baseline that ratchets up on its own and down only by the owner | A fixed bar nobody clears is switched off; a ratchet holds | the sdlc skill, law 11 |
| Provenance | Introduced blocks; existing reports | A change is judged on what it did | Todd, 2026-10-24 (concept, gating stories) |
| The declaration's source | The one in force before the change | A change that could widen its own judge judges nothing | template-tools ci.magic toolkit, G3 |
| Design records | Read as input, never copied | A copy drifts and becomes a second, unreviewed design | the sdlc skill, laws 2 and 3 |
| Comparability | Within a repository only | A cross-repository number would invite a comparison it cannot support | this record; Q2 |
| Dogfood | The suite measures itself in its own gate | A guardrail that does not hold its own author is not believed | this record |

---

## Open Questions

- **Q1 The name.** "Adherence" is this record's name for the component;
  the command has none. Rows it changes: the Overview and Ships where.
- **Q2 Comparability.** Whether a score is ever compared across
  repositories, and if so what normalises it. Rows it changes: Score,
  Non-Goals, and the data the report keeps.
- **Q3 A repository without a design record.** Whether such a repository
  may adopt the suite at all, or adopts with Trace, Language, Change and
  Kept test uncovered until a record exists. Rows it changes: Design
  records as input; the missing-record behavior.
- **Q4 The judge off the laptop.** Whether a cloud session asks a hosted
  judge directly, as `bin/decide` does today, or runs rule checks only.
  Rows it changes: Where it runs.
- **Q5 First adopters.** Which repositories are measured first; the
  candidates are this repository, template-tools and GammaGo, one per MVP
  language. Rows it changes: none here; the plan.
- **Q6 Judged checks at commit time.** Whether the hook ever asks the
  judge, within the commit-time bound, or leaves every judged check to CI
  and the agent. Rows it changes: Where it runs; the hook behavior.
- **Q7 Remediation cost.** Whether the report records what it took to
  close a finding, as Slater's proposed debt remediation index would.
  Rows it changes: Report; Future Considerations.

---

## Rejections

- **One blended score per repository** -- it hides the quality that fell;
  Slater's maintainability index rose as the code got lazier.
- **Maintainability index as a quality** -- a composite of volume and
  complexity rewards writing less, which is the omission debt the suite
  exists to find.
- **A generative model as the whole judge** -- no probability, prose to
  parse, slow, and the paper's remedy was symbolic rules first.
- **Rules only, no judge** -- "is this stub done", "are these two nouns
  one concept" and "is this `if` chain a hidden policy" have no
  deterministic form worth trusting.
- **Inferring layers from paths** -- a guess that fails the wrong file; a
  declaration costs one sentence.
- **A fixed adherence bar in this record** -- a number here freezes a
  tuning as a capability and is unreachable at adoption.
- **Blocking on existing debt** -- stalls every repository at adoption
  and blames the wrong author.
- **Automatic fixing** -- the suite that judges a fix must not author it;
  the agent's loop already does the fixing with the report as input.
- **Test coverage percentage as a quality** -- the testing skill owns it,
  and it says nothing about whether a test asserts a design behavior.
- **Restating the rules in a skill instead of a tool** -- the sdlc and
  coding skills already state them, and nothing executes prose; the
  Skills repo recorded that mechanics in prose draw defects every review
  round.

---

## Future Considerations

- **Remediation cost** -- turns, time and lines to close a finding class,
  per Slater's proposed index; pending Q7.
- **A fleet view** -- adherence over time per repository in the LMDE
  observability stack, as a consumer of persisted reports.
- **More analyzers** -- Go and GDScript, as the fleet's code demands.
- **A reviewer that reads the report** -- designomatic or the self-review
  panel given the report as context, so review spends its turns on what
  the suite cannot see.
- **Editor surface** -- findings shown at the line in the editor, from the
  same report.
- **One behavior per commit** -- a check over a change's commit sequence
  against law 5, once the kept-test checks hold.

---

## Related Documents

- [concept: arch-adherence](../concepts/arch-adherence/CONCEPT.md) -- the
  origin
- [ARCHITECTURE.ARCH-ADHERENCE.md](./ARCHITECTURE.ARCH-ADHERENCE.md) --
  how this record intends to be delivered
- [LMDE.DESIGN.md](./LMDE.DESIGN.md) -- the platform the laptop stage is
  a component of
- [DECIDE-ROUTE.DESIGN.md](./DECIDE-ROUTE.DESIGN.md) -- how a local tool
  asks the judge on the laptop
- template-tools `docs/design/DESIGN.CI-MAGIC-TOOLKIT.md` -- the hand-off
  of a repository's checker to the CI judge
- template-tools `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md` -- where
  reports persist
- the coding skill, Section 1.2; the testing skill, Where behaviors come
  from; the decision-models skill -- the rules the checks execute
- Slater, T. (2025). Quantitative Analysis of Technical Debt and Pattern
  Violation in Large Language Model Architectures. arXiv 2512.04273
