---
id: 2026-09-19-verification-scheduled-tasks-on-a-second-machine
title: Scheduled tasks on a second machine and where machine pinning applies
type: reference
area: [harness]
projects: []
tags: [tasks, scheduled-tasks, machines, linux, verification]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

Checked by running tasks on two machines, not by reading the code: every conclusion reached by
reading that day turned out wrong, and every one reached by executing turned out right.

## What held

- **Machine pinning holds on the scheduled path.** With a task pinned to the second machine, a
  `tasks.py` pass on the first ran nothing and created none of the task's output. `--list` showed it
  as `belongs to <machine>`.
- **Agent routines run end to end on Linux** under the scheduler's restricted environment.

## What did not

**`tasks.py --force <id>` ignored the `machine` column.** Forcing a task pinned to the second machine
from the first ran it on the first, and the proof was not the exit code: the task's output appeared
on both machines. Pinning carries side effects, not tidiness: a task pinned to one machine so that it
posts to a chat channel once posts twice when forced elsewhere.

Fixed: `--force` refuses a task whose `machine` is neither `*` nor this machine (exit 3) and names the
owner; `--anywhere` overrides it deliberately. `--list` prints on its second line what this host
matches as: its hostname and its stable machine key.

## Machine names

The same machine can answer to more than one name, and a hostname can change or be shared. The
registry's `machine` column accepts the hostname and the stable key; prefer the key
([[2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label]]).

## Generated files on two machines

Pulling on the second machine failed twice over locally modified generated files (the skills
catalogue). Two machines regenerating the same derived files collide routinely; committing them where
they were made and rebasing is enough, since they are rebuilt from their sources.

## Links

- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
- [[2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label]]
