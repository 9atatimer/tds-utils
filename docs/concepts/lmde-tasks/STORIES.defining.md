# Stories: defining

Writing a task down and keeping it in git.

- As a task author, I can write a task's definition -- what it runs, when,
  with which permissions, in which sandbox, against which LLM backends --
  in one place I can read back later.
- As a task author, I can commit that definition to git and see every
  past version of it.
- As a task author, I can diff a task's definition between two runs and
  see what changed.
- As a task author, I can disable a task without deleting it.
- As a task author, I can dry-run a task and see what it would do without
  it doing it.
- As a task author, I can name which LLM backends a task may use -- a
  cloud model, a subscription, a local model -- and which it may not.
- As a task author, I can write a task that touches no LLM at all and
  have it live alongside the ones that do.
- As a task author, I can copy an existing task as the starting point for
  a new one.
- As a task author, I can see, before enabling a task, what it will be
  allowed to spend and how long it will be allowed to run.
