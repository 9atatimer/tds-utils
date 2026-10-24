# Stories: measuring

> Part of [CONCEPT.md](CONCEPT.md). Phase 1 -- not acceptance criteria.

- As a developer, I can run one command on a repository and see, per
  quality, how much of the code adheres and which files do not.
- As a developer, I can see that the domain imports nothing concrete: no
  vendor, no SDK, no environment, no filesystem, no model id.
- As a developer, I can see that every import crosses inward and that
  nothing is circular.
- As a developer, I can see that rules, workflow and wiring are three
  separate jobs, and which file is doing two of them.
- As a developer, I can see that every behavior in the design record has
  one use case in the code, and which rows have none.
- As a developer, I can see that every use case has a kept test that
  asserts its design row's Then, and which do not.
- As a developer, I can see that the nouns in the code are the nouns in
  the design record, and where a concept has two names.
- As a developer, I can see where a decision is spread across conditionals
  instead of named once.
- As a developer, I can see where a function was stubbed, left as a TODO,
  or had a sleep stand in for the work it was asked to do.
- As a developer, I can see where a change introduced a dependency the
  tech radar does not allow.
- As a developer, I can see where a port has one implementation and no
  plausible second, so I can ask whether it is ceremony.
- As a developer, I can tell a measurement that is a fact from one that is
  a judgement with a confidence attached.
- As a developer, I can see how adherence has moved over the life of the
  repository, not just where it stands today.
- As Todd, I can see adherence across every repository in the fleet in one
  place.
- As the author of the coding skill, I can point at the suite's output
  instead of restating the mechanical tests in prose.
