# Stories: tracking

What keeps the reverse map true as sessions and branches move.

- As a reviewer, the map is right when I ask, even though I never told
  anything about the session, the branch, or the PR.
- As a reviewer, when the herd renames a session, the map follows the
  session, not the old name.
- As a reviewer, when a session dies, it stops being offered as a
  destination.
- As a reviewer, when an agent checks out a different branch in the same
  session, the session moves to that branch's PR.
- As a reviewer, when a PR is opened after the session started, the
  session is on it the moment the PR exists.
- As a reviewer, when a PR is merged and its branch deleted, a session
  still sitting on that branch is shown as stale rather than lost.
- As a reviewer, two worktrees of one clone on two branches are two
  entries, not one.
- As the herd, I do not have to remember anything between runs for the
  map to be right. (Todd's daemon hypothesis is the opposite story, and
  both stay; phase 2 decides.)
