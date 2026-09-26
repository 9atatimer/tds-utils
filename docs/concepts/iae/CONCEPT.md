# Integrated Authoring Environment (IAE)

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-09-26  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

An Integrated Authoring Environment that helps an author produce written
works at a furious pace. Everyone in the world is writing one right now;
this one will be mine. My use will be pointless fantasy stories. Others
may find it useful for technical writing, serious literature, or their
kinky fantasy stories.

Like an IDE, it is a panel of tools that assist the would-be author to
produce good product. It includes not just the composition primitives but
tools for tracking plot, tempo, truths about characters, AI assistants,
drama-visualization graphs (hello, Mr. Vonnegut), et cetera.

It really looks like an IDE. You navigate your filesystem, because an
authoring effort involves lots of files -- not just the writing, but a
bunch of OTHER files of different formats that cut across the writing in
many different directions: emotional pacing charts, tone maps, character
and scene bibles, skills and prompts for the AI, piles of reference
material, tone and voice examples, maybe pictures and videos. It's a whole
thing.

Tools across the top. Tabs that change the left-hand panels. Down the
right-hand side, all the AI agent panels. In the middle, your favorite
writing tool, with enough plugins to integrate with the IAE -- easy for
emacs, probably easy for vi, presumably doable for Word.

You can ask the agents to do things. Some agents watch your work and toast
you with observations: "This contradicts Y." "X wouldn't say that because
he doesn't know."

An AI helps you get set up. You just have a conversation with it, and it
sets all the details.

All the ai-author concepts are in: knowledge bases, scene flow, dramatic
notes, storyboarding, act structure -- and the tooling to fill them in by
hand or with AI assistance.

The thing that slows the writing down today is the writing -- the literal
words, the authoring part. Writing dialog is just pulling teeth.

I want to work in terms of boundaries, narratives, emotional curves,
details, and moments. I want to use my words to define the structure of
the work, then stream-of-consciousness my ideas, dictation-like, into a
file -- and have it ground up, pulled out, and made to fit the constraints
I've set, to produce a compelling story.

Like ai-author in emacs: I write what I want to write, mark out the areas
I don't want to write, and LLMs help fill those in -- in my own voice,
with my own ideas, faster than I could ever write.

A manuscript isn't a single revision. That's the way paper works, not
electricity. Every revision, scene, draft, and vignette is kept --
revisions, variations, rewrites -- and all of it is selectable by a click:
swappable, composable, blended. You can go back to an earlier revision,
keep the tone, keep a phrase, strike through a line, make a note to be
more loving, salty, truthful, deceitful, et cetera. And the IAE helps you
synthesize, analyze, and evaluate the options: "Should Joe die here, or
in Act 3?" "Should she say yes? Fuck no? Hell no? Maybe?" The writing
tools help consider all those possibilities.

We're taking writing to the next level.

When technical writing, I want the same thing, plus guardrails that make
sure I don't make mistakes.

I want "observability" on my writing: something that can be monitored,
adjusted, and AI-influenced, to produce a final result that is "Green".
Green means it is meeting all quality bars: it is consistent, matches the
narrative arcs, is correct, gets positive marks from the AI reviewers,
stays on-tone and on-voice, et cetera.

## Story sets

| File | Theme |
|---|---|
| STORIES.composing.md | structure in my words, ideas dumped raw, the prose filled in for me |
| STORIES.variants.md | nothing is a single revision: every version kept, swappable, blended, weighed |
| STORIES.observability.md | watching the writing move toward "Green", and guardrails |
| STORIES.workspace.md | the IDE-shaped shell: toolbar, tabs, left and right panels, the editor in the middle |
| STORIES.corpus.md | the many files, of many formats, that cut across the writing |
| STORIES.agents.md | agents you ask, and agents that watch and speak up |
| STORIES.craft.md | the story-building tools: knowledge bases, scene flow, structure, pacing |
| STORIES.setup.md | getting set up by talking to an AI |

## Notes

**Settled in session (Todd's words):**

- The existing emacs tooling (`emacs/dot.emacs.d/elisp/tds-v3-ai-author*.el`)
  is illustrative only -- "wood and stone." The IAE is "glass and steel."
- It looks like an IDE: toolbar across the top, tabs driving the
  left-hand panels, AI agent panels on the right, the author's own editor
  in the middle.
- The editor is the author's choice, integrated by plugin; emacs is Todd's.
- There are two kinds of agent: ones you ask, and ones that watch.
- Setup is a conversation with an AI.
- The biggest drag on pace today is the writing itself: the literal
  words. Dialog is pulling teeth.
- The author's words define structure (boundaries, narratives, emotional
  curves, details, moments); raw ideas are dictated in; LLMs produce the
  prose to fit, in the author's voice and with the author's ideas.
- The ai-author loop carries over as intent: write what I want, mark what
  I don't, have it filled.
- A manuscript is not a single revision. Every revision, scene, draft,
  vignette, variation, and rewrite is kept and selectable by a click --
  swappable, composable, blended.
- The IAE helps synthesize, analyze, and evaluate the alternatives,
  including story-level choices ("Should Joe die here, or in Act 3?").
- Technical writing gets the same loop plus guardrails against mistakes.
- The writing has "observability" and a "Green" end state.
- Green = meeting all quality bars: consistency, matching the narrative
  arcs, correctness, positive marks from AI reviewers, on-tone, on-voice,
  et cetera.

**Open:**

- Who sets the quality bars behind Green, and whether they differ per
  work, per genre, or per author.
- Pictures and video are a "maybe."
- Word integration is assumed possible, not known.
- Working label `iae`; the name is open.

**Leans on:** nothing in this repo beyond the emacs tooling as a
reference for what an inline AI loop felt like.
