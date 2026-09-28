# Stories: running

A run firing, and what bounds it.

- As an operator, I can rely on a task firing on its schedule while the
  laptop is awake.
- As an operator, I can see that a run was missed because the laptop was
  asleep or off, rather than have it silently skipped.
- As a task, I run inside the sandbox my definition names and cannot reach
  outside it.
- As a task, I can use only the credentials my definition grants me.
- As a task, I stop when I hit my budget, and I stop when I hit my
  timeout, whichever comes first.
- As a task, I do not start a second run while my previous run is still
  going.
- As an operator, I can trigger a run by hand, outside its schedule.
- As an operator, I can stop a running task.
- As the LLM inside a task, I can find out how much budget I have left.
- As a task, I can post a short message that the operator will see on the
  dashboard.
