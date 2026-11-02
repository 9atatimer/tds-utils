# Tool -- architecture

> **Status:** APPROVED (the fixture's owner)

The fixture's architecture record: the seams Change reads and the
use-case surface Trace reads.

## Seams

| Axis of change | Seam | Kind | Why it is a seam |
|---|---|---|---|
| Where orders are kept | `Store` | port | a file today, a database later |
| When an order is stamped | `Clock` | port | the real clock, a fake in tests |

## Use-case surface

| Design behavior | Use case (signature) | Ports |
|---|---|---|
| An order is closed | `close_order(order: Order, *, store: Store) -> str` | Store |
| An order is reopened | `reopen_order(order: Order, *, store: Store) -> str` | Store |
| Orders | (`close_order`) | Store |
