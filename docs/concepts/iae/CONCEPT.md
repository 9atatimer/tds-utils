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
sets all the details. When that conversation ends, what's in place is:
act structure, character bibles, settings notes, an outline, scene notes,
probably what is wanted and what to avoid, language and tone, and a
description of the audience.

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
with my own ideas, faster than I could ever write. My voice comes from
what I've written: either in the project, or a corpus of prior works I
want it to be aware of.

A manuscript isn't a single revision. That's the way paper works, not
electricity. Every revision, scene, draft, and vignette is kept --
revisions, variations, rewrites -- and all of it is selectable by a click:
swappable, composable, blended. You can go back to an earlier revision,
keep the tone, keep a phrase, strike through a line, make a note to be
more loving, salty, truthful, deceitful, et cetera. And the IAE helps you
synthesize, analyze, and evaluate the options: "Should Joe die here, or
in Act 3?" "Should she say yes? Fuck no? Hell no? Maybe?" The writing
tools help consider all those possibilities.

It literally treats writing like a graph. You aren't writing one
revision; you're forking off an infinite number of potential revisions
with each change. "I'm going to kill Joe in Act 2, not Act 3..." -- and it
should just figure out what impact that has on plot structure, character
knowledge, character emotion. Can't use Joe's apartment in Act 3 if he's
dead in Act 2 -- or at least there'd better be some change in tone. Et
cetera. Some of those graph lines will be green, some red, some orange,
some other colors -- the non-green ones are violating other constraints.
A traffic light: red, amber, green.

We're taking writing to the next level.

There are kinds of constraint. Correctness: are things factually correct
in the scene -- characters have the right hair color, locations are
described properly. And emotional and thematic correctness: rising
action, steamy, et cetera.

The writing process probably starts as disjointed high points -- scenes
or stories or reveals that make the story interesting. Then those get
arranged in some sort of timeline. There's the chronological timeline --
what happened, cause and effect -- and that's distinct from the narrative
timeline -- flashback, flashforward, drug-induced amnesia, a literally
untrustworthy narrator -- which is what nails the words to the page.

When technical writing, I want the same thing, plus guardrails that make
sure I don't make mistakes: factual errors, style/format compliance, code
correctness.

I want "observability" on my writing: something that can be monitored,
adjusted, and AI-influenced, to produce a final result that is "Green".
Green means it is meeting all quality bars: it is consistent, matches the
narrative arcs, is correct, gets positive marks from the AI reviewers,
stays on-tone and on-voice, et cetera.

## The model

Todd's statement of how observability works, recorded as said. It is the
definition the rest of the idea turns on.

There are various **analyzers**, each producing a numerical or enumerated
value with a confidence number. An analyzer evaluates a section of
writing, based on a specified path along the graph, and produces a time
series of metric values.

- Some analyzers are **contextual**: precedence (the path) matters.
- Some are **objective**: precedence and context don't matter; an
  evaluation of a snippet stands on its own.

There are background and foreground AIs, or analyzers/classifiers. The
foreground may also have real-time specialists. Notifications are
general: used by all of them.

A metric might be a true/false enumeration -- for example, a predicate
that a character's description is factual.

The main tool usage is defining **expectations** for a paragraph, scene,
chapter, or act: that a metric sits within a certain band, or within a
given subset of values. A lack of compliance is an error.

Then there are tools for writing summaries, act outlines, chapter
outlines, stages, and such, which lend themselves to events on a timeline
-- maybe regions on a timeline. Those high-level summaries feed into the
contextual metrics.

Pages are composed of a graph path through writing snippets. You add a
new snippet, or signal a revision of an existing snippet, add a segue, et
cetera.

When an expectation goes red, you view the editorial (page-number)
timeline and see the offending pages, then drill into a page and see the
offending regions. From there: click to review the predicate's notes;
open a discussion with one or more AIs; engage copy-editor mode to strike
through things and leave notes; engage author mode and write a revision.

Expectations, as Todd gave them:

- **Steamy-ness, for romantasy.** Certain scenes need it. Others must not
  have it, or it reads like a Penthouse Forum letter.
- **Relationship status curve.** Boy meets girl: goes up. Boy loses girl:
  goes down. Boy gets girl: goes up.
- **Frenemies.** Starts out antagonist, moves to neutral, ends up in bed
  by Act 2.

## Story sets

| File | Theme |
|---|---|
| STORIES.composing.md | structure in my words, ideas dumped raw, the prose filled in for me |
| STORIES.reviewing.md | from a red light to the offending page, the region, and the fix |
| STORIES.variants.md | writing as a graph: every change forks, consequences are worked out, every line colored |
| STORIES.observability.md | analyzers, metrics, expectations, and the traffic light toward "Green" |
| STORIES.workspace.md | the IDE-shaped shell: toolbar, tabs, left and right panels, the editor in the middle |
| STORIES.corpus.md | the many files, of many formats, that cut across the writing |
| STORIES.agents.md | agents you ask, and agents that watch and speak up |
| STORIES.craft.md | the story-building tools: high points, two timelines, knowledge bases, structure, pacing |
| STORIES.setup.md | getting set up by talking to an AI |

## Notes

**Settled in session (Todd's words):**

- The existing emacs tooling (`emacs/dot.emacs.d/elisp/tds-v3-ai-author*.el`)
  is illustrative only -- "wood and stone." The IAE is "glass and steel."
- Single-seat tool: no human editors, co-authors, or beta readers inside
  a project. The only human role is the author.
- It looks like an IDE: toolbar across the top, tabs driving the
  left-hand panels, AI agent panels on the right, the author's own editor
  in the middle.
- The editor is the author's choice, integrated by plugin; emacs is Todd's.
- There are two kinds of agent: ones you ask, and ones that watch.
- Setup is a conversation with an AI. It leaves in place: act structure,
  character bibles, settings notes, outline, scene notes, what is wanted,
  what to avoid, language and tone, description of the audience.
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
- Writing is a graph: each change forks potential revisions. A
  story-level change ("kill Joe in Act 2, not Act 3") has its impact on
  plot structure, character knowledge, and character emotion worked out
  by the IAE, not by the author.
- Graph lines carry a traffic-light status: red, amber, green. Non-green
  lines are violating constraints.
- Two kinds of constraint named so far: factual correctness (hair color,
  locations described properly) and emotional/thematic correctness
  (rising action, steamy).
- Work likely starts as disjointed high points (scenes, stories, reveals)
  that are then arranged on a timeline.
- A third timeline exists: the editorial (page-number) timeline.
- Chronological timeline (cause and effect) and narrative timeline
  (flashback, flashforward, amnesia, unreliable narrator) are distinct;
  the narrative timeline is what puts the words on the page.
- The analyzer / metric / expectation model in "The model" is Todd's own
  and is settled at the level he stated it. It is mechanism volunteered in
  phase 1: phase 2 takes it as the human's intent and still reviews it.
- "a private" in Todd's message was autocorrect for "a predicate";
  confirmed.
- AIs and analyzers/classifiers come in background and foreground; the
  foreground may include real-time specialists. Notifications are one
  general channel used by all of them. Whether "watching agents" and
  "analyzers" are one thing was asked; this is the answer as given.
- Pages are a graph path through writing snippets.
- A red expectation is worked from the editorial (page-number) timeline
  down to the page and the offending region, then handled by reading
  predicate notes, discussing with AIs, copy-editor mode, or author mode.
- Summaries and outlines (act, chapter, stages) become events or regions
  on a timeline and feed contextual metrics.
- The author's voice is learned from what the author has written: the
  project itself, or a corpus of prior works the author chooses.
- Technical writing gets the same loop plus guardrails against mistakes:
  factual errors, style/format compliance, code correctness.
- The writing has "observability" and a "Green" end state.
- Green = meeting all quality bars: consistency, matching the narrative
  arcs, correctness, positive marks from AI reviewers, on-tone, on-voice,
  et cetera.

**Open:**

- Transcription: "code in correction" was read as "code correctness";
  confirm.
- Who sets the quality bars behind Green, and whether they differ per
  work, per genre, or per author.
- Pictures and video are a "maybe."
- Word integration is assumed possible, not known.
- Working label `iae`; the name is open.

**Leans on:** nothing in this repo beyond the emacs tooling as a
reference for what an inline AI loop felt like.
