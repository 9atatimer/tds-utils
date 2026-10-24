# Stories: fixing

> Part of [CONCEPT.md](CONCEPT.md). Phase 1 -- not acceptance criteria.

- As an agent, a finding names the file, the line, the quality, the rule
  it broke, and the evidence, so I can fix it without re-deriving the
  rule.
- As an agent, a finding tells me which layer the offending unit belongs
  to and which layer it reached into, so the fix is a move, not a guess.
- As an agent, I can feed the report back into my own loop and re-run
  until the structure holds, the way the paper's self-correcting agent
  does.
- As an agent, I can ask for an explanation of a finding in prose when the
  rule alone is not enough, and I know the explanation is not the verdict.
- As a developer, I can tell a finding my change introduced from one that
  predates it.
- As a developer, I can see the finding in my editor, in the terminal, and
  on the pull request, and it is the same finding in all three.
- As a developer, a finding that turns out to be wrong can be told so,
  with a reason, and the suite learns nothing from that on its own.
- As Todd, I can see which rules fire most, and on which repositories, so
  I know which lesson to put in a skill.
- As Todd, I can see what it cost to remediate a class of flaw, so I know
  which flaws are worth preventing earlier.
