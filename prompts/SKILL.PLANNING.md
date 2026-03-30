# SKILL: Implementation Planning & TODO_PLAN Creation

> **Purpose:** Create resilient, BDD-driven implementation plans that fight compact amnesia
> **When to use:** Before starting any multi-phase feature implementation
> **Learned from:** Pantry TODO_PLAN (excellent) vs CR-MAGIC TODO_PLAN (poor)

---

## Core Philosophy: Test-First, Commit Often, Document Always

**The Three Pillars of Amnesia-Resistant Planning:**

1. **RED -> GREEN -> COMMIT** — Never implement without a failing test first
2. **Small Steps** — Each step = ONE test passing = ONE commit (not 7 features)
3. **Learning Checkpoints** — Force documentation of discoveries every 2-3 commits

**Why this matters:**
- Compact amnesia can strike mid-phase
- Last commit message = breadcrumb trail back to context
- Failing tests = clear "what's next" signal
- Learning notes = preserved decision context

---

## Anti-Patterns to AVOID [NO]

### 1. Implementation-First Planning

**BAD (Implementation-First):**
```markdown
### Step 1.2: Implement Action Execution Logic
- [ ] START_AGENT -> calls AgentClient.run()
- [ ] RESUME_AGENT -> calls AgentClient.resume()
- [ ] TERMINATE_AGENT -> calls AgentClient.terminate()
- [ ] START_POLLING -> calls CommentClient poll loop
- [ ] DO_PROMOTION -> calls promotion flow
- [ ] PROMPT_HUMAN -> displays banner, reads input
- [ ] CLEANUP -> releases locks, saves state

**Commit Point:** feat(component): implement all action handlers
```

**Problems:**
- 7 features before commit = hours of work
- No tests mentioned
- If amnesia hits at item 4, must re-read all code to figure out state
- "Implement then test" encourages skipping tests

### 2. Coarse Commit Granularity

**BAD:**
```markdown
**Commit Strategy:**
- After each phase completes
- After test suites pass
```

**Problems:**
- "Phase" = 5-10 steps = hours of work
- "Test suites" = when? After all 20 tests? Or each?
- No recovery points mid-phase

### 3. Vague Acceptance Criteria

**BAD:**
```markdown
**Acceptance:**
- RunController can start, drive FSM, execute actions
- State persisted before mutations
- Graceful shutdown works
```

**Problems:**
- How do you verify? Manual testing?
- Not test-driven
- Subjective ("works" = ???)

### 4. Missing Amnesia Recovery Protocol

**BAD:**
- No "how to resume" section
- No explicit connection between commits and TODO steps
- No guidance on reading context from last session

---

## The BDD TODO_PLAN Template [OK]

### Structure Overview

```markdown
# [Component] Implementation TODO Plan

> **Status:** [Not Started | In Progress | Complete]
> **Created:** YYYY-MM-DD
> **Design:** Link to architecture doc
> **Branch:** branch-name

---

## Implementation Philosophy

**BDD/TDD Process:**
1. Write skeleton tests FIRST (call the real API, assert on expected behavior)
2. Tests fail because the code does not exist yet -- never use placeholder assertions like `assert False`
3. Implement ONE test at a time
4. Green before moving to next test
5. Commit after EACH test passes (not after phase)

**Commit Strategy:**
- After EACH test goes from RED -> GREEN
- Before and after learning checkpoint updates
- After completing acceptance criteria

**Learning Checkpoints:**
- Every 2-3 commits OR 30 minutes of work
- Explicit steps to update this TODO with discoveries
- Notes on what worked well / what to improve
- Patterns to reuse in future phases

---

## Testing Philosophy (CRITICAL)

[Include test separation, timeout requirements, mocking strategy]

---

## Current Status Summary

[Visual table of what's complete vs in-progress vs not started]

---

## RESUMING AFTER COMPACT AMNESIA 
If you lose context mid-session:

1. **Check last commit:** `git log -1 --oneline`
2. **Read commit message:** Tells you what test passed
3. **Check this TODO_PLAN:** Find that step, see what's next
4. **Run tests:** `[test command]` — what's still RED?
5. **Read last learning checkpoint:** Context of decisions made
6. **Continue from next RED test**

**Example:**
```bash
$ git log -1
test(feature): add foo validation test (RED)

# You were writing a failing test but didn't finish implementation
# Next step: Make test_foo_validation pass (GREEN)
```

---

## PHASE [N]: [Phase Name] [Emoji]

**Goal:** One sentence describing the phase outcome

### Step [N.1]: Write [Feature] Tests (SKELETON)
- [ ] Create `tests/unit/test_[feature].py`
- [ ] Write `test_[behavior_1]()` calling real API with real assertions
- [ ] Write `test_[behavior_2]()` calling real API with real assertions
- [ ] Run tests: `[command]` -- expect RED (code not implemented yet)

**Tests Written (list them explicitly):**
- `test_[behavior_1]` - Validates [what]
- `test_[behavior_2]` - Validates [what]

**Acceptance:** Tests exist, all RED (failing because code doesn't exist, not because of placeholders)

**Commit Point:** `test(feature): add tests for [feature] (RED)`

---

### Step [N.2]: Implement [Behavior 1]
- [ ] Implement [specific function/class]
- [ ] Make `test_[behavior_1]()` pass (GREEN)
- [ ] Run: `[command]::test_[behavior_1]`

**Acceptance:** Test goes from RED -> GREEN, all others still pass

**Commit Point:** `feat(feature): implement [behavior_1] (GREEN)`

---

### Step [N.3]: Implement [Behavior 2]
- [ ] Implement [specific function/class]
- [ ] Make `test_[behavior_2]()` pass (GREEN)
- [ ] Run: `[command]::test_[behavior_2]`

**Acceptance:** Test goes from RED -> GREEN, all others still pass

**Commit Point:** `feat(feature): implement [behavior_2] (GREEN)`

---

### Step [N.4]: Learning Checkpoint - [Phase Name]
- [ ] Update this TODO with findings from steps N.1-N.3

**Notes:**
```
[PHASE N LEARNINGS - Fill after N.1-N.3]

What worked well:
-

What was harder than expected:
-

Discoveries/surprises:
-

Patterns to reuse:
-

Technical decisions made:
-

Next time I would:
-
```

**Commit Point:** `docs(feature): update TODO_PLAN with [phase] learnings`

---

## Definition of Done 
### Feature Complete When:

**Functional:**
- [ ] All tests written FIRST (skeleton with RED)
- [ ] All tests passing (GREEN)
- [ ] No placeholder assertions remaining
- [ ] Integration tests pass (if applicable)

**Testing:**
- [ ] Unit test coverage >80% (or project standard)
- [ ] All edge cases covered
- [ ] Mock usage appropriate (no real I/O in unit tests)

**Documentation:**
- [ ] All learning checkpoints filled in
- [ ] Architecture doc updated (if design changed)
- [ ] README updated (if user-facing)

**Quality:**
- [ ] Linter passes
- [ ] Type checker passes (if applicable)
- [ ] No TODO/FIXME comments in code
- [ ] Code review complete (if required)

---

## Progress Tracking

**Current Phase:** [Phase number and name]
**Current Step:** [Step number and name]
**Overall Progress:** [X%]

**Phase Completion:**
- [ ] Phase 0: [Name] (0/N steps)
- [ ] Phase 1: [Name] (0/N steps)
- [...]

**Last Commit:** `[git log -1 --oneline]`
**Last Test:** `[test name]` - [RED/GREEN]

---

## Notes & Decisions

### Architectural Decisions
```
[Date] - [Decision]: [Rationale]
```

### Deviations from Design
```
[Date] - [What changed]: [Why]
```

### Technical Debt
```
[Date] - [Shortcut taken]: [Plan to address]
```

---

**This TODO_PLAN is a living document. Update it after EVERY commit!**
```

---

## Key Principles Explained

### 1. RED -> GREEN -> COMMIT Cycle

**Always follow this sequence:**

1. **Write test (RED)**: Test fails because feature doesn't exist
2. **Implement feature (GREEN)**: Make test pass with simplest code
3. **Commit (CHECKPOINT)**: Save progress with clear message
4. **Repeat**: Next test

**Why:**
- Each commit is a recovery point
- Commit message = "I just made test_X pass"
- If amnesia hits, last commit tells you exactly what works

**Example commit sequence:**
```
test(auth): add password validation test (RED)
feat(auth): implement password validation (GREEN)
test(auth): add email format test (RED)
feat(auth): implement email validation (GREEN)
docs(auth): update TODO with validation learnings
```

### 2. One Test = One Commit

**NOT:**
```markdown
- [ ] Implement all validators
- [ ] Test all validators

Commit: feat(auth): implement all validation
```

**YES:**
```markdown
- [ ] Write test_password_length (RED)
- [ ] Implement password_length validator (GREEN)
  -> Commit: feat(auth): add password length validation (GREEN)

- [ ] Write test_email_format (RED)
- [ ] Implement email_format validator (GREEN)
  -> Commit: feat(auth): add email format validation (GREEN)
```

### 3. Learning Checkpoints Every 2-3 Commits

**Trigger checkpoint when:**
- 2-3 tests have passed (2-3 commits)
- 30+ minutes elapsed
- You make a significant discovery
- You change approach

**What to capture:**
- **What worked:** "Using pytest fixtures simplified test setup"
- **What was hard:** "Mock data generation was tedious"
- **Discoveries:** "Found existing helper in utils.py"
- **Decisions:** "Chose regex over parser for simplicity"
- **Next time:** "Start with property-based tests earlier"

**Why:**
- Preserves context across sessions
- Prevents re-learning same lessons
- Shows progress even if amnesia hits

### 4. Explicit Amnesia Recovery Protocol

**Include this section in EVERY TODO_PLAN:**

```markdown
## RESUMING AFTER COMPACT AMNESIA 
If you lose context mid-session:

1. **Check last commit:** `git log -1 --oneline`
2. **Read commit message:** Tells you what test passed
3. **Check this TODO_PLAN:** Find that step, see what's next
4. **Run tests:** `[test command]` — what's still RED?
5. **Read last learning checkpoint:** Context of decisions made
6. **Continue from next RED test**
```

**Why:**
- Explicit recovery procedure
- Assumes zero memory retention
- Treats TODO_PLAN as external memory

---

## Testing Philosophy Guidelines

### Test Separation (Copy from Pantry)

Always include this in TODO_PLANs:

```markdown
## Testing Philosophy (CRITICAL)

### Test Separation (Strict)

**Three separate buckets - never mix:**

1. **Unit Tests** (`tests/unit/**/*.test.[ext]`)
   - Run with: `[command]`
   - Environment: `[test env]`
   - All external dependencies MOCKED
   - **Timeout: 250ms default** (enforced)
   - **NO sleep(), NO wall-clock dependencies**
   - Deterministic, fast, isolated

2. **Integration Tests** (`tests/integration/**/*.test.[ext]`)
   - Run with: `[command]`
   - Real external services
   - Longer timeout allowed (30s default)
   - Still NO sleep() - use await on real operations

3. **E2E Tests** (`tests/e2e/**/*.test.[ext]`)
   - Run with: `[command]`
   - Full system test
   - Slowest, most realistic
```

### No Sleep Policy

Always include:

```markdown
### No Sleep Policy (Absolute)

**NEVER use `sleep()`, `setTimeout()`, or wall-clock delays in tests.**

**Instead:**
- Mock timers: `vi.useFakeTimers()` (JS) or `freezegun` (Python)
- Mock async operations: Return resolved promises immediately
- Use `await` on real async operations (integration tests only)
```

---

## Language-Specific Adaptations

### Python

```markdown
**BDD/TDD Process:**
1. Create `tests/unit/test_[feature].py`
2. Write test calling real API with real assertions on expected behavior
3. Run: `pytest tests/unit/test_[feature].py` (RED -- code not implemented yet)
4. Implement feature
5. Run: `pytest tests/unit/test_[feature].py` (GREEN)
6. Commit: `feat([module]): implement [feature] (GREEN)`

**Testing Framework:** pytest
**Mocking:** unittest.mock or pytest-mock
**Fixtures:** Use pytest fixtures liberally
```

### TypeScript

```markdown
**BDD/TDD Process:**
1. Create `test/[feature].test.ts`
2. Write test calling real API with real assertions on expected behavior
3. Run: `npm run test:unit -- [feature]` (RED -- code not implemented yet)
4. Implement feature
5. Run: `npm run test:unit -- [feature]` (GREEN)
6. Commit: `feat([module]): implement [feature] (GREEN)`

**Testing Framework:** Vitest or Jest
**Mocking:** vi.mock() or jest.mock()
**Environment:** happy-dom (unit) or node (integration)
```

---

## Commit Message Format

### Standard Format

```
<type>(<scope>): <subject> (<test-status>)

<type>: test | feat | fix | docs | refactor
<scope>: module/component name
<subject>: what changed (imperative mood)
<test-status>: (RED) | (GREEN) | omit for docs/refactor
```

### Examples

**Writing tests:**
```
test(auth): add password validation test (RED)
test(github): add comment classification tests (RED)
test(workspace): add lock acquisition test (RED)
```

**Implementing features:**
```
feat(auth): implement password validation (GREEN)
feat(github): implement comment classifier (GREEN)
feat(workspace): implement lock acquisition (GREEN)
```

**Learning checkpoints:**
```
docs(auth): update TODO_PLAN with validation learnings
docs(github): update TODO with polling strategy decisions
```

**Why this format:**
- `(RED)` = "I wrote a failing test, didn't implement yet"
- `(GREEN)` = "I made a test pass"
- No status = meta work (docs, refactor)
- On amnesia recovery, grep for `(RED)` to find unfinished work

---

## Phase Structure Template

Copy this for each phase:

```markdown
## PHASE [N]: [Phase Name] 
**Goal:** [One sentence outcome]

**Estimated:** [X commits, Y hours]

### Step [N.1]: Write [Feature] Tests (SKELETON)
- [ ] Create test file
- [ ] Write `test_[behavior_1]()` calling real API with real assertions
- [ ] Write `test_[behavior_2]()` calling real API with real assertions
- [ ] Run tests: expect RED (code not implemented yet)

**Tests Written:**
- `test_[behavior_1]` - [What it validates]
- `test_[behavior_2]` - [What it validates]

**Acceptance:** All tests RED (failing because code doesn't exist, not because of placeholders)

**Commit Point:** `test([scope]): add tests for [feature] (RED)`

---

### Step [N.2]: Implement [Behavior 1]
- [ ] Implement [specific function]
- [ ] Make `test_[behavior_1]()` pass
- [ ] Run: `[test command]`

**Acceptance:** Test GREEN, others still pass

**Commit Point:** `feat([scope]): implement [behavior_1] (GREEN)`

---

### Step [N.3]: Implement [Behavior 2]
- [ ] Implement [specific function]
- [ ] Make `test_[behavior_2]()` pass
- [ ] Run: `[test command]`

**Acceptance:** Test GREEN, others still pass

**Commit Point:** `feat([scope]): implement [behavior_2] (GREEN)`

---

### Step [N.4]: Learning Checkpoint
- [ ] Update TODO_PLAN with findings

**Notes:**
```
[LEARNINGS]

What worked:
-

Challenges:
-

Decisions:
-

Next time:
-
```

**Commit Point:** `docs([scope]): update TODO with [phase] learnings`
```

---

## Checklist: Before Starting Implementation

Use this checklist before creating TODO_PLAN:

- [ ] Read design doc thoroughly
- [ ] Identify all major components/features
- [ ] Break each feature into testable behaviors
- [ ] Estimate: 1 behavior = 1 test = 1 commit
- [ ] Group behaviors into phases (2-5 commits per phase)
- [ ] Add learning checkpoints every 2-3 commits
- [ ] Write amnesia recovery protocol
- [ ] Include test philosophy section
- [ ] Define acceptance criteria as passing tests
- [ ] Pre-write commit messages
- [ ] Estimate total commits (each = 15-30 min)

---

## Quality Standards

### Good TODO_PLAN Metrics

**Commit granularity:**
- [OK] 1 commit per test passing (ideal)
- [WARN] 2-3 commits per feature (acceptable)
- [NO] 1 commit per phase (too coarse)

**Phase size:**
- [OK] 2-5 steps per phase (ideal)
- [WARN] 6-8 steps per phase (acceptable)
- [NO] 10+ steps per phase (too large, split it)

**Learning checkpoints:**
- [OK] Every 2-3 commits (ideal)
- [WARN] Every phase (minimum)
- [NO] Only at end (insufficient)

**Recovery time:**
- [OK] Can resume in <5 min from last commit (ideal)
- [WARN] Can resume in <15 min (acceptable)
- [NO] Must re-read all code (plan failed)

---

## Common Pitfalls

### "I'll write tests later"
**Problem:** Never happens, technical debt accumulates
**Solution:** Make tests block implementation (RED first)

### "This is too small for a commit"
**Problem:** Commit granularity too coarse, amnesia recovery hard
**Solution:** Commit every test that passes, no matter how small

### "I'll document at the end"
**Problem:** Context lost, learning notes incomplete
**Solution:** Learning checkpoints are mandatory steps

### "Acceptance criteria are obvious"
**Problem:** Subjective, not test-driven
**Solution:** Acceptance = specific tests passing

### "Phase 1 is complex, has 12 steps"
**Problem:** Too large, no recovery points
**Solution:** Split into Phase 1A, 1B, 1C (4 steps each)

---

## Examples

### Good Phase (Small, Test-First)

```markdown
## PHASE 3: Password Validation 
**Goal:** Validate password strength before account creation

**Estimated:** 4 commits, 1 hour

### Step 3.1: Write Password Tests (SKELETON)
- [ ] Create `tests/unit/test_password.py`
- [ ] Write `test_password_min_length()` calling validate_length() with real assertions
- [ ] Write `test_password_has_number()` calling validate_has_number() with real assertions

**Tests Written:**
- `test_password_min_length` - Rejects passwords <8 chars
- `test_password_has_number` - Requires at least one digit

**Acceptance:** Both tests RED

**Commit:** `test(auth): add password validation tests (RED)`

---

### Step 3.2: Implement Min Length Check
- [ ] Add `validate_length()` to `auth/validators.py`
- [ ] Make `test_password_min_length()` pass

**Acceptance:** Test GREEN

**Commit:** `feat(auth): validate password minimum length (GREEN)`

---

### Step 3.3: Implement Number Requirement
- [ ] Add `validate_has_number()` to `auth/validators.py`
- [ ] Make `test_password_has_number()` pass

**Acceptance:** Test GREEN

**Commit:** `feat(auth): validate password has number (GREEN)`

---

### Step 3.4: Checkpoint
- [ ] Update TODO with learnings

**Notes:**
```
What worked: regex patterns from stdlib
Challenges: none
Decisions: Used re.search instead of parsing
```

**Commit:** `docs(auth): update TODO with validation learnings`
```

### Bad Phase (Large, Implementation-First)

```markdown
## PHASE 3: User Authentication

### Step 3.1: Implement Auth System
- [ ] Password validation
- [ ] Email validation
- [ ] Session management
- [ ] Token generation
- [ ] Password hashing
- [ ] Rate limiting
- [ ] 2FA support

**Commit:** feat(auth): implement authentication system
```

**Problems:**
- 7 features before commit = hours
- No tests mentioned
- No recovery points
- Too broad

---

## Summary: The Golden Rules

1. **Tests FIRST** — Write failing test before any implementation
2. **One test, one commit** — Each passing test = checkpoint
3. **Small phases** — 2-5 commits max per phase
4. **Learning checkpoints** — Document every 2-3 commits
5. **Amnesia protocol** — Explicit recovery instructions
6. **Clear acceptance** — Acceptance = tests passing, not vibes

**Remember:** You're writing for a future version of yourself with zero memory. Make it impossible to get lost.

---

## Template Checklist

Before publishing TODO_PLAN, verify:

- [ ] BDD/TDD philosophy section present
- [ ] Testing philosophy section present (with timeouts, no-sleep)
- [ ] Amnesia recovery protocol present
- [ ] Current status summary table present
- [ ] Each phase has 2-5 steps maximum
- [ ] Each step = 1-2 commits (not 7)
- [ ] All steps have explicit commit messages pre-written
- [ ] Learning checkpoints every 2-3 commits
- [ ] Acceptance criteria = specific tests passing
- [ ] Definition of Done section present
- [ ] Progress tracking section present
- [ ] Language-specific test commands included

**If any checkbox is unchecked, revise the plan before starting work.**
