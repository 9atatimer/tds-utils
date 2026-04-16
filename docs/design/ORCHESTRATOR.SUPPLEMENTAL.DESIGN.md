- No god-process validating transitions
- "Be like water" -- implementation evolves freely, tests enforce behavior
- The power of NATS subjects + JetStream consumers is that topology can evolve without rewriting a central state machine

### Orchestrator is a service collection, not a monolith

- The "orchestrator" is NOT an LLM
- It is code, config, control plane -- a collection of services
- Components: CLI/REPL, event supervisor, project manager, agent registry, context sharing layer
- Independently deployable, share state through NATS
- From human perspective: "the thing I talk to"

### Context sharing is pragmatic plumbing

- Three delivery mechanisms: files on disk, MCP servers, RAG/prompt injection
- NOT a knowledge graph or epistemology project
- Layered architecture, separation of concerns
- Cross-project sharing via whitelist/blacklist graph
- Graph edges controlled by human directives via CLI
- Sub-layers automate details based on high-level directives
- Goal: give the coding agent everything it needs, nothing to distract

### Agents: ephemeral by default, identity per class

- Both ephemeral and persistent agents exist
- Ephemeral preferred to keep resource consumption low
- Some classes are singletons
- Agent classes share class credentials (NKEYs)
- Persistent singletons get individual identity for audit
- Security + sanity: wrong agent never pulls from wrong topic

### Don't premature-optimize resources

- 64GB M1 Max laptop -- can absorb 1GB stagnant orchestrator
- Get to MVP first, see where pinched
- Single laptop is not scalable -- architecture assumes multi-machine from day one
- k8s gives us the generic abstraction for multiple projects, environments, everything

### UI is tmux + CLI tooling

- Not tmux-wiring or TUI -- CLI tools run in tmux sessions
- Multiple independent tool sessions, not a central tool
- Web UI only for monitoring dashboards where they genuinely help

---

## Open Design Threads

These were identified but NOT resolved:

1. **LLM backend for CLI/REPL** -- Ollama local vs remote API (Claude, etc.) vs hybrid
2. **Agent runtime format** -- All k3s pods, or can some be lightweight processes outside k3s?
3. **Task tracker source of truth** -- NATS KV as source with GitHub Issues as projection, or reverse?
4. **Agent class taxonomy** -- Initial classes and their boundaries not defined
5. **Cross-project context graph storage** -- NATS KV? Config files? Where do edges live?
6. **Budget and priority model** -- What does "budget" mean concretely?

---

## Gaps in the Design Doc

These sections need work:

### State Machine (major gap)

Three layered FSMs identified but not detailed:

- **Project lifecycle**: inception -> provisioning -> active -> paused -> completed -> archived
- **Task lifecycle**: pending -> assigned -> running -> review -> done / failed
- **Agent lifecycle**: provisioning -> ready -> working -> idle -> terminated

Each needs: mermaid diagram, transition table (from/to/trigger/condition), and clear documentation of how the FSM is enforced via message flow rather than a central engine.

### Data Model (major gap)

Need to specify:
- What keys/values live in NATS KV
- What goes in Object Store vs GitHub Packages
- Key naming conventions aligned with subject hierarchy

### Agent Class Taxonomy (gap)

No concrete agent types defined yet. Candidates mentioned in passing: coding, review, design, testing, documentation. Need boundaries, capabilities, permitted subjects.

### Rejections (empty)

No alternatives formally rejected yet. Should be populated as design progresses.

---

## User Story (verbatim from user)

```
The user has a coding task. He runs a command, a cli/repl, and begins talking
to ... let's call it the orchestrator. He has a new idea. He chats with the LLM
about the idea -- as I am doing with you -- and then decides "yup, let's do
this", and he asks the LLM to create a new project, distinct from all the other
work (we'll assume there are active projects going on, but this is a new one).
We need the LLM orchestrator to gather some information from the user, and then
provision a new active project. That project will need all sorts of stuff:
repos, design docs, architecture docs, goals, out-of-scope guardrails. Those
details will generate smaller-grain tasks and dependencies. Probably gonna need
a budget or priority for the project. Maybe a quality bar. All these tasks
naturally fall into events, which deserve to be consumed by agents that are
aware of the parameters of the project (and the task). And those agents should
be aware (whitelist/blacklist) of other projects and tasks to share context,
learnings, defeats...
```

---

## Design Principles Established

- Domain-driven design / clean architecture / hexagonal architecture
- Agents are first-class citizens -- the system is designed for coding agents, not humans, as code generators
- NATS advisory messages (NO_RESPONDERS) as the scale-to-zero trigger
- Pull consumers for governance and flow control
- Subject hierarchy: PROJECT.<id>.> for isolation, wildcard for observability
- JetStream for at-least-once delivery guarantees
- Resource quotas via k8s namespaces
- Security via NKEYs scoped per agent class

---

## Infrastructure Stack

| Component | Role |
|-----------|------|
| k3s | Container orchestration, namespaces, RBAC, quotas, job scheduling |
| NATS + JetStream | Messaging backbone, durable streams, KV store, Object Store |
| KEDA | Event-driven autoscaling, bridges NATS consumer lag to k3s pods |
| Ollama | LLM backend (local or via remollama for remote GPU) |
| GitHub | Repos, issues, packages for artifact persistence |
| tmux | Session management for CLI tooling |
| ssh-agent + PGP | Human identity and authentication |

---

## Repo Conventions to Follow

- Design docs: follow `docs/design/TEMPLATE.md` format
- Design skill: follow `prompts/SKILL.DESIGN.md` process
- Markdown: follow `prompts/SKILL.MARKDOWN.md` (ASCII only, no smart quotes, no em-dashes use --, blank lines after headings)
- Planning: follow `prompts/SKILL.PLANNING.md` when creating TODO_PLANs
- Mermaid diagrams preferred over ASCII box art
- Shell scripts: function-based structure per CLAUDE.md
- macOS scripts: zsh, BSD tool syntax
