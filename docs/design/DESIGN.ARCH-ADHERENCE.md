# Architectural Adherence

> **Date:** 2026-10-24
> **Authors:** Todd Stumpf, Claude
> **Depends on:** [LMDE](./LMDE.DESIGN.md)
> **Origin:** [concept: arch-adherence](../concepts/arch-adherence/CONCEPT.md); Slater, [arXiv 2512.04273](https://arxiv.org/pdf/2512.04273)

---

## Overview

Adherence is the suite that measures how well a repository's code keeps
the structure the SDLC asks of it: layered, hexagonal, domain-driven,
composable, injectable, behavior-driven, complete, on the tech radar, and
declared. It turns the coding skill's review-time tests into checks that
run, refuses a change that introduces a finding, and names every flaw
well enough that an agent can fix it. It is product, not
tooling: the gate, the hooks and the agents all code against its verdict.

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
  with named checks. Every check is a sensor: it either finds, or it does
  not; nothing is summed into a number.
- Two kinds of check, told apart in every report: a rule check that is a
  fact, and a judged check that is a bounded judgement with a confidence.
  An explanation is prose on request; it is not a check and never a
  verdict.
- A repository declares its layers, runtimes and design records, at its
  root or sub-project by sub-project, with the owner's approval. A change
  is judged under the declarations in force before it; its own
  declarations may widen what is checked, never narrow it.
- The design and architecture records are inputs: Trace and Language read
  the Behaviors table and the Domain Language, never a restatement, at the
  revision of the code they are compared against.
- Findings carry provenance: a flaw a change introduced blocks it, a flaw
  that predates it is known and does not. The known flaws are the base's
  own findings, so the bar ratchets up on its own as flaws are fixed, and
  nothing is stored or configured. A flaw a change must introduce is
  exempted by the owner in an earlier change, with a reason every report
  shows.
- The same findings in the terminal, the pre-commit hook, CI, and an
  agent's self-review loop.

**Tradeoffs.**

| Given up | Why it is worth it |
|---|---|
| A repository must declare its layers before layer checks run | Inferring layers from paths would guess, and a guess that is wrong fails the wrong file; a declaration is a sentence the owner writes once per sub-project |
| A repository without a design record gets no Trace or Language check | Those checks compare code to a contract; with no contract there is nothing to compare, and a made-up contract would be a design nobody reviewed |
| Judged checks can abstain, so some flaws go unreported | An abstention is honest; a forced answer at low confidence would fail clean changes and teach everyone to ignore the suite |
| Adopting on a repository that does not adhere starts with its flaws known, not with a fixed bar | A bar nobody clears is switched off; a ratchet from wherever the repository stands is a bar that holds |
| A flaw a change must introduce takes two changes: the owner's exemption, then the code | A change that could excuse its own finding judges nothing; the exemption's reason is in the record either way |
| Existing flaws never block a change | A change is judged on what it did; blocking it for its neighbours' debt punishes the wrong author and stalls every repository at adoption |
| New code must be declared in the change that adds it | Code the declaration does not cover is code the suite cannot see; widening coverage costs the author one line and can only add checks |
| One more required check and one more hook stage | It replaces a review-time ritual that was not being performed |

---

## Goals

- **G1 Every quality is measured.** Each quality in the Qualities table
  has at least one check, and every run reports each check's findings or
  says why it could not run.
- **G2 Facts and judgements are told apart.** Every finding says whether
  a rule check or a judged check produced it, and a judged finding carries
  its confidence.
- **G3 Inconclusive never fails, and never raises.** An abstention, an
  unavailable judge, or a check that did not run never lowers a verdict on
  its own, and never raises one.
- **G4 Not run is loud.** A check that could not run is reported as
  coverage missing, with the reason. The absence of findings is never
  reported as adherence.
- **G5 Regression is refused.** A change that introduces a finding gets
  the verdict lowered, and the report names every introduced finding so
  it can be fixed.
- **G6 The bar ratchets.** The known flaws are the base's own findings,
  so a change that fixes a flaw and lands removes it from the known set
  with nothing to configure, and reintroducing it later lowers. Within
  the suite, the one way to introduce a flaw through the gate is an
  owner's exemption with a reason, landed before the change and shown in
  every report it silences (Q9 and Q10 stay open).
- **G7 Existing flaws do not block.** Every finding is marked introduced
  or existing: introduced when it was absent before the change, whatever
  unit it names. Only introduced findings move a verdict down. Renaming a
  unit introduces nothing.
- **G8 Findings are fixable.** A finding names the unit, the quality, the
  check, and the evidence. A layer finding also names the layer the unit
  is in and the layer it reached.
- **G9 The declarations are the owner's.** A repository states, in one
  declaration at its root or one per sub-project, which units are in
  which layer, which runtimes it has, where its design records are, which
  radar it is held to, and what it exempts; a declaration changes only
  with the owner's approval. A change is judged under the declarations in
  force before it, plus the coverage its own declarations add. What its
  own declarations remove or exempt takes effect from the next change. A
  subtree no declaration governs has no adherence (The declaration).
- **G10 Design records are read, not restated.** Trace reads the design's
  Behaviors table and the architecture record's use-case surface.
  Language reads the design's Domain Language. Each is read at the
  revision of the code it is compared against. The suite holds no copy
  of either, and a change that narrows an approved record introduces a
  finding.
- **G11 Many languages, one suite.** Python, TypeScript with JavaScript,
  and shell are measured at the MVP. A unit in a language the suite does
  not measure is reported as uncovered, never passed.
- **G12 Layers are not directories.** A file that keeps domain,
  application and wiring as three regions is measured by the same checks
  as a package that keeps them as directories.
- **G13 Runs where the developer is.** The suite runs on demand on the
  laptop, in the pre-commit hook, as a required check in CI, and in an
  agent's self-review before a PR. A finding is the same finding in all
  four.
- **G14 Commit time is bounded.** A pre-commit run ends within the
  commit-time bound, whatever a check does. A check that cannot finish
  within it is reported as coverage, never as a pass.
- **G15 Explanations on demand.** Any finding can be explained in prose.
  The explanation is labelled as such, changes no finding and no verdict,
  and is produced by something that can act on nothing.
- **G16 Reports persist.** Every run's report is kept durably, so
  the findings over time, per repository and per quality, are a query.
- **G17 Exemptions are visible and reasoned.** An exemption carries a
  reason, appears in every report it affects, and an exemption a change
  adds is reported and inert for that change.
- **G18 What the repository supplies is data.** The suite never executes
  the repository's code, and nothing the repository supplies -- its code,
  its declaration, its design records or its radar -- can instruct a
  judge or an explainer.
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
- **Style and formatting.** The repository's formatters and linters hold
  those and are not re-implemented.
- **Security scanning.** The pre-commit gate's scanners own that.
- **A score.** No number is derived from the findings; a check finds or
  it does not, and nothing is compared but findings (Key Decisions).
- **Languages beyond the MVP three.** Go and GDScript are later
  languages, not later designs.
- **A hosted service or a dashboard.** Reports persist; a view over them
  is a later consumer of the data.
- **Judging a repository with no declaration on layer checks.** It gets
  the checks that need none and a coverage report naming the rest. An
  undeclared subtree of a declared repository gets less: no check reads
  it, and the coverage names it.
- **Owning the SDLC's rules.** The skills define the qualities; the suite
  executes them. A rule change is a skill change first.

---

## Design

### The Qualities table

The quality set is closed by this record. Each check below is named in the
problem's language; the coding skill, Section 1.2, is the authority for the
nine that carry its names. Kind is R for a rule check and J for a judged
check; a check listed as R/J has a rule part and a judged part, and the
judged part runs only on what the rule part could not decide.

| Quality | Adherence means | Checks |
|---|---|---|
| Layered | Rules, workflow and wiring are three separate jobs | Trace (R): every design behavior resolves to one application unit, by the use-case surface's signature. Purity (R/J): no domain unit takes a port or a clock; the judged part asks whether a callable it takes does I/O. Wiring (R): per declared runtime, exactly one unit constructs concrete adapters, that unit is in the composition-root layer, and no unit outside that layer constructs one; a fake is not a concrete adapter. Anatomy (R): a file's regions run in the coding skill's file-anatomy order. Two jobs (J): a unit that does two of rules, workflow and wiring |
| Hexagonal | The core depends on no mechanism | Grep (R): no domain or application unit names a vendor, an SDK, the environment, the filesystem, the network, or a model id. Arrow (R): every import crosses inward and no import cycle exists. Swap (R): every port has at least one fake and the core imports only the port. Change (R): every seam the architecture record names exists as exactly one port, policy or parameter |
| Domain-driven | Each concept is named once, in the problem's words, with one owner | Language (R/J): every noun in a use-case signature is defined in the design's Domain Language under that spelling; the judged part asks whether two differently spelled nouns are one concept. Decision (J): a choice spread across conditionals on the same discriminant instead of one named policy. Boundary (R/J): a value type whose fields are written outside its owning unit; the judged part asks whether that write can break an invariant. Anemic (R/J): a type that is all fields and no behavior; the judged part asks whether its rules live in another unit |
| Composable | A use case can be called by another with nothing in front | Values in and out (R): no use-case signature carries a wire format, an SDK type or an adapter handle. No nesting (R): no function defined inside another. Helpers take values (R): no pure helper takes a port or a callable |
| Injectable | Dependencies arrive at the flow function and never below it | Ports as keywords (R): every port a use case takes is a named dependency after the values. No self-wiring (R): no use case constructs a concrete adapter. No reach (R): no use case or domain unit reads a global, a singleton, or the environment |
| Behavior-driven | Every kept test asserts a design behavior through the public surface | Kept test (R): every design behavior has a test that calls its use case. Then asserted (J): that test asserts the row's Then, not merely that nothing raised. Public surface (R): no test reaches past a use case into a helper or an internal. Real assertion (R): no test without an assertion and no placeholder assertion |
| Complete | The code does the work it claims to | Stub (R): no stub marker, placeholder body, or sleep standing in for work, in a non-test unit; the stub vocabulary is a parameter. Done (J): a unit whose body does not implement what its name and docstring claim. Hand-rolled (J): a primitive written by hand where a radar-adopted library provides it. Complexity (R): no function over the complexity ceiling. Duplication (R): no clone over the duplication ceiling |
| Radar-true | Every dependency is one the radar allows | Dependency (R): every dependency a change introduces is on Adopt or Trial of the radar the repository names. Edge only (R): every radar entry is imported from an adapter, never from the core |
| Declared | Every unit is seen, under a contract the change did not shrink | Covered (R): every unit the change creates under a governing declaration is in a declared layer, by the declarations in force or by the change's own widening. Record kept (R): no design behavior and no Domain Language term is removed from an approved record |

Kept test and Then asserted together are the Trace test's other half: Trace
says the behavior has a home in the code; these say it has a home in the
suite. Declared is the suite's own quality: it makes the other eight
unavoidable.

### Units and layers

A unit is what a check is over: a file, a function, a type, a module, an
import edge, a design behavior, or a test. Every unit the governing
declarations cover is in exactly one layer: domain, application, ports,
adapters, composition root, or test. A unit under a governing declaration
that no layer covers is unassigned; it is counted in coverage, never
checked, and if the change created it, Covered finds it. A unit under no
governing declaration has no adherence: it is counted in coverage as an
undeclared subtree, no check reads it, and Covered never names it.

Layers are not directories. A declaration may assign a whole directory, a
file, or a region of a file, so a one-file tool and a package are measured
alike (G12).

### The declaration

A repository declares, in a file named `adherence.toml`:

- which units are in which layer, and which runtimes it has;
- where its design records are;
- which radar it is held to;
- its exemptions, each with a reason.

A declaration governs the subtree of the directory that holds it, and
every path or glob in it, a layer glob, a region's file, a marker file, a
record, the radar, a runtime pattern, an exemption's unit, is relative to
that directory and cannot leave it: a path that escapes makes the
declaration unreadable. A repository may hold one at its root, which
governs the whole tree, and one in each sub-project, which governs that
sub-project; neither is required, and a monorepo is declared sub-project
by sub-project. The governing declarations of a path are every
declaration in the directories from the root down to the path's own, root
first. A path with none has no adherence: nothing is measured there and
nothing is found there, and the coverage says so; a change that creates
files there is noticed, never faulted. A declaration is never added to
assets, art or the scripts that make them. A file named `adherence.toml`
that a governing declaration above it assigns to the test layer is test
data, not a declaration: it is never discovered, never in force, never a
notice.

The governing declarations are read as one. The union sections, layers,
runtimes, exemptions and vocabulary, are the union of what the governing
declarations say; one finding two files exempt is one exemption carrying
both reasons, and an exemption reaches only its own file's subtree.
Vocabulary applies to the whole run and so has no override: a nearer file
may only extend it. The single-valued sections, the design record, the radar
and the limits, take the nearest governing declaration's value: the
outermost to name one sets the default for its subtree, and a nearer one
may set its own only by saying it overrides. The notation tells defining
from overriding apart: a plain section (`[layers]`, `[records]`,
`[radar]`, `[limits]`, `[exemptions]`, `[runtimes]`, `[vocabulary]`)
defines, and the same section under `[override]` (`[override.layers]`,
`[override.records]`, and so on, never `[override.vocabulary]`) replaces
the whole section for its own subtree: everything the declarations above say for that section is void
there, and the overriding file's entries are the section. A plain
single-valued section is legal only where no declaration above has that
section, plain or overriding; an `[override]` is legal only where one
above has it; a plain union section is always legal and adds. Two
governing declarations that both define a single-valued section without
an override, and two that place one real path (a path in the tree at the
revision) in two layers without an override of the layers, are a
conflict; a conflict is a declaration that cannot be read, and the report
names both files, the section and the path. An override where no
governing declaration above has the section is also refused: it overrides
nothing, and the author has misplaced it. The limits, whichever file sets
them, only lower the shipped ceilings.

A declaration changes only with the owner's approval (G9), file by file:
each `adherence.toml` has its own declaration in force, the newest landed
revision of that file whose landing the owner approved, a deletion
included, and each edit to any of them is a notice in the report. An
approved deletion ends the file's governance from the next change; a
deletion the owner did not approve leaves the last approved revision in
force. A change is judged under the declarations in force before it, with
one addition that cannot lower anything: layer assignments in the
change's own edits to a declaration already in force, for units the
change creates, are honored, because widening can only add checks.
Everything else a change's declarations do, removing or moving an
assignment, covering an existing unit, adding an exemption, takes effect
from the next change, and so does a declaration new at the head: it
governs nothing for its own change, the units under it alone are an
undeclared subtree, and the new file is a notice. A declaration lands
first, then the code it governs is judged. An existing unit a declaration
newly covers is therefore measured at the next change's base first, so
its flaws are existing, not introduced.

When a declaration and the code disagree, for example a declared runtime
with no composition root, the suite reports the disagreement as a finding
and does not guess which is right. A declaration in force that cannot be
read, a conflict among the governing declarations included, ends the run
as not run. A change whose own declaration cannot be read is judged under
the declarations in force, and the unreadable edit is a notice.

### Design records as input

Trace, Language, Change, Kept test and Record kept read the approved
records of the code under measurement: the Behaviors table, the Domain
Language, the use-case surface and the seam list. The suite never holds a
copy (G10). A record is read at the revision of the code it is compared
against, so a change that adds a behavior and its use case together is
judged whole. A change that removes a behavior or a term from an approved
record is found by Record kept.

A record that is missing, or still in draft, leaves those checks with no
contract; they report coverage missing and name the record. A behavior
row written in a way nothing could trace to a function, with no nameable
action or observation, is itself a finding against the record.

### Measurement

A run measures a repository, or a change in it, and produces a report:

- the findings, each with its quality, check, kind, unit, evidence and
  provenance, so that each can be fixed from the report alone (G8);
- the abstentions, per judged check;
- the notices: declaration edits, a declaration new at the head, files
  created under no declaration, exemptions applied, and anything else a
  reviewer should see that is not a finding;
- coverage: every unit and check that did not run, and why.

A judged check puts one bounded question about one unit to the judge and
gets back a probability for each allowed answer. The suite's threshold
policy turns that distribution into a finding, a pass, or an abstention;
the judge never decides that. A judged finding carries its confidence
(G2). The judge is given the unit as data to be judged, never as
instructions (G18).

A rule check is reproducible: the same code and the same declarations give
the same result on every machine.

### Judging a change

A change is judged by comparing its head's report with its base's. Both
are measured under the same suite, measured languages and judge
availability, and under the declaration in force, the head with its
widening added. Where the base cannot be measured under the same, it is
not compared against: the verdict is inconclusive and the report names
what differs. The comparison is of findings, by identity, with paths
resolved through the change's renames. A head finding absent from the
base's report is introduced, a created unit's findings among them. A
base finding absent from the head's report is removed only when every
unit it names is still covered at the head and its check ran there and
passed; an abstention, an unavailable judge or a check in coverage
removes nothing (G3). A finding on a unit the change deleted is neither
introduced nor removed, so deleting a unit moves nothing by its own
findings; what the deletion breaks elsewhere is introduced (G7). A
finding an exemption silences stays in the report marked exempt and
counts as neither, on either side.

| Verdict | Meaning |
|---|---|
| not run | The suite could not measure; the reason is reported |
| lowered | An introduced finding from a rule check or from a judged check above its threshold, that no exemption in the declarations in force silences |
| inconclusive | Not lowered, and a judged check abstained on a unit the change touched, a rule or judged check could not run on a unit the change touched, a check that ran at the base could not run at the head, or the base could not be measured under the same suite, declaration, measured languages and judge availability as the head |
| raised | Not lowered, not inconclusive, and at least one finding removed |
| held | None of the above |

The rows are read in that order; the first that applies is the verdict.
Lowered fails a gate; whether not run or inconclusive blocks a merge is
Q10. Inconclusive and not run never read as pass, and inconclusive is
never reported as raised (G3, G4).

Provenance: a finding is introduced when its identity is absent from the
base's report, whatever unit it names; a use case deleted from under a
design behavior, or a fake deleted from behind a port, introduces the
finding on the behavior or the port. A renamed unit keeps its base
identity, so its findings are existing. A finding present at the base is
existing (G7).

The known flaws are the base's own findings. Each landed change's head is
the next change's base, so a flaw fixed and landed leaves the known set
with nothing to configure, and a change that brings it back introduces
it. Nothing lowers the bar through the gate: a flaw a change must
introduce is silenced by an exemption the owner lands in an earlier
change, with a reason. A lowered report lists every introduced finding with what
G8 requires, so the remediation is read from the report and not
rediscovered.

### Findings and explanations

A finding names: the quality, the check, the kind, the unit, the evidence
(at most the offending line and its location), the provenance, and for a
layer check the layer the unit is in and the layer it reached (G8). The
same finding is produced in the terminal, the hook, CI and the agent's
self-review, and it carries a stable identity so the four can be joined
and so a rename does not make it new.

An explanation is prose about one finding, produced only when asked,
labelled as an explanation, and never an input to a finding or a verdict
(G15). Whatever produces it reads the finding and the unit as data and
can act on nothing. It may disagree with the finding; when it does, the
finding stands and the disagreement is shown.

### Where it runs

| Place | What runs | Bound |
|---|---|---|
| The laptop, on demand | Every check | None |
| The pre-commit hook | The checks that fit the commit-time bound, over the staged change (Q6) | The commit-time bound (G14) |
| CI, as a required check | Every check over the pull request's change | The gate's own time |
| An agent's self-review | Every check over its diff, before the PR | None |
| A cloud session | The checks the session can run (Q4) | None |

The same declaration, the same known flaws, the same findings in each. A place
that cannot run a check reports it as coverage missing, never as a pass.

### Exemptions

An owner may exempt a unit from a check, or dismiss one finding, with a
reason. The reason is in the declaration and in every report the exemption
touches (G17). An exemption a change adds is a notice and is inert for
that change, so a change cannot exempt what it broke. An exemption names
a unit and a check, or dismisses one existing finding by its identity; a
flaw a change must introduce is exempted by unit and check in a change
before it, since the finding does not exist yet. A silenced finding stays
in the report, marked exempt with the reason, and counts as neither
introduced nor removed. No exemption can exempt the Declared quality's
checks.

---

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| A repository is measured | Given a declared repository, When a run is asked for, Then the report holds, per quality, the checks that ran and every finding each produced, with what G8 requires to fix it |
| A domain leak is found | Given a domain unit that names a vendor, the environment, the filesystem, the network or a model id, When Grep runs, Then a finding names the unit, the symbol and the layer it reached |
| An inward arrow holds | Given a repository whose every import crosses inward, When Arrow runs, Then there is no Arrow finding |
| A cycle is found | Given two units that import each other, When Arrow runs, Then one finding names the cycle |
| A behavior with no home is found | Given a design behavior that no application unit carries by the surface's signature, When Trace runs, Then a finding names the behavior and the record it came from |
| A behavior with a home passes | Given a design behavior carried by one application unit with the surface's signature, When Trace runs, Then there is no Trace finding for it |
| A port in a rule is found | Given a domain function that takes a port, a clock, or a callable that does I/O, When Purity runs and, for a callable, the judge's answer is above its threshold, Then a finding names the function and the parameter, with its confidence when judged |
| A second composition root is found | Given a declared runtime with two units that construct concrete adapters, When Wiring runs, Then a finding names both |
| A missing composition root is a disagreement | Given a declared runtime with no unit that constructs concrete adapters, When Wiring runs, Then a finding says the declaration and the code disagree, and names the runtime |
| An adapter constructed below the root is found | Given a unit outside the composition-root layer that constructs a concrete adapter, When Wiring runs, Then a finding names the unit and the adapter |
| A file out of order is found | Given a file whose regions are not in the anatomy order, When Anatomy runs, Then a finding names the file and the first region out of place |
| A unit doing two jobs is found | Given a unit that does two of rules, workflow and wiring, When Two jobs runs and the judge's answer is above its threshold, Then a finding names the unit and the jobs it does, with its confidence |
| A judged check answers with a confidence | Given a unit a judged check asks about, When that judged check runs, Then the finding, pass or abstention carries a confidence |
| A port without a fake is found | Given a port with no fake behind it anywhere in the repository, When Swap runs, Then a finding names the port |
| A named seam is missing | Given a seam the architecture record names with no port, policy or parameter in the code, When Change runs, Then a finding names the seam |
| A foreign noun is found | Given a use-case signature with a noun the Domain Language does not define, When Language runs, Then a finding names the noun and the signature |
| Two spellings of one concept are found | Given two differently spelled nouns that are one concept, When Language's judged part runs and the judge's answer is above its threshold, Then a finding names both nouns, with its confidence |
| A hidden policy is found | Given a choice spread across conditionals on one discriminant with no named policy, When Decision runs and the judge's answer is above its threshold, Then a finding names the conditionals and the discriminant, with its confidence |
| A foreign write is found | Given a value type whose field is written outside its owning unit, When Boundary runs, Then a finding names the type, the writer, and the owning unit |
| A write that breaks an invariant is found | Given a field written outside its owning unit, When Boundary's judged part runs and the judge's answer is above its threshold, Then the finding names the write and the invariant at risk, with its confidence |
| An anemic type is found | Given a type that is all fields while its rules live in another unit, When Anemic runs and the judge's answer is above its threshold, Then a finding names the type and the unit holding its rules, with its confidence |
| A wire format in a signature is found | Given a use case whose signature carries a wire format, an SDK type or an adapter handle, When Values in and out runs, Then a finding names the parameter |
| A nested function is found | Given a function defined inside another in a non-test unit, When No nesting runs, Then a finding names both |
| A helper that takes a port is found | Given a pure helper that takes a port or a callable, When Helpers take values runs, Then a finding names the helper and the parameter |
| A port taken by position is found | Given a use case that takes a port before its values or without a name, When Ports as keywords runs, Then a finding names the use case and the port |
| A self-wired use case is found | Given a use case that constructs an adapter, When No self-wiring runs, Then a finding names the use case and the adapter |
| A reach is found | Given a use case or domain unit that reads a global, a singleton or the environment, When No reach runs, Then a finding names the unit and what it reached |
| A behavior with no kept test is found | Given a design behavior whose use case no test calls, When Kept test runs, Then a finding names the behavior |
| A test that skips the Then is found | Given a kept test that calls its use case but does not assert the row's Then, When Then asserted runs and the judge's answer is above its threshold, Then a finding names the test and the behavior, with its confidence |
| A test that cannot fail is found | Given a test with no assertion, When Real assertion runs, Then a finding names the test |
| A test past the surface is found | Given a test that calls a helper or an internal instead of a use case, When Public surface runs, Then a finding names the test and what it reached |
| A stub is found | Given a non-test function whose body is a stub, When Stub runs, Then a finding names the function |
| An unfinished unit is found | Given a non-test unit whose body does not do what its name and docstring claim, When Done runs and the judge's answer is above its threshold, Then a finding names the unit, with its confidence |
| A hand-rolled primitive is found | Given a primitive written by hand where a radar-adopted library provides it, When Hand-rolled runs and the judge's answer is above its threshold, Then a finding names the unit and the library, with its confidence |
| A function over the complexity ceiling is found | Given a function whose complexity is over the ceiling, When Complexity runs, Then a finding names the function and the ceiling |
| A clone over the duplication ceiling is found | Given two stretches of code alike beyond the ceiling, When Duplication runs, Then one finding names both |
| A disallowed dependency is found | Given a change that introduces a dependency not on Adopt or Trial of the declared radar, When Dependency runs, Then a finding names the dependency and the ring it is on, or that it is absent |
| A radar entry in the core is found | Given a domain or application unit that imports a radar entry, When Edge only runs, Then a finding names the unit and the entry |
| An undeclared new unit is found | Given a change that creates a unit under a governing declaration that assigns it no layer, When Covered runs, Then a finding names the unit and the verdict is lowered |
| A widening is honored | Given a change that creates a unit and assigns it a layer in its own declaration, When the change is judged, Then the unit is checked under that layer and Covered finds nothing |
| A narrowed record is found | Given a change that removes a behavior or a term from an approved record, When Record kept runs, Then a finding names the record and what was removed |
| A record is read with its code | Given a change that adds a behavior to the record and its use case in the same change, When Trace runs, Then there is no Trace finding for it |
| A one-file tool is measured | Given a file whose declaration assigns its regions to layers, When a run is asked for, Then the layer checks find in its regions what they would find in packages |
| An uncovered language is reported | Given a unit in a language the suite does not measure, When a run is asked for, Then coverage names the unit and the language, and nothing reports it as clean |
| A missing design record is reported | Given a declared repository whose design record is absent or in draft, When a run is asked for, Then Trace, Language, Change, Kept test and Record kept report coverage missing and name the record, and the other qualities' checks run |
| A missing record on both sides is not inconclusive | Given a repository whose design record is missing at the base and at the head, When a change is judged, Then the missing record alone does not make the verdict inconclusive |
| An untraceable row is a finding against the record | Given a behavior row with no nameable action or observation, When Trace runs, Then a finding names the row and the record |
| An undeclared repository is measured | Given a repository with no declaration, When a run is asked for, Then the checks that need no declaration run, and coverage names every check that needed one |
| An undeclared subtree has no adherence | Given a repository with a declaration in one sub-project and a change that creates a unit in another sub-project with none, When the change is judged, Then no check reads the unit, Covered finds nothing, coverage names the unit's path as an undeclared subtree, and a notice names the directory the change created under no declaration |
| A new declaration governs from the next change | Given a change that adds a sub-project with its own declaration, When the change is judged, Then the new declaration governs nothing for this change, its units are an undeclared subtree, and the new file is a notice |
| A declaration's paths stay in its subtree | Given a declaration whose path or glob escapes its own directory, When a run is asked for, Then the verdict is not run and the report names the file and the path |
| A fixture is not a declaration | Given a file named `adherence.toml` under a path a governing declaration above it assigns to the test layer, When a run is asked for, Then it is not read as a declaration, governs nothing, and is no notice |
| A deleted declaration ends with its approval | Given a landing the owner approved that deletes a sub-project's declaration, When the next change is judged, Then nothing governs that subtree; Given a deletion the owner did not approve, Then the last approved revision is in force and the deletion is a notice |
| A sub-project's declaration governs its subtree | Given a declaration in a sub-project whose layer paths are relative to that directory, When a run is asked for, Then every unit under that directory is assigned by it and no unit outside the directory is |
| Governing declarations are read as one | Given a root declaration naming the radar and a sub-project declaration naming its layers and design record, When a run is asked for, Then a unit in the sub-project is checked under those layers, against that record and that radar |
| An override replaces a parent's default | Given a root declaration that names a radar and a sub-project declaration that names its own under `[override.radar]`, When a run is asked for, Then the sub-project's units are held to the sub-project's radar and the rest of the tree to the root's |
| A silent conflict is refused | Given two governing declarations that place one path in two layers, or that both define one single-valued section, neither under `[override]`, When a run is asked for, Then the verdict is not run and the report names both files and the section |
| An override of nothing is refused | Given a sub-project declaration with a section under `[override]` that no governing declaration above it defines, When a run is asked for, Then the verdict is not run and the report names the file and the section |
| A declaration in force is settled per file | Given two declarations of which only one has a landing the owner approved, When a change is judged, Then the approved one is in force and the other is a notice, and the units it alone would govern are an undeclared subtree |
| An unreadable declaration is not run | Given a declaration in force that cannot be read, When a run is asked for, Then the verdict is not run and the report names the error |
| An unreadable edit is a notice | Given a readable declaration in force and a change whose own declaration cannot be read, When the change is judged, Then it is judged under the declaration in force and the unreadable edit is a notice |
| An unapproved declaration is not in force | Given a declaration edit that landed without the owner's approval, When the next change is judged, Then it is judged under the last approved declaration and the unapproved edit is a notice |
| An author's approval is refused | Given a declaration edit approved only by the author of the change that carries it, who is not the owner, When the change lands, Then the edit does not become the declaration in force and the report says why |
| An unmeasurable base is inconclusive | Given a base the gate cannot measure under the same suite, declaration, measured languages and judge availability as the head, When the change is judged, Then the verdict is inconclusive and the report names what differs |
| A change that raises is raised | Given a change on which a base finding is absent at the head, on a unit the head still covers and a check that ran there and passed, with no finding introduced and nothing that makes the verdict inconclusive, When it is judged, Then the verdict is raised and the report names the removed finding |
| A change that lowers is lowered | Given a change that introduces a finding from a judged check above its threshold, When it is judged, Then the verdict is lowered and the report names the finding with its confidence |
| An introduced flaw lowers | Given a change that creates a unit a rule check fails, When it is judged, Then the verdict is lowered and the finding is marked introduced |
| An existing flaw does not block | Given a finding present in the base's report, When the change is judged, Then the finding is marked existing and the verdict is not lowered by it |
| A break on an untouched unit is introduced | Given a change that deletes a use case or a fake and does not edit the design behavior or port that depended on it, When the change is judged, Then the new finding on the behavior or the port is marked introduced and the verdict is lowered |
| A rename introduces nothing | Given a unit with an existing flaw that the change renames and does not edit, When the change is judged, Then its finding is marked existing and keeps its identity |
| Deleting clean code moves nothing | Given a change that only deletes units with no findings in a repository with existing flaws, When it is judged, Then nothing is introduced or removed and the verdict is held |
| Deleting a flawed unit moves nothing | Given a change that only deletes a unit with an existing flaw, When it is judged, Then that flaw is neither introduced nor removed and the verdict is held |
| An abstention is inconclusive | Given a change whose only unresolved item is a judged check that abstained on a unit it touched, When it is judged, Then the verdict is inconclusive, never lowered |
| An unavailable judge is inconclusive, never raised | Given no judge reachable at the head, When a change is judged, Then every judged check reports coverage missing, no judged finding counts as removed, an introduced rule finding still lowers, and the verdict is otherwise inconclusive |
| An exhausted judged-check budget is inconclusive | Given a change whose judged questions exceed the judged-check budget, When it is judged, Then coverage names the questions not asked and the verdict is inconclusive at best |
| A rule check that errors is coverage | Given a rule check that errors on a unit the change touched, When the change is judged, Then coverage names the check, the unit and the error, and the verdict is inconclusive at best |
| An unreadable file is coverage | Given a file in a measured language that cannot be read at the head, When the change is judged, Then coverage names the file, nothing reports it as clean, and the verdict is inconclusive at best |
| CI out of time is coverage | Given a CI run whose gate time ends before every check has run, When the change is judged, Then the checks that did not finish are coverage and the verdict is inconclusive at best |
| A suite that cannot run says so | Given a repository that cannot be read, or that has no unit in a measured language, When a run is asked for, Then the verdict is not run with the reason, and nothing reads as a pass |
| A fixed flaw stays fixed | Given a change that removed a finding and landed, When a later change brings the same finding back, Then it is introduced and the verdict is lowered, with nothing configured |
| A change cannot narrow its own declaration | Given a change that removes an assignment, covers an existing unit or adds an exemption, When it is judged, Then it is judged as if that edit were absent, and the edit is a notice |
| A newly covered unit's flaws are existing | Given a declaration edit that covers an existing unit, landed in one change, When the next change is judged, Then that unit's flaws are in the base's report and marked existing |
| An exemption carries its reason | Given an exempted unit, When a run reports, Then the exemption and its reason appear beside the check it silenced |
| An added exemption is inert for its change | Given a change that adds an exemption for a flaw it introduces, When it is judged, Then the flaw lowers the verdict and the exemption is a notice |
| The Declared quality cannot be exempted | Given a declaration that exempts Covered or Record kept, When a run is asked for, Then the exemption is refused and reported |
| A report quotes no more than the evidence | Given a finding on a unit, When the report is written, Then it holds the unit's path, the symbol and at most the offending line, and never more of the unit's body |
| The same finding everywhere | Given one flaw, When the laptop, the hook, CI and the self-review each run, Then each reports a finding with the same identity |
| The hook ends within its bound | Given a staged change and a check that does not return, When the pre-commit hook runs, Then the run ends within the commit-time bound, the checks that did not finish are coverage, and the commit is not blocked past the bound |
| An explanation changes nothing | Given a finding, When an explanation is asked for, Then prose labelled as an explanation is returned and the findings and verdict are unchanged |
| A disagreeing explanation shows both | Given an explanation that disagrees with its finding, When it is shown, Then the finding stands and the disagreement is visible |
| The judge is given data | Given a unit whose text addresses the judge, When a judged check runs, Then the text is judged as the unit's content and nothing in it changes which question is asked |
| The explainer can act on nothing | Given a unit whose text instructs the explainer to read a file or run a command, When an explanation is asked for, Then nothing is read or run and the explanation is returned or refused |
| Repository code is never run | Given any run, When it completes, Then no code from the repository under measurement was executed |
| A report persists | Given a completed run, When it reports, Then the report is kept durably with the repository, the change and the time, and a failure to keep it never changes the verdict |

---

## State Machine

### A run

```
+-----------+    +-----------+    +----------+    +----------+
| requested |--->| declared  |--->| measured |--->| reported |
+-----------+    +-----------+    +----------+    +----------+
   |     |                             ^
   |     |       +------------+        |
   |     +------>| undeclared |--------+
   |             +------------+   (coverage names the rest)
   v
+-----------+
|  not run  |
+-----------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| requested | declared | the declarations in force are read | at least one exists and the governing declarations are well-formed; a subtree none governs is coverage within the run |
| requested | undeclared | no declaration | the repository has none in force anywhere |
| requested | not run | the suite cannot proceed | a declaration in force cannot be read or the governing declarations conflict, no unit is in a measured language, or the repository cannot be read |
| declared, undeclared | measured | every check that can run has run | always |
| measured | reported | the report is written and, for a change, the verdict is set | always; a failure to persist is noted, not fatal |

---

## Domain Language

- **Quality.** One of the nine named structural properties in the
  Qualities table. Invariant: the set is closed by this record.
- **Check.** One named test of one quality over one kind of unit. Every
  check is a rule check or a judged check.
- **Rule check.** A check whose result is a fact: the same code and
  declaration give the same result everywhere. Carries no confidence and
  cannot abstain.
- **Judged check.** A check that puts one bounded question about one unit
  to the judge and receives a probability per allowed answer. Carries a
  confidence and may abstain.
- **Judge.** Whatever answers a judged check's question with
  probabilities. Invariant: the judge never sets a threshold, never sees
  the unit as instructions, and can act on nothing.
- **Threshold.** Per judged check, the rule that turns the judge's
  probabilities into a finding or a pass. Owned by the suite, never by the
  judge.
- **Abstention band.** Per judged check, the probabilities that are
  neither a finding nor a pass.
- **Explanation.** Prose about one finding, produced on request by
  something that can act on nothing. Not a check. Invariant: never an
  input to a finding or a verdict.
- **Unit.** What a check is over: a file, a function, a type, a module, an
  import edge, a design behavior, or a test.
- **Layer.** Domain, application, ports, adapters, composition root, or
  test. Invariant: a covered unit is in exactly one.
- **Port.** A named interface the core owns at one axis of change; the
  architecture record's seam list names them.
- **Adapter.** A unit that implements a port. A concrete adapter does so
  over a mechanism; a fake does so in memory.
- **Fake.** An in-memory adapter, for tests. Invariant: not a concrete
  adapter, so a test that constructs one breaks no Wiring rule.
- **Seam.** An axis of change the architecture record maps to one port,
  policy or parameter.
- **Use case.** One application-layer function carrying one or more
  design behaviors, with the signature the use-case surface gives it.
- **Composition root.** The one unit per runtime that constructs concrete
  adapters and binds them to the use cases' ports.
- **Runtime.** A declared entry the repository can be run as, each with
  one composition root.
- **Region.** A span of one file assigned to one layer.
- **Declaration.** One `adherence.toml`: a statement of the layers,
  runtimes, design record, radar and exemptions of the subtree of the
  directory that holds it, its paths relative to that directory.
  Invariant: changes only with the owner's approval; a change is judged
  under the one in force before it plus its own widening.
- **Sub-project.** A directory below the repository root that holds a
  declaration; what a monorepo's package is to the suite. Invariant: its
  declaration's paths stay under it.
- **Governing declarations.** The declarations in the directories from
  the repository root down to a path's own, root first, read as one: the
  union of their union sections (layers, runtimes, exemptions,
  vocabulary), the nearest file's value for each single-valued section
  (design record, radar, limits). Invariant: a conflict among them is a
  declaration that cannot be read, never a pick.
- **Undeclared subtree.** A path with no governing declaration. Invariant:
  no check reads it, Covered never names it, and coverage says so.
- **Override.** A section a declaration writes under `[override]` to
  replace, for its subtree, the whole of what the governing declarations
  above it say for that section. Invariant: refused where no declaration
  above has the section; a plain single-valued section is refused where
  one does.
- **Approval.** The owner's assent to one declaration edit, attributable
  to the owner and not to the author of the change that carries it.
  Invariant: an edit without it never becomes the declaration in force;
  where the owner is the author, see Q11.
- **Widening.** A layer assignment in a change's own declaration for a
  unit the change creates. Invariant: honored for the change itself; it
  can only add checks. Covering an existing unit is not widening and takes
  effect from the next change.
- **Design record.** The approved design and architecture records of the
  code under measurement, read for their Behaviors table, Domain
  Language, use-case surface and seam list, at the revision of the code.
- **Design behavior.** One row of a design record's Behaviors table.
- **Radar.** The tech radar the declaration names, read for its rings.
- **Run.** One measurement of a repository or a change.
- **Change.** A repository's head against its base, or a working tree or
  staged index against its base.
- **Base.** The revision a change is judged against. Invariant: measured
  by the gate's own run, never by a report the change supplies.
- **Head.** What a change produces: a revision, a working tree, or a
  staged index.
- **Gate.** The required check that runs the suite over a change before it
  lands. Invariant: refuses a change whose verdict is lowered; whether it
  refuses not run or inconclusive is pending Q10.
- **Report.** A run's outcome: the checks that ran, the findings,
  abstentions, notices and coverage, and for a change the verdict, the
  provenance of each finding and the findings removed. Invariant: derives
  no number from the findings.
- **Finding.** One check failing on one unit: the quality, check, kind,
  unit, evidence, provenance, and for a layer check the layer reached.
  Invariant: carries a stable identity that survives a rename.
- **Kind.** Of a finding: rule or judged, by the check that produced it.
- **Evidence.** The location and at most the offending line.
- **Provenance.** Introduced, when the finding's identity is absent from
  the base's report; existing, when it is present there.
- **Removed.** A base finding absent from the head's report, with paths
  resolved through the renames, where every unit it names is still
  covered at the head and its check ran there and passed. Invariant: a
  deleted unit's findings, an abstention, an unavailable judge and a check
  in coverage remove nothing; the removed findings are in the report.
- **Sensor.** A check, as the gate sees it: it trips, which is a finding,
  or it does not. Not a third kind of check.
- **Known flaws.** The base's findings. Invariant: never configured or
  stored as a bar; they are the base report.
- **Abstention.** A judged check's answer when its probabilities fall in
  the abstention band. Counted as inconclusive, never as a pass or a
  finding.
- **Notice.** Something a reviewer should see that is not a finding: a
  declaration edit, an exemption applied, a report not kept.
  Invariant: never moves a verdict.
- **Coverage.** Every unit and check a run did not perform, with the
  reason.
- **Verdict.** Not run, lowered, inconclusive, raised, or held, read in
  that order. Invariant: lowered fails a gate; whether not run or
  inconclusive does is pending Q10.
- **Exemption.** An owner's statement that a unit is not checked by one
  check, or that one finding is dismissed, with a reason. Invariant:
  cannot cover the Declared quality; inert for the change that adds it;
  within the suite, the one way a flaw is introduced through the gate. A
  silenced finding stays in the report marked exempt and counts as
  neither introduced nor removed.
- **Place.** Where a run happens: the laptop on demand, the pre-commit
  hook (the hook), CI as the gate, an agent's self-review before a PR, or
  a cloud session. The terminal is the laptop's and the agent's view of a
  report. Invariant: a finding has the same identity in every place.
- **Owner.** The human who owns the repository under measurement.
- **Deadline.** The instant a bounded run must end, or none for an
  unbounded run. Invariant: only an adapter compares it to the clock; the
  core reads no time.
- **Parameters.** The Parameters table as one value a run is given: the
  thresholds, the vocabulary and the limits, as the shipped defaults; the
  run merges the declarations' adjustments in itself.
- **CodeLanguage.** A language the suite measures, told by a source's
  file extension or, for a file with none, by its shebang, and named apart
  from the Language check. A source in a language no analyzer measures is
  coverage, never a pass.
- **DeclarationUnreadable.** The outcome of a declaration that cannot be
  read or parsed, with the reason. Invariant: a run given one is not run,
  never measured as undeclared.
- **Recorded.** Whether a run's report was kept, and, when it was not, the
  notice shown beside the report.
- **FinishedSink.** Where a run reports what it has done as it goes: the
  run's own coverage and notices as each is known, and each check as it
  finishes, so a run ended at its deadline still has them.
- **Latch.** A run's record of the first TimedOut any of its ports
  answered. Invariant: once it is set, the run asks no port anything more,
  and each call left is answered TimedOut without reaching the port.

---

## Parameters

| Bound | Constraint |
|---|---|
| Threshold, per judged check | The rule over the judge's probabilities above which a judged check is a finding; chosen from a labelled set per check, never by eye |
| Abstention band, per judged check | The probabilities that are neither a finding nor a pass; non-empty for every judged check |
| Commit-time bound | How long a pre-commit run may take in total; short enough that a developer does not bypass it |
| Judged-check budget, per run | How many judged questions one run may ask; large enough for a typical change, bounded so a large change degrades to abstentions and coverage, never to a hung run |
| Complexity ceiling | The per-function complexity above which Complexity finds; a ratchet, never raised to fit a file |
| Duplication ceiling | The clone size above which Duplication finds; a ratchet |
| Evidence bound | How much of a unit a finding may quote; at most the offending line |
| Stub vocabulary | The markers Stub recognises; extended by the owner, never emptied |
| Design records that count | Which records are readable for Trace and Language; at least those on the default branch |

---

## Security Considerations

- **Everything the repository supplies is untrusted.** Its code, its
  declaration, its design records and its radar are read as data. A unit
  or a record can carry text addressed to the judge or the explainer. The
  suite performs only static reading of the repository and never imports,
  builds or executes it (G18). A judged question is fixed by the suite;
  what the repository supplies is its data. Neither the judge nor the
  explainer can act on anything.
- **The first declaration is the owner's.** Each declaration in force
  is one the owner wrote or approved; until a sub-project's is, that
  sub-project is an undeclared subtree, and until any is, the repository
  is undeclared. A declaration the owner did not approve stays untrusted
  data and is never in force.
- **A change can try to rewrite its own bar.** The declaration and the
  exemptions a change is judged under are the ones in force before it,
  and the known flaws are the base's own findings; its own declaration can only widen (G9, G17). The edit
  itself is a notice.
- **A change's author cannot approve its declaration edits.** The owner's
  approval of a declaration edit never comes from the author of the
  change that carries it. Where the owner is the author, see Q11.
- **A change cannot supply its own base report.** The known flaws come
  only from the gate's own run over the base; a report a change's own run
  produced never becomes the base it is judged against.
- **A change can try to write outside the bar.** A unit the change
  creates under a governing declaration that no layer covers is a Covered finding, and lowers.
- **A change can try to shrink the contract.** Removing a behavior or a
  term from an approved record is a Record kept finding, and lowers.
- **An unavailable judge never reads as a pass.** A judge that cannot be
  reached yields coverage missing and at best inconclusive, never a pass
  or a raised verdict (G3, G4). Whether inconclusive blocks a merge is
  Q10.
- **A change can steer judged checks to inconclusive.** Its author
  controls the size of the change and the text of its units, so it can
  exhaust the judged-check budget or aim units at the abstention band.
  Such a change is inconclusive, never raised; whether it may merge is
  Q10.
- **The judge's access is out of the repository's reach.** Nothing the
  repository supplies, and nothing a check does with it, can obtain what
  the judge or the explainer is authorised with.
- **Reports may name files and symbols.** A report holds paths, symbol
  names and at most one quoted line per finding, never a file's body. A
  persisted report is readable by no one who cannot read the repository.
  Where reports persist is the architecture record's.
- **A gamed probability.** The author of a change controls the units a
  judged check reads, so a threshold is a target. The rule checks do not
  move with the text, and an introduced finding from a rule check is
  lowered whatever the judged checks say.

---

## Ships where

The owner's laptop as part of the LMDE contract, the adopting repositories' CI as a required check, and a cloud agent session on demand.

---

## Key Decisions

| Decision | Choice | Rationale | Origin |
|---|---|---|---|
| Product or tooling | Product: design, architecture and as-built records | The gate, the hooks and the agents code against its verdict, so it is not self-contained | the sdlc skill, Product or tooling |
| The qualities | A closed set of nine, each defined by an SDLC rule, the ninth being the suite's own Declared | The suite executes the skills' rules; it does not invent its own. Declared makes the other eight unavoidable | Todd, 2026-10-24 (concept); the coding skill, Section 1.2; self-review panel 2026-10-24 |
| Kinds of check | Rule and judged, told apart in every report; an explanation is not a check | A fact and a judgement fail differently and are trusted differently | the decision-models skill, The ladder |
| Inconclusive never fails and never raises | An abstention or an unrun check never yields lowered and never yields raised; the change it touches is inconclusive | A forced low-confidence verdict fails clean changes; a raise on missing coverage ratchets a number nobody measured | ci.magic's inconclusive verdict; Slater's maintainability paradox; self-review panel 2026-10-24 |
| The bar | A per-repository, per-quality baseline that is the base's compared score, so it ratchets up as changes land, and falls through the gate only by a drop ticket in the declaration in force naming scores, not a commit | A fixed bar nobody clears is switched off; a ratchet holds; a ticket makes the owner's reason part of the record and survives the base moving while a change waits to land | the sdlc skill, law 11; self-review panel 2026-10-24, both rounds |
| What a score comparison sees | The units both sides cover and the units the change created | Deleting clean code is not regression, and a judge that answered on one side only is not a rise | self-review panel 2026-10-24 |
| Provenance | Introduced is absent-at-base, whatever unit the finding names; existing reports; a rename keeps identity | A change is judged on what it did, including what it broke from under another unit | Todd, 2026-10-24 (concept, gating stories); self-review panel 2026-10-24, both rounds |
| The declaration's source | The one in force before the change, plus the change's own widening for the units it creates and the ticket it marks used; the owner approves every change to it | A change that could narrow its own judge judges nothing; widening adds checks and marking a ticket used spends a permission, and neither can lower a bar | template-tools ci.magic toolkit, G3; self-review panel 2026-10-24, both passes |
| Design records | Read as input at the code's revision, never copied; narrowing an approved record is a finding | A copy drifts and becomes a second, unreviewed design; a record pinned to the base could not be grown with its code | the sdlc skill, laws 2 and 3; self-review panel 2026-10-24 |
| Floors | Bind once reached; an aim until then | A floor above today's score would make every change unlandable | self-review panel 2026-10-24 |
| Dogfood | The suite measures itself in its own gate | A guardrail that does not hold its own author is not believed | this record |
| No score: sensors | Supersedes The bar, What a score comparison sees, Floors, and the ticket clause of The declaration's source. No number is derived from findings. A change is judged on findings by identity: an introduced finding lowers, a removed one raises, a deleted unit's findings do neither. Floors and drop tickets are removed; an owner's exemption landed in an earlier change is the one way to introduce a flaw through the gate | A fraction over files and design behaviors weighs incommensurable things, and a change that fixes one flaw and introduces another leaves it unchanged; the finding itself is the failure and already carries what a fix needs (G8). Rules moot, and removes from Open Questions, Q2 (whether a score compares across repositories) and Q8 (a score over mixed kinds of unit) | Todd, 2026-10-25, Issue#590 |
| Wiring over the test layer | A unit in the test layer may construct a concrete adapter; the Wiring rule that no unit outside the composition-root layer constructs one exempts the test layer, as Fake already exempts a fake | A test that constructs a concrete adapter is that adapter's contract suite, which the testing skill requires; the self-measurement's 60 Wiring findings were each such a test | Todd, 2026-11-06, Issue#590 |
| Language over the suite's own nouns | Deadline, Parameters, CodeLanguage, DeclarationUnreadable and Recorded join the Domain Language | They are nouns of the suite's own language in its use-case signatures that this record did not define; the self-measurement's 10 Language findings were Language working as designed over an incomplete record | Todd, 2026-11-06, Issue#590 |
| FinishedSink and Latch | FinishedSink and Latch join the Domain Language under the ruling on the suite's own nouns | They are nouns of the suite's own language in its use-case signatures that this record did not define, the class that ruling covers; the self-measurement's 6 Language findings on them were Language working as designed | Todd, 2026-11-06, Issue#590 |
| Inconclusive at the gate | In the `ci` stage a change fails on lowered and on not run only; inconclusive never fails a gate in any stage, and the report names what was not covered. Rules, and removes from Open Questions, Q10: not run blocks a merge and inconclusive does not, which settles the clauses that defer to Q10: G6's, the Verdict section's, the Gate and Verdict invariants', and the two Security Considerations' | Inconclusive is coverage missing, not a flaw found: it already never yields lowered or raised (Inconclusive never fails and never raises), and a gate that failed on it would refuse clean changes whenever the judge is down, a budget runs out or an analyzer is missing. Not run measured nothing, so it still never reads as a pass | Todd, 2026-11-06, Issue#590 |
| An owner who is the author | A landing counts as the owner's approval when a code owner approved it in a review, or when a code owner merged the pull request themselves, the owner who authored it included; the report names which counted. A landing attributable to no one but an author who is no code owner stays uncounted, and an author's own review still counts nothing. Amends Approval and the Security Consideration on a change's author; rules, and removes from Open Questions, Q11 | In a repository with one human the owner authors every declaration edit and the code host refuses self-approval, so without this no declaration could ever come into force there: the first live run skipped the landing at 49ba5438ad8c, authored and merged by the owner. Merging is an act of the owner's attributable to the owner, as a review is; a non-owner who merges their own edit is still the author alone | Todd, 2026-11-06, Issue#590 |
| Wiring's unit in the composition root | In the composition-root layer the unit Wiring counts as a root is the module: one file that constructs concrete adapters in several functions is one root, and two composition-root files that construct them are still the finding, naming the files. Below the root the unit is still the one making the call | A composition root is a file of wiring, and splitting it into a function per stage is how it stays readable; counting its functions made one root read as several, as the self-measurement's Wiring finding on `container.py` was | Todd, 2026-11-06, Issue#590 |
| One radar, carrying the fleet's packages | The Dependency check keeps reading the one radar the declaration names; a repository whose dependencies the fleet's radar already rings carries a row for each in its own radar, at the fleet's ring, naming the fleet as the source | A second radar read beside the named one would be a second, unreviewed source of rings; the self-measurement's 26 Dependency findings were pytest, hypothesis, Click, boto3 and botocore, each on the fleet's radar and absent from this repository's | Todd, 2026-11-06, Issue#590 |
| Nested declarations | A repository is declared by one `adherence.toml` at its root, one in each sub-project, or both; each governs its subtree with paths relative to its directory that cannot leave it; the governing declarations of a path are read as one, the union sections as a union, the single-valued sections as the nearest file's, a nearer file replacing a whole section only under `[override]`; a path with no governing declaration has no adherence and is coverage, never a Covered finding; a conflict, an override of nothing, or a plain single-valued section where one is already defined above, is a declaration that cannot be read; the declaration in force is settled per file, a declaration new at the head governs from the next change | The Covered check is tree-wide by design, so one root declaration that names two of a monorepo's packages lowers every change that creates a unit anywhere else, and a sub-project's design record cannot be named by a declaration that names another's; template-tools (PR#1058) could be judged but never gated. A declaration that lands with its sub-project is code-owned with it and names its one record. Scoping Covered to `[runtimes]` was rejected: it keeps the one file and makes the runtime list carry a meaning it was not given | Todd, 2026-11-07, Issue#695 |
| A record on main is approved | No record carries a status line or a status word: on main it is approved, off main it is not. Where this record says "absent or in draft" (the missing-record behavior, the coverage of Trace, Language, Change, Kept test and Record kept), read "absent or not on main"; `domain/records.py` counts every record at the target revision, which is that rule | A status word in a document is a second source of truth that drifts from the one that matters, the branch; the retrospective's drift walk found the wording and the code apart only in words | Todd, 2026-11-06, Issue#590 |
| No code scanning upload | The reusable workflow posts no SARIF to code scanning; the judge job keeps the SARIF as a run artifact and the verdict, the log report and the job summary are the whole PR surface. This record names no upload; where the architecture record says the SARIF is uploaded to code scanning and rendered at the line (its workflow row, PR surface row, Credentials row, the `upload-sarif` radar row and the Findings as SARIF decision), read "the findings are in the job summary and the run artifact" | A private repository without GitHub's paid Code Security add-on refuses the upload, and the owner ruled the add-on out, so an upload that failed the call over a cosmetic step (template-tools PR#1058, run 42310085996) would have kept every private consumer out of its gate | Todd, 2026-11-06, PR#694 |
| The hosted judge in CI (Q4, its CI clause; Issue#590) | The `ci` stage asks the hosted judge, Clef through the fleet's AI Gateway by `bin/decide`, for every caller that passes `ADHERENCE_OP_SA_TOKEN`: tds-utils, Skills and template-tools since 2026-11-07 (tds-utils PR#716, tds-internal PR#321, Skills PR#181, template-tools PR#1068). A fork's pull request never asks: it gets no secrets, and the callers skip it | The owner directed it on 2026-11-07: bind the hosted judge, through one secret and a dedicated vault. Until then every judged check was coverage in every consumer (435 of template-tools' 1090 unmeasured units on 2026-11-06). On tds-utils master's first judged run Clef answered: one judged finding, 163 abstentions (run 42349500786). Q4's cloud, consent and private-repository clauses stay open (Issue#720); the exposure the Security Considerations forbid, a same-repository PR author reading the judge's token, is Issue#719, a decision for the owner, and this row does not amend that section | Todd, 2026-11-07, Issue#590 |

---

## Open Questions

- **Q1 The name.** "Adherence" is this record's name for the component;
  the command has none. Rows it changes: the Overview and Ships where.
- **Q3 A repository without a design record.** Whether such a repository
  may adopt the suite at all, or adopts with Trace, Language, Change,
  Kept test and Record kept uncovered until a record exists. Rows it
  changes: Design records as input; the missing-record behaviors.
- **Q4 The judge off the laptop.** Whether a cloud session asks a hosted
  judge directly, or runs rule checks only. Whether a change from a
  contributor the owner does not trust can cause the judge to be asked at
  all. Who receives a unit's text when the judge is asked, whether the
  owner has consented to that, and whether a private repository may use a
  judge at all. Rows it changes: Where it runs; Security Considerations.
- **Q5 First adopters.** Which repositories are measured first; the
  candidates are this repository, template-tools and GammaGo, one per MVP
  language. Rows it changes: none here; the plan.
- **Q6 Judged checks at commit time.** Whether the hook ever asks the
  judge, within the commit-time bound, or leaves every judged check to CI
  and the agent. Rows it changes: Where it runs; the hook behavior.
- **Q7 Remediation cost.** Whether the report records what it took to
  close a finding, as Slater's proposed debt remediation index would.
  Rows it changes: Report; Future Considerations.
- **Q9 Paths the gate refuses.** A human amendment that removes a behavior
  or term (Record kept), a revert of a landed change, and a judged false
  positive in its own change all lower, and an exemption the change
  writes is inert for it. Whether the owner's bypass is the
  sanctioned route, whether the next report shows a bypassed landing as a
  notice, and what it records; or whether the suite grants another path.
  Rows it changes: Tradeoffs; Exemptions; Judging a change; the Declared
  and exemption behaviors.
- **Q12 A judged rerun.** Reproducibility is promised only for rule
  checks, so a required check can flip between verdicts on a CI retry of
  the same head against the same base. Whether a rerun reuses each judged
  answer so the verdict cannot flip. Whether the base's and the head's
  judged answers may be taken at different times. Rows it changes:
  Measurement; Judging a change; the judged behaviors; a retry behavior
  for the gate.

---

## Rejections

- **A score, per quality or per repository** -- a fraction over files,
  functions and design behaviors weighs incommensurable things, nets a
  fixed flaw against an introduced one, and hides which sensor tripped;
  Slater's maintainability index rose as the code got lazier. The
  findings are compared instead (Key Decisions, No score).
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
- **Drop tickets and floors** -- both were bounds on a score; without a
  score a ticket is an exemption landed in advance, which exemptions
  already are, and a floor is what the ratchet already does once a check
  is clean.
- **A Fakeable check** -- "the root receives its adapters as values"
  contradicts "the root is the one unit that constructs them"; Wiring and
  Swap already cover what it meant.
- **Honoring a change's whole declaration** -- a change could exempt what
  it broke; honoring only its widening cannot lower anything.
- **Pinning design records to the base** -- a behavior and its use case
  could never land together; Record kept covers the shrinking case.
- **Automatic fixing** -- the suite that judges a fix must not author it;
  the agent's loop already does the fixing with the report as input.
- **Test coverage percentage as a quality** -- the testing skill owns it,
  and it says nothing about whether a test asserts a design behavior.
- **Restating the rules in a skill instead of a tool** -- the sdlc and
  coding skills already state them, and nothing executes prose; the
  Skills repo recorded that mechanics in prose draw defects every review
  round.

---

- **One root declaration for a monorepo** -- Covered is tree-wide, so a
  root file that declares some packages lowers every change that creates
  a unit in the others, and one file cannot name each package's design
  record; the declaration lives with the sub-project instead (Key Decisions,
  Nested declarations).
- **Scoping Covered to the declared runtimes** -- it would have kept one
  root file and made `[runtimes]` carry a meaning it was not given; a
  sub-project's own declaration says the same thing where it belongs.

## Future Considerations

- **Ceremony ports** -- the concept asks to see a port with one
  implementation and no plausible second; a rule can count adapters, but
  "plausible second" needs the architecture record's seam rationale as
  input, so it waits on Change reading rationale, not only names.
- **Remediation cost** -- turns, time and lines to close a finding class,
  per Slater's proposed index; pending Q7.
- **A fleet view** -- the findings over time per repository in the LMDE
  observability stack, as a consumer of persisted reports.
- **More languages** -- Go and GDScript, as the fleet's code demands.
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
  how this record intends to be delivered, including how a judge is
  reached
- [LMDE.DESIGN.md](./LMDE.DESIGN.md) -- the platform the laptop stage is
  part of
- the coding skill, Section 1.2; the testing skill, Where behaviors come
  from; the decision-models skill -- the rules the checks execute
- Slater, T. (2025). Quantitative Analysis of Technical Debt and Pattern
  Violation in Large Language Model Architectures. arXiv 2512.04273
