# TODO: Time Machine workspace backup intelligence

## Problem

Time Machine has no whitelist/pattern logic. You can only blacklist
(exclude) specific paths. For a developer workspace like ~/workplace,
you want to back up source code (especially uncommitted work) but not
build artifacts, caches, node_modules, etc.

## Half-baked ideas

### .gitignore-driven exclusion

A cron job or launchd agent that:
- Walks ~/workplace for .gitignore files
- Parses the ignored patterns and resolves them to actual directories
- Runs `tmutil addexclusion` on each

Pros: .gitignore is already maintained per-project, knows what's junk.
Cons: .gitignore also excludes things you DO want TM to catch (.env,
local configs, scratch files). The whole point of TM is to back up
what git doesn't.

### Heap-allocation model

Start with ~/workplace fully excluded from TM. The agent notices a
project subtree is "important" (has a .git dir? has recent commits?)
and selectively un-excludes it, then individually excludes the junk
within it.

Pros: conservative by default, only backs up what you've opted in.
Cons: complex state management. What triggers "important"? How do
you un-exclude in TM? (You can't — you can only remove an exclusion,
which means the whole subtree floods back in.)

### Growth-watch model

Periodically `du` known-included dirs and alert (or auto-exclude)
when something grows past a threshold. Catches the "someone dropped
a 4 GB log file next to code" case.

Cons: reactive, not preventive. Damage is done by the time you notice.

## What might actually work

Probably a combination:
1. Start with a curated pattern list (node_modules, build, target,
   DerivedData, .gradle, __pycache__, etc.) — the 80% case.
2. Cron sweep that finds new dirs matching those patterns and excludes.
3. Growth alerting for everything else.
4. A per-project `.tminclude` or `.tmexclude` override file for
   fine-tuning, read by the sweep script.

## Related

- bin/timemachine-audit — current tool, audits ~/.* dirs only
- Could extend timemachine-audit or build a companion `timemachine-sweep`
