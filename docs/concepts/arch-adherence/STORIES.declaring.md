# Stories: declaring

> Part of [CONCEPT.md](CONCEPT.md). Phase 1 -- not acceptance criteria.

- As a repository owner, I tell the suite once which of my code is domain,
  application, ports, adapters and composition root, and it holds me to
  it.
- As a repository owner, I point the suite at my design and architecture
  records, and it reads the Behaviors table and the Domain Language from
  them rather than from me.
- As a repository owner, a one-file tool that keeps its layers as regions
  of one file is measured the same way as a package that keeps them as
  directories.
- As a repository owner, a repository with Python, TypeScript and shell in
  it is measured by one suite, not three.
- As a repository owner, I can adopt the suite on a repository that does
  not yet adhere, see where it stands, and ratchet from there without
  first fixing everything.
- As a repository owner, a change cannot rewrite the declaration it is
  judged under.
- As a developer, when the declaration and the code disagree, the suite
  tells me which, and does not guess.
- As the author of a design record, the suite tells me when a behavior row
  is written in a way nothing could trace to a function.
