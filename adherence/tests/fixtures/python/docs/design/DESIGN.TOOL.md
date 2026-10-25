# Tool

> **Status:** APPROVED (the fixture's owner)

The adherence engine's Python fixture: a design record shaped like
DESIGN.ARCH-ADHERENCE.md, read by the markdown records adapter.

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| An order is closed | Given an open order, When it is closed, Then the store holds it closed |
| An order is reopened | Given a closed order, When it is reopened, Then it is open again |
| Orders | Given orders. |

## Domain Language

- **Order.** What a customer asks for. Invariant: one status at a time.
- **Store.** Where orders are kept.
