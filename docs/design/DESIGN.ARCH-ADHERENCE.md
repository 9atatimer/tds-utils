# Architectural Adherence

> **Status:** DRAFT
> **Date:** 2026-10-24 (self-review panel findings folded in the same day)
> **Authors:** Todd Stumpf, Claude
> **Depends on:** [LMDE](./LMDE.DESIGN.md); the decide route, [DECIDE-ROUTE](./DECIDE-ROUTE.DESIGN.md) (DRAFT), for the laptop's judge; template-tools [ci.magic toolkit](https://github.com/Nine-At-A-Time-Media/template-tools/blob/main/docs/design/DESIGN.CI-MAGIC-TOOLKIT.md) for the CI judge's hand-off; template-tools [the data warehouse](https://github.com/Nine-At-A-Time-Media/template-tools/blob/main/docs/design/ARCHITECTURE.DATA-WAREHOUSE.md) for durable reports
> **Origin:** [concept: arch-adherence](../concepts/arch-adherence/CONCEPT.md); Slater, [arXiv 2512.04273](https://arxiv.org/pdf/2512.04273)

---

## Overview

Adherence is the suite that measures how well a repository's code keeps
the structure the SDLC asks of it: layered, hexagonal, domain-driven,
composable, injectable, behavior-driven, complete, on the tech radar, and
declared. It turns the coding skill's review-time tests into checks that
run, scores each quality, refuses a change that lowers a score, and names
every flaw well enough that an agent can fix it. It is product, not
tooling: the gate, the merge bot, the hooks and the agents all code
against its verdict.

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
- A repository declares its layers, runtimes and design records once, with
  the owner's approval. A change is judged under the declaration in force
  before it; its own declaration may widen what is checked, never narrow
  it.
- The design and architecture records are inputs: Trace and Language read
  the Behaviors table and the Domain Language, never a restatement, at the
  revision of the code they are compared against.
- A baseline per quality that only ratchets up on its own; a change that
  would lower it does not land, unless the owner accepts the drop with a
  reason that every later report shows.
- Findings carry provenance: a flaw a change introduced blocks it, a flaw
  that predates it is reported and does not. Scores are compared over the
  units both sides share, so deleting clean code moves nothing.
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
| A landing that bypasses the gate lowers the bar with no reason recorded | The gate is the only place a reason is demanded; bypassing it is the owner's act by definition, and the declaration is the owner's to change |
| New code must be declared in the change that adds it | Code the declaration does not cover is code the suite cannot see; widening coverage costs the author one line and can only add checks |
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
- **G3 Inconclusive never fails, and never raises.** An abstention, an
  unavailable judge, or a check that did not run never lowers a verdict on
  its own, and never raises one.
- **G4 Not run is loud.** A check that could not run is reported as
  coverage missing, with the reason. The absence of findings is never
  reported as adherence.
- **G5 Regression is refused.** A change that introduces a finding, or
  whose compared score on any quality falls below the baseline, or whose
  score is below a floor the repository had reached, gets the verdict
  lowered.
- **G6 The bar ratchets.** A change that lands with a raised score raises
  the baseline with nothing to configure. Lowering a baseline is an
  owner's act: a drop ticket with a reason, shown in every later report
  until the score regains what it was.
- **G7 Existing flaws do not block.** Every finding is marked introduced
  or existing. Only introduced findings, a fallen compared score and an
  unreached floor move a verdict. Deleting or renaming units introduces
  nothing.
- **G8 Findings are fixable.** A finding names the unit, the quality, the
  check, and the evidence. A layer finding also names the layer the unit
  is in and the layer it reached.
- **G9 One declaration, the owner's.** A repository states once which
  units are in which layer, which runtimes it has, where its design
  records are, which radar it is held to, and what it exempts; the
  declaration changes only with the owner's approval. A change is judged
  under the declaration in force before it, plus the coverage its own
  declaration adds. What its own declaration removes, exempts or accepts
  takes effect from the next change.
- **G10 Design records are read, not restated.** Trace reads the design's
  Behaviors table and the architecture record's use-case surface.
  Language reads the design's Domain Language. Each is read at the
  revision of the code it is compared against. The suite holds no copy
  of either, and a change that narrows an approved record introduces a
  finding.
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
- **G14 Commit time is bounded.** A pre-commit run ends within the
  commit-time bound, whatever an analyzer does. Checks that cannot run
  where somebody is waiting.
- **G15 Explanations on demand.** Any finding can be explained in prose.
  The explanation is labelled as such, changes no score and no verdict,
  and is produced by something that can act on nothing.
- **G16 Reports persist.** Every run's report is kept durably, so
  adherence over time, per repository and per quality, is a query.
- **G17 Exemptions are visible and reasoned.** An exemption carries a
  reason, appears in every report it affects, and an exemption a change
  adds is reported and inert for that change.
- **G18 The code under measurement is data.** The suite never executes
  the repository's code, and nothing in that code can instruct a judge or
  an explainer.
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

### The Qualities table

The quality set is closed by this record. Each check below is named in the
problem's language; the coding skill, Section 1.2, is the authority for the
nine that carry its names. Kind is R for a rule check and J for a judged
check; a check listed as R/J has a rule part and a judged part, and the
judged part runs only on what the rule part could not decide.

| Quality | Adherence means | Checks |
|---|---|---|
| Layered | Rules, workflow and wiring are three separate jobs | Trace (R): every design behavior resolves to one application unit, by the use-case surface's signature. Purity (R): no domain unit takes a port, a callable that does I/O, or a clock. Wiring (R): per declared runtime, exactly one unit names concrete adapters, that unit is in the composition-root layer, and no unit outside that layer names one. Anatomy (R): a file's regions run header, imports, constants, flags, predicates, helpers, flow, entry, in that order. Two jobs (J): a unit that does two of rules, workflow and wiring |
| Hexagonal | The core depends on no mechanism | Grep (R): no domain or application unit names a vendor, an SDK, the environment, the filesystem, the network, or a model id. Arrow (R): every import crosses inward and no import cycle exists. Swap (R): every port has at least one fake and the core imports only the port. Change (R): every seam the architecture record names exists as exactly one port, policy or parameter |
| Domain-driven | Each concept is named once, in the problem's words, with one owner | Language (R/J): every noun in a use-case signature is defined in the design's Domain Language under that spelling; the judged part asks whether two differently spelled nouns are one concept. Decision (J): a choice spread across conditionals on the same discriminant instead of one named policy. Boundary (R/J): a value type whose fields are written outside its owning unit; the judged part asks whether that write can break an invariant. Anemic (R): a type that is all fields and no behavior while its rules live elsewhere |
| Composable | A use case can be called by another with nothing in front | Values in and out (R): no use-case signature carries a wire format, an SDK type or an adapter handle. No nesting (R): no function defined inside another. Helpers take values (R): no pure helper takes a port or a callable |
| Injectable | Dependencies arrive at the flow function and never below it | Ports as keywords (R): every port a use case takes is a named dependency after the values. No self-wiring (R): no use case constructs an adapter. No reach (R): no use case or domain unit reads a global, a singleton, or the environment. Fakeable (R): the composition root receives its adapters as values, names a fake for every port it binds, and no unit below it names a concrete adapter |
| Behavior-driven | Every kept test asserts a design behavior through the public surface | Kept test (R): every design behavior has a test that calls its use case by the surface's signature. Then asserted (J): that test asserts the row's Then, not merely that nothing raised. Public surface (R): no test reaches past a use case into a helper or an internal. Real assertion (R): no test without an assertion and no placeholder assertion |
| Complete | The code does the work it claims to | Stub (R): no stub marker, placeholder body, or sleep standing in for work, in a non-test unit; the stub vocabulary is a parameter. Done (J): a unit whose body does not implement what its name and docstring claim. Hand-rolled (J): a primitive written by hand where a radar-adopted library provides it. Complexity (R): no function over the complexity ceiling. Duplication (R): no clone over the duplication ceiling |
| Radar-true | Every dependency is one the radar allows | Dependency (R): every dependency a change introduces is on Adopt or Trial of the radar the repository names. Edge only (R): every radar entry is imported from an adapter, never from the core |
| Declared | Every unit is seen, under a contract the change did not shrink | Covered (R): every unit the change creates is in a declared layer, by the declaration in force or by the change's own widening. Record kept (R): no design behavior and no Domain Language term is removed from an approved record |

Kept test and Then asserted together are the Trace test's other half: Trace
says the behavior has a home in the code; these say it has a home in the
suite. Declared is the suite's own quality: it makes the other eight
unavoidable.

### Units and layers

A unit is what a check is over: a file, a function, a type, a module, an
import edge, a design behavior, or a test. Every unit the declaration
covers is in exactly one layer: domain, application, ports, adapters,
composition root, or test. A unit the declaration does not cover is
unassigned; it is counted in coverage, never scored, and if the change
created it, Covered finds it.

Layers are not directories. A declaration may assign a whole directory, a
file, or a region of a file, so a one-file tool and a package are measured
alike (G12). A region is named by a marker the file carries or by the
lines it spans.

### The declaration

A repository declares, once, in one place:

- which units are in which layer, and which runtimes it has;
- where its design records are;
- which radar it is held to;
- its exemptions, each with a reason;
- its floors, if the owner has set any;
- its drop tickets, each with a reason.

The declaration changes only with the owner's approval (G9). A change is
judged under the declaration in force before it, with one addition: layer
assignments in the change's own declaration for units the declaration in
force does not cover are honored, because widening can only add checks.
Everything else a change's declaration does, removing or moving an
assignment, adding an exemption, setting a floor, writing a drop ticket,
takes effect from the next change. Every edit to the declaration is a
notice in the report, so a reviewer sees it beside the verdict.

When the declaration and the code disagree, for example a declared runtime
with no composition root, the suite reports the disagreement as a finding
and does not guess which is right. A declaration that cannot be read ends
the run as not run.

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

- a score per quality: the units that pass every check of that quality,
  as a fraction of the units that quality's checks covered;
- the findings, each with its kind, its provenance, and its evidence;
- the abstentions, per judged check;
- the notices: declaration edits, accepted drops, unreached floors, and
  anything else a reviewer should see that is not a finding;
- coverage: every unit and check that did not run, and why.

A judged check puts one bounded question about one unit to the judge and
gets back a probability for each allowed answer. The suite's threshold
policy turns that distribution into a finding, a pass, or an abstention;
the judge never decides that. A judged finding carries its confidence
(G2). The judge is given the unit as data to be judged, never as
instructions (G18).

A rule check is reproducible: the same code and the same declaration give
the same result on every machine.

### Judging a change

A change is judged by comparing its head's report with its base's. The
compared score for a quality is taken over the units both reports cover
and the units the change created; a unit the change deleted or that only
one side could check counts on neither side. That is what keeps a deletion
of clean code, or a judge that answered on one side only, from moving a
verdict (G3, G7).

| Verdict | Meaning |
|---|---|
| not run | The suite could not measure; the reason is reported |
| lowered | An introduced finding from a rule check or from a judged check above its threshold, a compared score below the baseline, or a score below a floor the repository had reached |
| inconclusive | Not lowered, and a judged check abstained or did not run on a unit the change touched, or a check that ran at the base could not run at the head |
| raised | Not lowered, not inconclusive, and at least one compared score rose |
| held | None of the above |

The rows are read in that order; the first that applies is the verdict.
Only lowered fails a gate. Inconclusive and not run never read as pass,
and inconclusive never ratchets (G3, G4).

Provenance: a finding is introduced when the unit it names is one the
change created or edited and the finding was absent before the change. A
renamed unit keeps its base identity, so its findings are existing.
Otherwise a finding is existing (G7).

The baseline per quality is the base's score. It rises when a raised
change lands. It falls past the gate only with a drop ticket: the owner's
statement, in the declaration, of the quality, the score it accepts, the
base it accepts it against, and the reason. A fall the ticket covers is a
notice, not a lowering, and the ticket stays in every later report until
the score regains what it was (G6). A ticket is honored only against the
base it names, so it cannot be written once and spent twice.

A floor is a bound the owner sets. It binds once the base's score is at or
above it: from then on a score below it is lowered whatever the baseline
says. Below it, the baseline comparison alone judges and the report says
the floor is not yet reached, so a floor set above today's score is a
target, not a wall.

### Findings and explanations

A finding names: the quality, the check, the kind, the unit, the evidence
(at most the offending line and its location), the provenance, and for a
layer check the layer the unit is in and the layer it reached (G8). The
same finding is produced in the terminal, the hook, CI and the agent's
self-review, and it carries a stable identity so the four can be joined
and so a rename does not make it new.

An explanation is prose about one finding, produced only when asked,
labelled as an explanation, and never an input to a score or a verdict
(G15). Whatever produces it reads the finding and the unit as data and
can act on nothing: no tools, no files, no network beyond the model it
asks. It may disagree with the finding; when it does, the finding stands
and the disagreement is shown.

### Where it runs

| Place | What runs | Bound |
|---|---|---|
| The laptop, on demand | Every check | None |
| The pre-commit hook | The rule checks over the staged change | The commit-time bound (G14), enforced on the whole run, so a slow analyzer ends the run rather than the bound |
| CI, as a required check | Every check over the pull request's change | The gate's own time |
| An agent's self-review | Every check over its diff, before the PR | None |
| A cloud session | The rule checks; judged checks when a judge is reachable (Q4) | None |

The same declaration, the same baseline, the same findings in each. A place
that cannot run a check reports it as coverage missing, never as a pass.

### Exemptions

An owner may exempt a unit from a check, or dismiss one finding, with a
reason. The reason is in the declaration and in every report the exemption
touches (G17). An exemption a change adds is a notice and is inert for
that change, so a change cannot exempt what it broke. No exemption can
exempt the Declared quality's checks.

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
| A second composition root is found | Given a declared runtime with two units that name concrete adapters, When Wiring runs, Then a finding names both |
| A missing composition root is a disagreement | Given a declared runtime with no unit that names concrete adapters, When Wiring runs, Then a finding says the declaration and the code disagree, and names the runtime |
| An adapter named below the root is found | Given a unit outside the composition-root layer that names a concrete adapter, When Wiring runs, Then a finding names the unit and the adapter |
| A file out of order is found | Given a file whose regions are not in the anatomy order, When Anatomy runs, Then a finding names the file and the first region out of place |
| A unit doing two jobs is judged | Given a unit that holds both rules and workflow, When Two jobs runs, Then the finding, pass or abstention carries a confidence |
| A port without a fake is found | Given a port with no fake behind it anywhere in the repository, When Swap runs, Then a finding names the port |
| A named seam is missing | Given a seam the architecture record names with no port, policy or parameter in the code, When Change runs, Then a finding names the seam |
| A foreign noun is found | Given a use-case signature with a noun the Domain Language does not define, When Language runs, Then a finding names the noun and the signature |
| Two names for one concept are judged | Given two nouns the Domain Language spells differently, When Language's judged part runs, Then the finding, pass or abstention carries a confidence |
| A scattered decision is judged | Given conditionals on the same discriminant in more than one unit, When Decision runs, Then the finding, pass or abstention carries a confidence |
| A foreign write is found | Given a value type whose field is written outside its owning unit, When Boundary runs, Then a finding names the type, the writer, and the owning unit |
| A foreign write is judged | Given a foreign write Boundary found, When Boundary's judged part runs, Then the finding, pass or abstention carries a confidence about the invariant |
| An anemic type is found | Given a type that is all fields while its rules live in another unit, When Anemic runs, Then a finding names the type and the unit holding its rules |
| A wire format in a signature is found | Given a use case whose signature carries a wire format, an SDK type or an adapter handle, When Values in and out runs, Then a finding names the parameter |
| A nested function is found | Given a function defined inside another in a non-test unit, When No nesting runs, Then a finding names both |
| A helper that takes a port is found | Given a pure helper that takes a port or a callable, When Helpers take values runs, Then a finding names the helper and the parameter |
| A port taken by position is found | Given a use case that takes a port before its values or without a name, When Ports as keywords runs, Then a finding names the use case and the port |
| A self-wired use case is found | Given a use case that constructs an adapter, When No self-wiring runs, Then a finding names the use case and the adapter |
| A reach is found | Given a use case or domain unit that reads a global, a singleton or the environment, When No reach runs, Then a finding names the unit and what it reached |
| A root that builds its own adapters is found | Given a composition root that constructs an adapter it binds, or binds a port with no fake in the repository, When Fakeable runs, Then a finding names the root and the port |
| A behavior with no kept test is found | Given a design behavior whose use case no test calls by the surface's signature, When Kept test runs, Then a finding names the behavior |
| A test that cannot fail is found | Given a test with no assertion, When Real assertion runs, Then a finding names the test |
| A test past the surface is found | Given a test that calls a helper or an internal instead of a use case, When Public surface runs, Then a finding names the test and what it reached |
| A Then not asserted is judged | Given a test that calls a behavior's use case, When Then asserted runs, Then the finding, pass or abstention carries a confidence |
| A stub is found | Given a non-test function whose body is a stub, When Stub runs, Then a finding names the function |
| An unimplemented claim is judged | Given a function whose body does not do what its name and docstring claim, When Done runs, Then the finding, pass or abstention carries a confidence |
| A hand-rolled primitive is judged | Given a function that implements what a radar-adopted library provides, When Hand-rolled runs, Then the finding, pass or abstention carries a confidence |
| A function over the complexity ceiling is found | Given a function whose complexity is over the ceiling, When Complexity runs, Then a finding names the function and the ceiling |
| A clone over the duplication ceiling is found | Given two stretches of code alike beyond the ceiling, When Duplication runs, Then one finding names both |
| A disallowed dependency is found | Given a change that introduces a dependency not on Adopt or Trial of the declared radar, When Dependency runs, Then a finding names the dependency and the ring it is on, or that it is absent |
| A radar entry in the core is found | Given a domain or application unit that imports a radar entry, When Edge only runs, Then a finding names the unit and the entry |
| An undeclared new unit is found | Given a change that creates a unit no declaration assigns to a layer, When Covered runs, Then a finding names the unit and the verdict is lowered |
| A widening is honored | Given a change that creates a unit and assigns it a layer in its own declaration, When the change is judged, Then the unit is checked under that layer and Covered finds nothing |
| A narrowed record is found | Given a change that removes a behavior or a term from an approved record, When Record kept runs, Then a finding names the record and what was removed |
| A record is read with its code | Given a change that adds a behavior to the record and its use case in the same change, When Trace runs, Then there is no Trace finding for it |
| A one-file tool is measured | Given a file whose declaration assigns its regions to layers, by marker or by lines, When a run is asked for, Then the layer checks score its regions as they would score packages |
| An uncovered language is reported | Given a unit in a language with no analyzer, When a run is asked for, Then coverage names the unit and the language, and no score counts it as passing |
| A missing design record is reported | Given a declared repository whose design record is absent or in draft, When a run is asked for, Then Trace, Language, Change, Kept test and Record kept report coverage missing and name the record, and the other qualities are scored |
| A missing record on both sides is not inconclusive | Given a repository whose design record is missing at the base and at the head, When a change is judged, Then the missing record alone does not make the verdict inconclusive |
| An untraceable row is a finding against the record | Given a behavior row with no nameable action or observation, When Trace runs, Then a finding names the row and the record |
| An undeclared repository is measured | Given a repository with no declaration, When a run is asked for, Then the checks that need no declaration run, and coverage names every check that needed one |
| An unreadable declaration is not run | Given a declaration that cannot be read, When a run is asked for, Then the verdict is not run and the report names the error |
| A change that raises is raised | Given a change on which one compared score rose and none fell and no rule check found an introduced flaw, When it is judged, Then the verdict is raised |
| A change that lowers is lowered | Given a change on which one compared score fell below the baseline, When it is judged, Then the verdict is lowered and the report names the quality |
| A floor holds | Given a quality whose base score is at or above the owner's floor, When a change takes it below the floor, Then the verdict is lowered and the report names the floor |
| An unreached floor is a target | Given a quality whose base score is below the owner's floor, When a change raises it but not to the floor, Then the verdict is raised and the report says the floor is not yet reached |
| An introduced flaw lowers | Given a change that creates a unit a rule check fails, When it is judged, Then the verdict is lowered and the finding is marked introduced |
| An existing flaw does not block | Given a unit a rule check failed before the change and the change did not touch it, When the change is judged, Then the finding is marked existing and the verdict is not lowered by it |
| A rename introduces nothing | Given a unit with an existing flaw that the change renames and does not edit, When the change is judged, Then its finding is marked existing and keeps its identity |
| Deleting clean code moves nothing | Given a change that only deletes units with no findings in a repository with existing flaws, When it is judged, Then no compared score falls and the verdict is held |
| An abstention is inconclusive | Given a change whose only unresolved item is a judged check that abstained on a unit it touched, When it is judged, Then the verdict is inconclusive, never lowered |
| An unavailable judge is inconclusive, never raised | Given no judge reachable at the head and a judge that answered at the base, When a change is judged, Then every judged check reports coverage missing, the judged units count on neither side, and the verdict is inconclusive at best |
| A suite that cannot run says so | Given a repository the suite cannot measure, When a run is asked for, Then the verdict is not run with the reason, and nothing reads as a pass |
| The baseline ratchets up | Given a change with the verdict raised, When it lands, Then the baseline for each risen quality is the new score, with nothing configured |
| A drop ticket accepts a fall | Given a change whose declaration carries a drop ticket naming its base, the quality and a reason, When its compared score falls no further than the ticket accepts, Then the fall is a notice with the reason and the verdict is not lowered by it |
| A drop ticket is spent once | Given a drop ticket naming one base, When a later change against a different base falls on that quality, Then the ticket does not cover it |
| A drop ticket is shown until regained | Given an accepted drop, When later reports are produced, Then each shows the ticket and its reason until the quality's score regains the score before the drop |
| A change cannot narrow its own declaration | Given a change that removes an assignment, adds an exemption, sets a floor or writes a ticket, When it is judged, Then it is judged as if that edit were absent, and the edit is a notice |
| An exemption carries its reason | Given an exempted unit, When a run reports, Then the exemption and its reason appear beside the check it silenced |
| An added exemption is inert for its change | Given a change that adds an exemption for a flaw it introduces, When it is judged, Then the flaw lowers the verdict and the exemption is a notice |
| The Declared quality cannot be exempted | Given a declaration that exempts Covered or Record kept, When a run is asked for, Then the exemption is refused and reported |
| A finding is fixable | Given any finding, When an agent reads it, Then it holds the quality, the check, the kind, the unit, the evidence and the provenance, and a layer finding names the layer reached |
| The same finding everywhere | Given one flaw, When the laptop, the hook, CI and the self-review each run, Then each reports a finding with the same identity |
| The hook ends within its bound | Given a staged change and an analyzer that does not return, When the pre-commit hook runs, Then the run ends within the commit-time bound, the checks that did not finish are coverage, and the commit is not blocked past the bound |
| An explanation changes nothing | Given a finding, When an explanation is asked for, Then prose labelled as an explanation is returned and the score and verdict are unchanged |
| A disagreeing explanation shows both | Given an explanation that disagrees with its finding, When it is shown, Then the finding stands and the disagreement is visible |
| The judge is given data | Given a unit whose text addresses the judge, When a judged check runs, Then the text is judged as the unit's content and nothing in it changes which question is asked |
| The explainer can act on nothing | Given a unit whose text instructs the explainer to read a file or run a command, When an explanation is asked for, Then nothing is read or run and the explanation is returned or refused |
| Repository code is never run | Given any run, When it completes, Then no code from the repository under measurement was executed |
| A report persists | Given a completed run, When it reports, Then the report is kept durably with the repository, the change and the time, and a failure to keep it never changes the verdict |
| A base report is reused only when comparable | Given a kept report for the base made under a different suite, declaration, analyzer set or judge availability, When a change is judged, Then the base is measured again rather than compared to it |
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
| requested | not run | the suite cannot proceed | the declaration cannot be read, no analyzer for any unit, or the repository cannot be read |
| declared, undeclared | measured | every check that can run has run | always |
| measured | reported | the report is written and, for a change, the verdict is set | always; a failure to persist is noted, not fatal |

### The baseline

```
+--------+    +------+    +-----------+
| absent |--->| set  |<-->| ratcheted |
+--------+    +------+    +-----------+
                 ^              |
                 |  drop ticket, with reason
                 +--------------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| absent | set | the owner adopts the suite on the repository | the first report's scores become the baseline |
| set, ratcheted | ratcheted | a change with the verdict raised lands | the risen scores become the baseline |
| set, ratcheted | set | a change with an accepted drop lands | a drop ticket names that base and a reason; the ticket is shown until the old score is regained |

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
- **Analyzer.** Whatever performs rule checks for one language.
- **Analyzer set.** The languages a run can analyze.
- **Explanation.** Prose about one finding, produced on request by
  something that can act on nothing. Invariant: never an input to a score
  or a verdict.
- **Unit.** What a check is over: a file, a function, a type, a module, an
  import edge, a design behavior, or a test.
- **Layer.** Domain, application, ports, adapters, composition root, or
  test. Invariant: a covered unit is in exactly one.
- **Port.** A named interface the core owns at one axis of change; the
  architecture record's seam list names them.
- **Fake.** An in-memory implementation of a port, for tests and for the
  Fakeable check.
- **Seam.** An axis of change the architecture record maps to one port,
  policy or parameter.
- **Use case.** One application-layer function carrying one or more
  design behaviors, with the signature the use-case surface gives it.
- **Composition root.** The one unit per runtime that names concrete
  adapters.
- **Runtime.** A declared entry the repository can be run as, each with
  one composition root.
- **Region.** A span of one file assigned to one layer, named by a marker
  the file carries or by the lines it spans.
- **Declaration.** A repository's statement of its layers, runtimes,
  design records, radar, exemptions, floors and drop tickets. Invariant:
  changes only with the owner's approval; a change is judged under the one
  in force before it plus its own widening.
- **Widening.** A layer assignment in a change's own declaration for a
  unit the declaration in force does not cover. Invariant: honored for the
  change itself; it can only add checks.
- **Design record.** The approved design and architecture records of the
  code under measurement, read for their Behaviors table, Domain
  Language, use-case surface and seam list, at the revision of the code.
- **Design behavior.** One row of a design record's Behaviors table.
- **Radar.** The tech radar the declaration names, read for its rings.
- **Run.** One measurement of a repository or a change.
- **Target.** What a run measures: a repository at one revision, its
  working tree, or its staged index.
- **Change.** A repository's head against its base, or a working tree or
  staged index against its base.
- **Report.** A run's outcome: the scores, findings, abstentions, notices
  and coverage, and for a change the verdict, the compared scores and the
  provenance of each finding.
- **Score.** Per quality, the units that pass every check of that quality
  as a fraction of the units covered. Invariant: between zero and one.
- **Compared score.** Per quality, the score taken over the units both the
  base and the head reports cover, plus the units the change created.
  Invariant: a deleted unit, and a unit only one side could check, is on
  neither side.
- **Finding.** One check failing on one unit: the quality, check, kind,
  unit, evidence, provenance, and for a layer check the layer reached.
  Invariant: carries a stable identity that survives a rename.
- **Evidence.** The location and at most the offending line.
- **Provenance.** Introduced, when the change made the finding appear on a
  unit it created or edited; else existing.
- **Abstention.** A judged check's answer when its probabilities fall in
  the abstention band. Counted as inconclusive, never as a pass or a
  finding.
- **Notice.** Something a reviewer should see that is not a finding: a
  declaration edit, an accepted drop, an unreached floor, a report not
  kept. Invariant: never moves a verdict.
- **Coverage.** Every unit and check a run did not perform, with the
  reason.
- **Baseline.** The base's score per quality that the change is held to.
  Invariant: rises on its own, falls past the gate only by a drop ticket.
- **Drop ticket.** The owner's statement in the declaration accepting a
  fall on one quality against one named base, with a reason. Invariant:
  covers one base; shown until the score regains what it was.
- **Floor.** An owner-set score per quality. Invariant: binds once the
  base's score reaches it; a target until then.
- **Verdict.** Not run, lowered, inconclusive, raised, or held, read in
  that order. Invariant: only lowered fails a gate; only raised ratchets.
- **Exemption.** An owner's statement that a unit is not checked by one
  check, or that one finding is dismissed, with a reason. Invariant:
  cannot cover the Declared quality; inert for the change that adds it.
- **Policies.** The suite's thresholds, abstention bands, vocabulary and
  limits, as one value a run is given.
- **Recorded.** The outcome of keeping a report: kept, or not kept with the
  reason. Invariant: never changes a verdict.
- **Owner.** The human who owns the repository under measurement.

---

## Parameters

| Bound | Constraint |
|---|---|
| Threshold, per judged check | The rule over the judge's probabilities above which a judged check is a finding; chosen from a labelled set per check, never by eye |
| Abstention band, per judged check | The probabilities that are neither a finding nor a pass; non-empty for every judged check |
| Commit-time bound | How long a pre-commit run may take in total; short enough that a developer does not bypass it |
| Analyzer bound | How long one analyzer may run inside a bounded run; shorter than the commit-time bound |
| Judged-check budget, per run | How many judged questions one run may ask; large enough for a typical change, bounded so a large change degrades to abstentions and coverage, never to a hung run |
| Complexity ceiling | The per-function complexity above which Complexity finds; a ratchet, never raised to fit a file |
| Duplication ceiling | The clone size above which Duplication finds; a ratchet |
| Floor, per quality | Set by the owner, or absent |
| Evidence bound | How much of a unit a finding may quote; at most the offending line |
| Analyzer set | The languages the suite measures; at least Python, TypeScript with JavaScript, and shell |
| Stub vocabulary | The markers Stub recognises; extended by the owner, never emptied |
| Region markers | The marker forms that name a region and the layer each maps to; extended by the owner |
| Design-record status that counts | Which statuses make a record readable for Trace and Language; at least APPROVED and IMPLEMENTED |

---

## Security Considerations

- **The code under measurement is untrusted.** A unit can carry text
  addressed to the judge or the explainer. The suite performs only static
  reading of the repository and never imports, builds or executes it
  (G18). A judged question is fixed by the suite; the unit is its data.
  Neither the judge nor the explainer has any way to act: no tools, no
  files, no network beyond the model asked.
- **A change can try to rewrite its own bar.** The declaration, the
  baseline and the exemptions a change is judged under are the ones in
  force before it; its own declaration can only widen (G9, G17). The edit
  itself is a notice.
- **A change can try to write outside the bar.** A unit the change
  creates that no declaration covers is a Covered finding, and lowers.
- **A change can try to shrink the contract.** Removing a behavior or a
  term from an approved record is a Record kept finding, and lowers.
- **An unavailable judge must not open the gate.** A judge that cannot be
  reached yields coverage missing and at best inconclusive, never a pass
  or a raised verdict (G3, G4).
- **The suite holds no credential of its own on the laptop.** Asking the
  judge there is done the way every local tool asks. In CI the judge's
  credential is never in the environment of anything the suite spawns.
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

Two stages: the owner's laptop, as part of the LMDE contract, and the
adopting repositories' CI as a required check. A cloud agent session runs
it on demand. No nonprod stage; the runbook names the stand-in.

---

## Key Decisions

| Decision | Choice | Rationale | Origin |
|---|---|---|---|
| Product or tooling | Product: design, architecture and as-built records | The gate, the hooks, the merge bot and the agents code against its verdict, so it is not self-contained | the sdlc skill, Product or tooling |
| The qualities | A closed set of nine, each defined by an SDLC rule, the ninth being the suite's own Declared | The suite executes the skills' rules; it does not invent its own. Declared makes the other eight unavoidable | Todd, 2026-10-24 (concept); the coding skill, Section 1.2; self-review panel 2026-10-24 |
| Kinds of check | Rule, judged, explanation; told apart in every report | A fact and a judgement fail differently and are trusted differently | the decision-models skill, The ladder |
| Inconclusive never fails and never raises | An abstention or an unrun check is at worst inconclusive and at best inconclusive | A forced low-confidence verdict fails clean changes; a raise on missing coverage ratchets a number nobody measured | ci.magic's inconclusive verdict; Slater's maintainability paradox; self-review panel 2026-10-24 |
| The bar | A per-repository, per-quality baseline that ratchets up on its own and down only by a drop ticket | A fixed bar nobody clears is switched off; a ratchet holds; a ticket makes the owner's reason part of the record | the sdlc skill, law 11; self-review panel 2026-10-24 |
| What a score comparison sees | The units both sides cover and the units the change created | Deleting clean code is not regression, and a judge that answered on one side only is not a rise | self-review panel 2026-10-24 |
| Provenance | Introduced blocks; existing reports; a rename keeps identity | A change is judged on what it did | Todd, 2026-10-24 (concept, gating stories); self-review panel 2026-10-24 |
| The declaration's source | The one in force before the change, plus the change's own widening; the owner approves every change to it | A change that could narrow its own judge judges nothing; one that can only widen adds checks | template-tools ci.magic toolkit, G3; self-review panel 2026-10-24 |
| Design records | Read as input at the code's revision, never copied; narrowing an approved record is a finding | A copy drifts and becomes a second, unreviewed design; a record pinned to the base could not be grown with its code | the sdlc skill, laws 2 and 3; self-review panel 2026-10-24 |
| Floors | Bind once reached; a target until then | A floor above today's score would make every change unlandable | self-review panel 2026-10-24 |
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
  may adopt the suite at all, or adopts with Trace, Language, Change,
  Kept test and Record kept uncovered until a record exists. Rows it
  changes: Design records as input; the missing-record behaviors.
- **Q4 The judge off the laptop.** Whether a cloud session asks a hosted
  judge directly, as the decide client does today, or runs rule checks
  only. Rows it changes: Where it runs.
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
- **A whole-repository score as the thing compared** -- it falls when
  clean code is deleted, the same property the index was rejected for; the
  compared score is over shared and created units.
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

## Future Considerations

- **Ceremony ports** -- the concept asks to see a port with one
  implementation and no plausible second; a rule can count adapters, but
  "plausible second" needs the architecture record's seam rationale as
  input, so it waits on Change reading rationale, not only names.
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
  part of
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
