# Stories: gating

> Part of [CONCEPT.md](CONCEPT.md). Phase 1 -- not acceptance criteria.

- As a developer, I learn before I push that my change lowered adherence,
  and on which quality.
- As a reviewer, I see on the pull request whether the change raised,
  held or lowered adherence, before I read the diff.
- As a repository owner, a change that lowers adherence does not land
  unless I say so.
- As a repository owner, a change that raises adherence raises the bar
  for the next one, with nothing to configure.
- As a repository owner, I can exempt a file or a finding with a reason,
  and the reason is visible wherever the exemption takes effect.
- As a developer, a flaw that was already there before my change does not
  block my change; it is reported as existing, not as mine.
- As a developer, a judgement the suite was not confident about never
  fails my change on its own.
- As a developer, a suite that could not run, because a tool or a model
  was unavailable, says so loudly and never reads as a pass.
- As a developer, the suite runs in the time I am willing to wait at a
  commit, and the slower checks run where I am not waiting.
- As the merge bot, the suite is one more required check, and nothing
  about me changes.
- As an agent, I run the suite over my own diff before I open the pull
  request, the way I run the tests.
