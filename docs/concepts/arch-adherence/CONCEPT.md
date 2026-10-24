# Architectural Adherence

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-24  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

We are going to create some tools in the LMDE that are going to be helpful
for all of our coding efforts: a suite of tools to measure architectural
adherence, as suggested by Slater's paper on technical debt and pattern
violation in LLM-generated code
([arXiv 2512.04273](https://arxiv.org/pdf/2512.04273)).

The paper prompted several models to build one microservice under strict
hexagonal constraints and then tempted them with a performance request. The
weaker models imported the database driver straight into the domain
("hallucinated coupling"), padded the structure with hand-rolled primitives
("hallucinated complexity"), and left `pass` and `# logic goes here` where
the business logic should have been ("omission debt"). The proposed cure is
architecture as a guardrail: a symbolic, rule-based system that lints the
output and feeds the violation report back to the agent until the structure
holds. That is the tool we want, built for our own code and our own rules.

The suite should ensure that the code remains:

- layered
- domain driven
- Clean/Hexagonal
- composable
- dependency injectable
- behavior driven
- and the rest of what the SDLC asks of code

according to the principles of the SDLC. Those principles are already
written down: the sdlc skill's laws, the coding skill's three axes and their
mechanical tests (Grep, Swap, Arrow, Change; Trace, Purity, Wiring;
Decision, Language, Boundary), the testing skill's rule that a kept test
asserts a design behavior's Then. Today every one of those tests is a
review-time opinion. Nothing executes them, so they hold only as well as the
reviewer's attention on the day, and an agent that drifts reads as a passing
suite and a clean review.

We want to utilize the best open-source off-the-shelf analyzers, as well as
Jev- and Clef-class decision models, and our own home-grown tooling, to
prevent regression in quality with code changes and to identify flaws. A
change that lowers adherence should not land. A flaw that is already there
should be named, with the file and the rule, so an agent or a human can fix
it.

## Story sets

| File | Theme |
|---|---|
| STORIES.measuring.md | what is measured, per quality, and what a reader sees |
| STORIES.gating.md | a change that would lower adherence does not land |
| STORIES.fixing.md | a flaw is named well enough that an agent can repair it |
| STORIES.declaring.md | how a repository tells the suite what its architecture is |

## Notes

**Settled in session (Todd's words):**

- The tools live in the LMDE and serve all of our coding efforts.
- The suite measures architectural adherence, as the paper suggests.
- The qualities: layered, domain driven, Clean/Hexagonal, composable,
  dependency injectable, behavior driven, "etc", per the SDLC's principles.
- Three sources of judgement, together: the best open-source analyzers,
  Jev/Clef decision models, and our own home-grown tooling.
- Two purposes: prevent regression in quality with code changes, and
  identify flaws.
- This pass produces the concept, design and architecture for every listed
  quality, ready for BDD-red definition.

**Leans on:**

- The coding skill, Section 1.2 -- the mechanical tests the suite would
  execute. The sdlc skill, laws 5, 6, 7, 8 and 11.
- The approved design records of the code under measurement: the
  Behaviors table and the Domain Language are what Trace and Language are
  checked against. A repo with no design record has nothing for those two
  checks to read.
- `bin/decide` and the decide-route concept
  (`docs/concepts/decide-route/`), the way local tools already put a
  bounded question to a decision model; the decision-models skill, which
  says when a judgement belongs to rules, a decision model, or a
  generative model.
- ci.magic and its toolkit (template-tools
  `docs/design/DESIGN.CI-MAGIC-TOOLKIT.md`), the existing place a
  repository's own checker is handed to a judge in CI.
- The gates skill's law that a gate is cleared before it is moved.
- The fleet data warehouse (template-tools
  `docs/design/ARCHITECTURE.DATA-WAREHOUSE.md`), where measurements could
  accumulate so "did this get worse" becomes a query.

**Still open (nobody's yet):**

- The name. "Arch adherence" is the folder; the tool has no name.
- Which repositories measure first, and whether a repository with no
  design record is measured at all or only on the checks that need none.
- Where a change is judged: in the pre-commit hook, in CI, by the agent
  before it opens the PR, or all three.
- Whether a cloud session can ask a decision model for the judged checks,
  or only a laptop can.
- Whether a score is a number anyone compares across repositories, or
  only against the same repository's past.
- Whether the paper's follow-on measure, the cost of remediating a
  flagged violation, is worth tracking from the start.
