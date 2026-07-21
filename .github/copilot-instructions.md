# Copilot Code Review Instructions

You are reviewing a pull request. Optimize for catching real defects. Be terse.
Raise fewer, higher-value comments. A review that surfaces one real bug is worth
more than ten that polish prose.

## Comment on these (high value)

- Correctness bugs: wrong logic, off-by-one, inverted conditions, unhandled
  cases, incorrect API or contract usage.
- Concurrency and ordering: races, deadlocks, unsynchronized shared state,
  non-atomic read-modify-write.
- Error handling and failure modes: swallowed errors, unchecked fallible calls,
  wrong error propagation, resource leaks (files, handles, locks, temp dirs),
  missing cleanup on error paths.
- Security and boundaries: injection, unsafe input handling, path or permission
  issues, secret leakage, TLS/auth mistakes, unsafe deserialization.
- Data integrity: corruption, loss, or migration hazards; destructive
  operations without guards.
- Portability that actually breaks: platform-specific syntax used where the code
  must run cross-platform (e.g. a GNU-only flag in a script that must also run
  on BSD/macOS).
- Public API or backward-compatibility breaks.
- Test gaps that hide a real, reachable risk in the change under review.

## Do NOT comment on these (noise)

- Wording, phrasing, grammar, or tone of comments, docstrings, log messages, or
  commit text -- unless the text is factually wrong in a way that misleads about
  what the code does.
- Micro-precision of prose that already describes correct code ("unset" vs
  "unset or empty", "-z" vs presence checks, and the like).
- Renaming an unused parameter to `_x`, or other cosmetic naming preferences.
- Formatting, whitespace, or import ordering -- anything a linter or formatter
  owns.
- Restating what the diff does, or praising it.
- Style preferences not codified in this repository's conventions.
- Speculative "what if someone called this differently" concerns when the actual
  call sites are correct and the misuse is not reachable.

## How to weight a comment

- If the comment would not change whether the code is correct, safe, or
  materially more maintainable, do not post it.
- When unsure whether something is a real defect, say so briefly rather than
  asserting it -- and do not manufacture an issue just to have something to say.
- Prefer proposing a concrete fix over describing a preference.
