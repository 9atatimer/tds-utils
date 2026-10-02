# Stories: triggering

> Part of [CONCEPT.md](CONCEPT.md). Phase 1 -- not acceptance criteria.

- As Todd, I can give a chore a webhook trigger instead of a schedule, and
  a path of its own under the chores webhook endpoint.
- As Todd, I can point a GitHub repo's webhook at that path and see the
  chore run when the repo changes.
- As Todd, I name a chore's key by its label; no key value is ever written
  into a chore.
- As Todd, I know a push without the proper key runs nothing.
- As a chore, I am handed the webhook payload as my context.
