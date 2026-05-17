#!/usr/bin/env bash
# 07_migrator_parses_todo_plan.sh — parseOpenTasks extracts only
# `- [ ]` rows under "## Open Tasks", attaches subsystem from `###` headings,
# and stops at the first `---` divider.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

require_node

MIGRATE_MODULE="${GADMIN_ADMIN_DIR}/migrate-todo-plan.mjs"

run_node --input-type=module -e "
import { parseOpenTasks } from '${MIGRATE_MODULE}';

const md = [
  '# TODO_PLAN.md',
  '',
  '## How to use this file',
  '- Some unrelated bullet that should NOT become an issue',
  '',
  '---',
  '',
  '## Open Tasks',
  '',
  '### gadmin hardening',
  '',
  '- [ ] Task GA1: **Stale path comments.** Body text here. (Copilot ID.)',
  '- [ ] Task GA2: just a plain task with no bold title.',
  '',
  '### Terminal UX',
  '',
  '- [ ] Task T1: **Improve brand theme matching** — fuzzy match needed.',
  '- [x] Task T0: already done — should be skipped.',
  '',
  '---',
  '',
  '## Lessons Learned',
  '- [ ] Task FAKE: lessons-learned bullet should be ignored.',
].join('\\n');

const tasks = parseOpenTasks(md);
let fails = 0;
function check(name, cond, detail) {
  if (!cond) { console.error('FAIL', name, detail || ''); fails++; }
}

check('count==3', tasks.length === 3, JSON.stringify(tasks.map(t => t.id)));
check('GA1.subsystem', tasks[0]?.subsystem === 'gadmin');
check('GA1.title',     tasks[0]?.title === 'Stale path comments.');
check('GA2.subsystem', tasks[1]?.subsystem === 'gadmin');
check('GA2.title-first-sentence', tasks[1]?.title === 'just a plain task with no bold title');
check('T1.subsystem',  tasks[2]?.subsystem === 'terminal');
check('T1.title',      tasks[2]?.title === 'Improve brand theme matching');
check('no-completed',  !tasks.some(t => t.id === 'T0'), 'completed task leaked');
check('no-lessons',    !tasks.some(t => t.id === 'FAKE'), 'lessons-learned leaked');

if (fails) {
  console.error('migrator parser tests:', fails, 'failure(s)');
  console.error('tasks:', JSON.stringify(tasks, null, 2));
  process.exit(1);
}
console.log('migrator parser tests ok');
"
