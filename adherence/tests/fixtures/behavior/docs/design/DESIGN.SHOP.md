# Shop

> **Status:** APPROVED (the fixture's owner)

The Behavior-driven fixture's design record, read by the markdown records
adapter: one behavior a test keeps and one no test keeps.

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| A tariff is looked up | Given a code, When its tariff is looked up, Then the tariff is returned |
| A tariff is quoted | Given a code, When it is quoted, Then the store holds the quote |

## Domain Language

- **Tariff.** What a code costs.
- **Quote.** A tariff given for a code.
- **Code.** What a tariff is looked up by.
- **Store.** Where quotes are kept.
