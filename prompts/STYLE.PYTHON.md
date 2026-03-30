# Python Style Guide

> Opinionated rules for this project. Not a Python tutorial.

## Philosophy

**BDD/TDD is THE way.** Every feature, every fix, every refactor starts with a failing test. No exceptions.

1. **Tests first, always** — Write the test, watch it fail, make it pass, refactor
2. **Readability is paramount** — Code is read far more than written
3. **Explicit over implicit** — No magic, no surprises
4. **Type everything** — Static analysis catches bugs before runtime
5. **Automate formatting** — Never argue about style

> **The Red-Green-Refactor cycle is not optional.** If you're writing code without a failing test driving that code, you're doing it wrong.

## Toolchain

| Tool | Purpose |
|------|---------|
| **uv** | Package management |
| **Ruff** | Linting + formatting |
| **mypy** | Static type checking (strict mode) |
| **pytest** | Test runner |

All config lives in `pyproject.toml`. Python 3.11+ required.

## Formatting Rules

- **Line length**: 88 characters (project default)
- **Quotes**: Double quotes
- **Trailing commas**: Always (cleaner diffs)
- **Imports**: Absolute only, no star imports, sorted by Ruff

## Type Annotations

Annotate everything. Use modern syntax (PEP 585, PEP 604):

```python
# Yes
def get_user(user_id: int) -> User | None: ...
items: list[str] = []

# No (legacy)
from typing import Optional, List
def get_user(user_id: int) -> Optional[User]: ...
```

Use `Protocol` over ABC. Use `Self` for fluent returns. **Never use `Any`** — prefer `TypeVar` or `Generic` if truly polymorphic.

## Functions

- **Single responsibility**: One function, one job
- **Keyword-only args**: Use `*` after positional args
- **No boolean traps**: `connect(host, use_tls=False)` not `connect(host, False)`
- **Return early**: Guard clauses at top, not nested ifs
- **Max 5 args**: Use a dataclass if you need more

## Classes

- **Dataclasses for data**: `@dataclass(frozen=True, slots=True)`
- **Pydantic for validation**: External input boundaries
- **Composition over inheritance**: Inject dependencies, don't inherit
- **JSON serialization**: Use Pydantic. `camelCase` keys at API boundaries, `snake_case` internally

## Error Handling

- **Custom hierarchy**: `AppError` -> `DomainError` / `InfrastructureError`
- **Specific messages**: `raise NotFoundError(f"User {id} not found")`
- **Chain exceptions**: `raise NewError(...) from e`
- **Never catch bare `Exception`**

## Async

- **Async all the way**: If you call async, you are async
- **Use `asyncio.TaskGroup`**: For concurrent operations
- **Timeouts mandatory**: `async with asyncio.timeout(30):`
- **Context managers**: For all async resources

## Testing

### The TDD Workflow (Non-Negotiable)

1. **RED**: Write a failing test that describes the behavior you want
2. **GREEN**: Write the minimum code to make the test pass
3. **REFACTOR**: Clean up while keeping tests green

You do not write production code without a failing test demanding it. Period.

### Structure

- **BDD style**: Given-When-Then in every test (describes behavior, not implementation)
- **Fakes over mocks**: In-memory implementations beat `Mock()`
- **factory_boy**: For test data factories
- **hypothesis**: For property-based testing

### Critical Rule: Never Sleep

**NEVER use `time.sleep()` or `asyncio.sleep()` in tests.**

```python
# FORBIDDEN
await asyncio.sleep(0.1)  # NO!

# Instead: FakeClock, Events, or mock the sleep
fake_clock.advance(5.0)  # Instant
await done_event.wait()  # Coordination
mocker.patch("asyncio.sleep", return_value=None)
```

### Test Naming

```python
def test_<action>_<scenario>_<expected>() -> None:
    """Given X, When Y, Then Z."""
```

### Coverage

90% minimum. Config in `pyproject.toml`.

## Project Structure

Hexagonal architecture (Ports & Adapters):

```
src/cr_magic/
├── domain/      # Core logic, no deps
├── ports/       # Interfaces (Protocol)
├── adapters/    # Implementations
├── cli/         # Entry points (Click)
└── orchestration.py  # FSM + port wiring
```

**Dependency rule**: `adapters` -> `ports` -> `domain` (inward only)

## Dependencies

- Use `>=` with minimum version for direct deps
- Never `==` (too restrictive) or unpinned (too loose)

## Docstrings

Google style. Required for public functions:

```python
def process(order: Order, *, notify: bool = True) -> Result:
    """Process an order and update inventory.

    Args:
        order: The order to process.
        notify: Send email notification.

    Returns:
        Processing result with updated status.

    Raises:
        InsufficientInventoryError: Items out of stock.
    """
```

## Quick Checklist

- [ ] **Test written FIRST** (Red-Green-Refactor)
- [ ] Tests follow Given-When-Then
- [ ] No sleeps in tests
- [ ] All functions typed
- [ ] No `# type: ignore` without explanation
- [ ] Ruff + mypy pass
- [ ] Coverage >= 90%
