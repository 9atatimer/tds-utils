# IAE -- Integrated Authoring Environment (POC)

> **Status:** DRAFT
> **Date:** 2026-09-26
> **Authors:** Todd Stumpf, with AI assistance
> **Depends on:** [IAE concept](../concepts/iae/CONCEPT.md) (phase 1 origin, not authority)

---

## Overview

An author's work is a multiverse: every version of every snippet is kept,
and a reading of the work is one path through the graph of those versions.
The POC proves that an author can generate alternative versions of a
scene, see them scored red/amber/green against expectations, and navigate,
compare, and choose among them in a visual multiverse view -- with the
prose itself still written in the author's own editor.

---

## Goals

POC goals. Each is checked by the author on a real project of at least
three nexuses and ten nodes.

1. **Nothing is overwritten** -- every node ever created, including
   rejected ones, is still readable after any sequence of operations.
2. **The multiverse is visible** -- the Multiverse View draws every
   non-rejected node, grouped by nexus, with the edges between them, and
   highlights the current path.
3. **Variants on demand** -- asking for N versions at a nexus adds N new
   nodes to that nexus, written in the author's voice and conditioned on
   the neighboring nodes of the current path.
4. **Every node has a light** -- each node shows red, amber, or green from
   the expectations evaluated on it along the current path; a nexus lists
   its nodes most-green first.
5. **The 4 Rs work from a click** -- clicking a node offers read, review,
   reject, and revise, each doing what the Behaviors table says.
6. **A path is a readable work** -- choosing a path yields the manuscript
   for that path as one continuous text.

---

## Non-Goals

Deferred to MVP or later; each traces to the concept.

- **IDE-style panels** (toolbar, tabs, agent panels) -- MVP. The POC is
  the Multiverse View plus the author's editor.
- **Setup conversation** -- MVP. POC bibles, outline, and expectations
  are hand-written files.
- **Dictation and shotgun-typing ingestion** -- MVP.
- **Editorial timeline drill-down to offending regions** -- MVP. The POC
  lights whole nodes, not regions within them.
- **Background analyzers and notifications** -- MVP. POC analysis runs
  when asked.
- **Consequence propagation** ("kill Joe in Act 2" reworks downstream
  knowledge and emotion) -- post-MVP.
- **Chronological vs narrative timelines** -- post-MVP. The POC has one
  order: the path.
- **Real-time specialists, media, vi and Word plugins, technical-writing
  guardrails, multi-user** -- post-MVP; multi-user is never (single-seat).

---

## Architecture Overview

Components are named by responsibility; runtimes, languages, and vendors
are phase 3.

```
+--------------------+        +-----------------------------+
|  Author's editor   |<------>|  Project on disk            |
|  (emacs)           |  edit  |  snippets, bibles, outline, |
+--------------------+  files |  expectations, graph        |
                               +--------------+--------------+
                                              |
                               +--------------v--------------+
                               |  Multiverse core            |
                               |  graph, paths, nexuses,     |
                               |  lights, 4 Rs               |
                               +---+-----------------+-------+
                                   |                 |
                     +-------------v---+     +-------v-------------+
                     |  Generator      |     |  Analyzers          |
                     |  (LLM, voice)   |     |  (LLM or rule)      |
                     +-----------------+     +---------------------+
                                   ^
                                   |
                     +-------------+---------------+
                     |  Multiverse View            |
                     |  (graph, nexus carousels,   |
                     |   click -> 4 Rs)            |
                     +-----------------------------+
```

---

## Design

### Multiverse core

| Responsibility | Details |
|---|---|
| Hold the graph | Nodes, edges, nexuses; append-only -- a node is never edited, only superseded by a new node |
| Resolve a path | A path is an ordered walk of nodes, one per nexus it passes through |
| Compute lights | For a node on a path, evaluate every expectation scoped to that node's nexus; the worst result is the node's light |
| Rank a nexus | Siblings ordered green, amber, red; ties by creation time, newest first |
| Carry the 4 Rs | Read, review, reject, revise as use cases (below) |

### Paths

A path is either **manual** -- the author picks the node at each nexus --
or **guided** by a policy that picks for them. POC policies:

| Policy | Picks, at each nexus, the non-rejected node with... |
|---|---|
| most steamy | the highest steaminess value |
| least words | the fewest words |
| least AI | the lowest AI taint |
| most green | the best light (the default ranking) |

Ties break by light, then newest. A guided path is resolved once, when
asked; it does not re-route itself as new nodes arrive.

Paths can be **saved** under a name. A saved path has a permanent revision
history: every change to it appends a revision, none is ever lost, and
any revision can be **forked** into a new saved path.

### Generator

Writes new node text for a nexus. Input: the author's intent note for the
nexus, the neighboring nodes on the current path, the bibles, and a voice
sample drawn from the project's own accepted nodes. One call per variant;
N variants are N independent calls, as in the emacs `AI[3: ...]` loop.

### Analyzers

The concept's model, cut to two:

| Analyzer | Kind | Output | Scope |
|---|---|---|---|
| Steaminess | objective | number 0.0-1.0, with confidence 0.0-1.0 | the node's text alone |
| Character fact | contextual | true/false, with confidence and a note naming the contradicted fact | the node's text, the bibles, and the path up to the node |

### Expectations

An expectation binds one analyzer to one nexus with a band (numbers) or
an allowed subset (enumerations). Light rules:

| Result | Light |
|---|---|
| Value inside band/subset, confidence >= 0.7 | green |
| Value inside band/subset, confidence < 0.7 | amber |
| Value outside band/subset, confidence < 0.7 | amber |
| Value outside band/subset, confidence >= 0.7 | red |
| Analyzer failed or has not run | amber |

The 0.7 threshold is a POC parameter, not a rule of the domain.

### Multiverse View

Its own app and visualization layer, separate from the editor. It may be
a web app, but it must operate properly with the author's running emacs
server session: revise opens the working copy in that session (a new
frame or buffer of the existing server), not in a fresh emacs. Key
bindings are the known risk for a web implementation. Draws the graph
left-to-right in path order; each nexus is a carousel column of its
nodes, most-green on top; the current path is a highlighted line through
one node per column. Clicking a node opens the 4 Rs:

| R | Where it happens |
|---|---|
| Read | In the Multiverse View |
| Review | In the Multiverse View: analyzer results, plus review notes the author attaches to the node |
| Reject | In the Multiverse View |
| Revise | Triggers an emacs session on the node's text; saving adds a new node |

Choosing a different node in a column re-routes the current path through
it and recomputes contextual lights downstream.

---

## Behaviors and Interfaces

Signatures use the ubiquitous language; port names are axes of change,
replaced by seams in phase 3.

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| Variants are generated | `generate_variants(nexus: NexusId, path: Path, count: int, note: IntentNote) -> list[Node]` | text generation, project store | Given a nexus on the current path, When the author asks for 3 variants, Then 3 new nodes join that nexus and no existing node changes |
| A failed generation adds nothing | (same use case; error path) | text generation, project store | Given the generator fails on 1 of 3 calls, When generation completes, Then 2 nodes are added and the failure is reported, not retried |
| A node is read | `read_node(node: NodeId) -> NodeText` | project store | Given any node, rejected or not, When read, Then its full text is returned unchanged |
| A node is reviewed | `review_node(node: NodeId, path: Path) -> Review` | analysis, project store | Given a node on a path, When reviewed, Then every expectation on its nexus is listed with value, confidence, light, and note, followed by the author's review notes |
| A node is rejected | `reject_node(node: NodeId) -> Node` | project store | Given a node, When rejected, Then it leaves the default view and every ranking, and remains readable |
| The path avoids rejected nodes | `reject_node` (same use case; path rule) | project store | Given the current path runs through a node, When that node is rejected, Then the path re-routes through the most-green remaining sibling |
| A review note is attached | `attach_review_note(node: NodeId, note: ReviewNote) -> Node` | project store | Given a node in the Multiverse View, When the author attaches a note, Then the note shows on the node's review and the node's text is unchanged |
| Revise opens the editor | `begin_revision(node: NodeId) -> RevisionSession` | editor launch, project store | Given a node, When the author picks revise, Then an emacs session opens on a working copy of the node's text, never on the node itself |
| A node is revised by hand | `revise_node(node: NodeId, text: NodeText) -> Node` | project store | Given a revision session, When the author saves, Then a new node is added to the same nexus, linked to its origin, and the origin is unchanged |
| A node is revised by the AI | `revise_node_with_note(node: NodeId, path: Path, note: IntentNote) -> Node` | text generation, project store | Given a note "more salty", When revision runs, Then a new sibling node linked to its origin is added |
| A node is lit | `light_node(node: NodeId, path: Path) -> Light` | analysis | Given expectations on a nexus, When the node's analyzers report, Then the light follows the light rules table |
| A nexus is ranked | `rank_nexus(nexus: NexusId, path: Path) -> list[RankedNode]` | analysis, project store | Given a nexus with green, amber, and red nodes, When ranked, Then the order is green, amber, red |
| A path is guided | `guide_path(policy: PathPolicy, from_path: Path) -> Path` | analysis, project store | Given nexuses holding nodes of different word counts, When the author guides by "least words", Then each nexus contributes its shortest non-rejected node |
| A path is saved | `save_path(name: PathName, path: Path) -> SavedPath` | project store | Given a path, When saved under an existing name, Then a new revision is appended and every earlier revision is still retrievable |
| A saved path is forked | `fork_path(saved: SavedPathId, revision: RevisionNumber, name: PathName) -> SavedPath` | project store | Given a saved path with 3 revisions, When revision 2 is forked, Then a new saved path starts from revision 2, records its origin, and the original is unchanged |
| A path is chosen | `choose_node(path: Path, node: NodeId) -> Path` | project store | Given a path, When the author picks another node at a nexus, Then the new path runs through it and downstream contextual lights are recomputed |
| A path is read as a work | `render_path(path: Path) -> Manuscript` | project store | Given a path, When rendered, Then the manuscript is the path's node texts in order |

---

## Data Model

Domain nouns; storage format is phase 3.

```
Node
+-- id            NodeId, unique, never reused
+-- nexus         NexusId
+-- text          NodeText (plain text or LaTeX)
+-- origin        NodeId or none -- the node it revises
+-- ai_taint      0.0-1.0 -- how much of the text is AI-derived; a hand
|                 revision of an AI node inherits taint, it is not clean
+-- created_at    timestamp
+-- rejected      bool, default false
+-- review_notes  list of ReviewNote -- author's notes, attached in the view

Nexus
+-- id            NexusId
+-- label         short author-chosen name ("Act 2, Joe dies")
+-- note          IntentNote -- what the author wants here

Edge              Node -> Node, "may follow"

Path              ordered list of NodeId

PathPolicy        manual | most steamy | least words | least AI | most green

SavedPath
+-- id            SavedPathId
+-- name          PathName
+-- revisions     append-only list of (RevisionNumber, Path, created_at)
+-- forked_from   (SavedPathId, RevisionNumber) or none

Expectation
+-- nexus         NexusId
+-- analyzer      analyzer name
+-- band | subset allowed values

Metric            value, confidence 0.0-1.0, note
Light             red | amber | green
ReviewNote        text, created_at
Review            list of (Expectation, Metric, Light), then ReviewNotes
RevisionSession   a working copy of a node's text open in the editor
```

---

## Security Considerations

- **Prose leaves the machine when the generator or an analyzer is a
  hosted model** -- the POC sends only the nexus note, the path
  neighbors, the bibles, and the voice sample; the vendor choice and any
  local-model option are phase 3.
- **Model credentials** -- read at run time from the fleet vault, never
  written into the project.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| POC centre of gravity | The multiverse: graph view, nexus carousels, 4 Rs | Todd, 2026-09-26: "I really want us to get to the multiverse... for POC" |
| Node actions | The 4 Rs: read, review, reject, revise | Todd, 2026-09-26 |
| Nothing is overwritten | Append-only nodes; reject hides, never deletes | Concept: "Every revision, scene, draft, and vignette is kept" |
| Where prose is written | The author's own editor (emacs), on plain files | Concept: editor is the author's choice; snippets are files the editor works on |
| Where the Multiverse View lives | Its own visualization layer, separate from the editor | Todd, 2026-09-26: "Graph view will need to be its own visualization layer" |
| Multiverse View runtime | Its own app; web is acceptable if it operates properly with a running emacs server session; the runtime choice is phase 3 | Todd, 2026-09-26: "I think it's its own app. Could be web... I suspect key bindings make that hard" |
| Which Rs happen where | Read, review (incl. attaching notes), and reject in the Multiverse View; revise triggers an emacs session | Todd, 2026-09-26 |
| Lights | Traffic light from expectations over analyzer metrics with confidence | Concept, "The model" |
| Paths | Manual or guided by a policy; saved paths keep a permanent revision history and can be forked | Todd, 2026-09-26 (transcribed "parts", read as "paths" -- see Open Questions) |
| AI taint | Every node carries an AI taint weight 0.0-1.0; hand-revising an AI node yields a tainted node, not a clean one; the formula is an implementation detail | Todd, 2026-09-26: "Tainted, clearly" |
| Home repo | tds-utils, for now | Todd, 2026-09-26: "Just go with what we got for now"; moving it out is a later detail |
| Nexus order in the POC | One fixed nexus order; paths differ only in which node they pick at each nexus (agent's call; Todd to confirm) | Proves the multiverse view, lights, and saved paths without structural forks; structural forks are MVP |
| Analyzer count for POC | Two: one objective, one contextual | The smallest set that exercises both kinds the concept names |

---

## Open Questions

1. **Structural forks** -- decided below for the POC (fixed nexus
   order); whether MVP paths may pass through different nexuses (the
   concept's "Joe dead, no apartment scene") stays open.
2. **Snippet vs node vs nexus naming** -- "snippet" (concept) is used
   here as the author-facing word for a node's text; confirm the three
   nouns.
3. **"Parts" or "paths"** -- Todd's message said "Parts can be manual,
   or guided... Parts can be saved"; read as paths. Confirm.
4. **Measuring AI taint** -- settled that it is a 0-1 weight and that a
   hand revision of an AI node is tainted; the formula (starting from
   word-count share) is an implementation detail, not design.
5. **Key bindings in the Multiverse View** -- which keys the author
   expects to work in the view, and whether they must be emacs-style;
   this decides whether web is viable.
6. **Voice sample** -- which accepted nodes form it, and how much.
7. **Model vendor(s)** for generator and analyzers -- phase 3, tech radar.

---

## Rejections

- **Multiverse View drawn inside emacs** -- a force- or column-laid graph
  with carousels and click targets is a poor fit for a text buffer.
- **Overwriting revisions in place** -- contradicts the concept's core
  claim that a manuscript is not a single revision.

---

## Future Considerations

MVP, in the order the concept circles back to them: IDE-style panels,
editorial timeline drill-down, background analyzers with notifications,
relationship-curve time series, dictation ingestion, setup conversation.

---

## Related Documents

- [IAE concept](../concepts/iae/CONCEPT.md) and its STORIES files
- `emacs/dot.emacs.d/elisp/tds-v3-ai-author*.el` -- the "wood and stone"
  predecessor
