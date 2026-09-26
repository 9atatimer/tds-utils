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

The thing that slows the writing down today is the writing.

## Story sets

| File | Theme |
|---|---|
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
- The biggest drag on pace today is the writing itself.

**Open:**

- What "the writing" is as a bottleneck -- the typing, the drafting, the
  deciding, the revising -- is the next question.
- Pictures and video are a "maybe."
- Word integration is assumed possible, not known.
- Working label `iae`; the name is open.

**Leans on:** nothing in this repo beyond the emacs tooling as a
reference for what an inline AI loop felt like.
