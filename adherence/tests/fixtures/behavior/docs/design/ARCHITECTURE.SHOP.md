# Shop -- architecture

> **Status:** APPROVED (the fixture's owner)

The Behavior-driven fixture's architecture record: the seam and the
use-case surface Kept test and Public surface read.

## Seams

| Axis of change | Seam | Kind | Why it is a seam |
|---|---|---|---|
| Where quotes are kept | `Store` | port | a file today, a database later |

## Use-case surface

| Design behavior | Use case (signature) | Ports |
|---|---|---|
| A tariff is looked up | `tariff(code: int) -> int` | none |
| A tariff is quoted | `quote_tariff(code: int, *, store: Store) -> int` | Store |
