# [Title]

> **Status:** DRAFT  
> **Date:** YYYY-MM-DD  
> **Authors:** [Names]  
> **Depends on:** [Other Doc](./path.md) (if applicable)

---

## Overview

_2-3 sentences. What is this system/feature? Why does it exist? What problem does it solve?_

---

## Goals

_Testable success criteria. What does "done" look like?_

1. **[Goal 1]** -- [Measurable outcome]
2. **[Goal 2]** -- [Measurable outcome]
3. **[Goal 3]** -- [Measurable outcome]

---

## Non-Goals

_Explicit boundaries. What this system will NOT do, even if someone asks._

- **[Non-goal 1]** -- [Why it's out of scope]
- **[Non-goal 2]** -- [Why it's out of scope]

---

## Architecture Overview

_High-level diagram showing major components and data flow._

```
+--------------+     +--------------+     +--------------+
| Component A  |---->| Component B  |---->| Component C  |
+--------------+     +--------------+     +--------------+
```

---

## Design

### [Subsystem 1]

_Describe the component, its responsibilities, and interfaces._

#### Responsibilities

| Responsibility | Details |
|----------------|---------|
| [What it does] | [How it does it] |

#### API / Interface

```
[Method/Endpoint signature]

Request:
  [fields]

Response:
  [fields]

Errors:
  [error cases]
```

### [Subsystem 2]

_Repeat pattern for each major component._

---

## State Machine

_If the system has lifecycle states, document them explicitly._

```
+-----------+         +-----------+         +-------------+
|  STATE_A  |-------->|  STATE_B  |-------->|   STATE_C   |
+-----------+         +-----------+         +-------------+
```

| From | To | Trigger | Condition |
|------|-----|---------|-----------|
| STATE_A | STATE_B | [event] | [condition] |
| STATE_B | STATE_C | [event] | [condition] |

---

## Data Model

_Database tables, key fields, relationships._

```
table_name
+-- id                  UUID, primary key
+-- foreign_id          UUID, FK to other_table
+-- field_name          TYPE, constraints
+-- created_at          TIMESTAMPTZ
```

---

## Security Considerations

_Authentication, authorization, secrets handling, attack vectors._

- **[Consideration 1]** -- [Mitigation]
- **[Consideration 2]** -- [Mitigation]

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| [What was decided] | [The choice made] | [Why this choice over alternatives] |
| [What was decided] | [The choice made] | [Why this choice over alternatives] |

---

## Open Questions

_Unresolved issues. Be honest about unknowns._

1. **[Question]** -- [Context, options being considered]
2. **[Question]** -- [Context, options being considered]

---

## Rejections

_Alternatives that were considered and explicitly dismissed, with one-line
reasons. The point of this section is to prevent future maintainers (and
future-you) from relitigating decisions that have already been settled.
Distinct from Non-Goals (scope) and Key Decisions (what was chosen): this
captures what was **not** chosen and why._

- **[Alternative]** -- [One-line reason for rejection]
- **[Alternative]** -- [One-line reason for rejection]

---

## Future Considerations

_Things that might matter later but are explicitly deferred._

- **[Topic]** -- [Why deferred, when it might become relevant]

---

## Related Documents

- [Document Name](./path.md) -- [Relationship]
- [Document Name](./path.md) -- [Relationship]
