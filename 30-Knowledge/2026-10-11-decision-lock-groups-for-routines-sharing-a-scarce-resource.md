---
id: 2026-10-11-decision-lock-groups-for-routines-sharing-a-scarce-resource
title: Routines that share a scarce resource join a lock group so they never overlap
type: decision
area: [harness]
projects: []
tags: [tasks, routines, scheduled-tasks, concurrency, flock, lock-group, quota]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-11
supersedes: []
---

# Lock groups for routines sharing a scarce resource

## What was decided

An agent routine can name a group in its front matter:

```yaml
lock_group: image-credits
```

Every routine with the same `lock_group` shares one lock, `<brain state>/task-locks/group-<name>.lock`
(`_bin/tasks.py`). A run holds it for as long as it lasts.

- A due task whose group is busy is skipped on that tick with its state untouched, and the runner log
  says `skipped <id>: lock group <name> busy (<holder>)`. The lock file carries a label naming the
  task that holds it, so the line says who.
- The process holding the group runs the group's other due tasks right after its own task ends, one
  after another (`run_group_followers`), re-reading the task state first because other processes may
  have recorded runs meanwhile. A blocked routine starts as soon as the group is free, not up to one
  poll later.
- flock dies with the process, so a killed run leaves no stale lock.
- `single_instance: true` still works inside a group: the group lock is taken first, then the
  routine's own.

## Why

`single_instance` ([[2026-09-24-decision-single-instance-flag-for-routines]]) stops one routine from
overlapping itself. It does nothing when two different routines draw on the same thing at the same
time: one browser session that cannot serve two agents, one generation quota with a per hour window,
one account that rate limits concurrent use. Two invented routines, a daily illustrated newsletter and
a weekly poster, both making images on the same service: started on overlapping schedules they split
the hourly window between them, and both came back with half their images refused.

## Alternatives considered

- **Shift the schedules apart.** Fragile: a long run still overlaps the next one, and every new
  routine on the resource has to be fitted around the others by hand.
- **One combined routine.** Merges jobs that have nothing in common except the resource, and a
  failure in one stops the other.
- **A wait inside the routine.** An agent sleeping on a lock burns its timeout and its tokens doing
  nothing. Skipping and running as a follower costs nothing while waiting.

## Consequences

- Late rather than overlapping: a routine in a busy group may start well after its slot. Routines
  that must run at an exact time do not belong in a group.
- Pair a group with the quota ledger ([[2026-10-10-convention-global-quota-ledger]]) when the shared
  resource is a quota: the group stops the overlap, the ledger stops the second run from starting
  with too little left.
