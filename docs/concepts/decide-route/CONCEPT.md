# Decide Route

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-16  **Author:** Todd Stumpf (captured with AI assistance)
> **Issue:** Issue#382

## The idea

How do we make local vs hosted as streamlined as possible for local tools?

Decision models are useful to more and more of what runs on my laptop:
the ocrinator's page judgements, git hooks, local ci-magic runs, agents
asking a quick yes/no. Today each one has to know where the model lives
-- hosted Clef through the fleet's AI Gateway, with a credential pulled
from 1Password on every call, or a local server somewhere -- and each has
to be told again when that changes.

I want one door on the laptop for decisions. A local tool asks a
decision question at one place, the same way every time, holding no
credential of its own, and gets typed probabilities back. Whether the
answer came from Cloudflare or from a model running on this machine is a
choice made once, not re-plumbed into every tool. Hosted works from day
one; a local model joins later as one more thing behind the same door.

The door sits with everything else that faces local services: the LMDE
proxy layer.

## Story sets

| File | Theme |
|---|---|
| STORIES.calling.md | the tools that ask, and what asking is like for them |
| STORIES.operating.md | Todd, choosing where answers come from and seeing what it costs |

## Notes

**Settled in session (Todd's words):**

- The question: "how do we make local vs hosted as streamlined as possible
  for local tools?"
- "Okay. I'm convinced." -- to the proposal recorded on Issue#382: one
  door on the LMDE proxy layer that local tools speak to, the model they
  name deciding hosted or local, no tool holding a credential, no silent
  switch between hosted and local, cloud sessions unchanged.
- "Let's create a concept/design/arch/as-built/bdd/impl/release chain for
  this and get it up as an MVP."

**Leans on:** the LMDE proxy layer (live since 2026-10-13,
`docs/arch/proxy-layer/`); `bin/decide`, which already reaches hosted Clef
(`docs/ops/decide.md`); the decision arena concept
(`docs/concepts/decision-arena/`), which becomes a later local backend.

**Still open (nobody's yet):**

- The name. "Decide route" is the working name.
- Whether a tool can ever ask for "whichever is available".
- What a tool off the laptop -- a cloud session -- does; today it calls
  hosted directly.
