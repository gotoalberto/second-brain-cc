---
id: 2026-09-24-decision-single-instance-flag-for-routines
title: Routines can opt into single_instance so tasks.py never runs them twice at once
type: decision
area: [harness]
projects: []
tags: [tasks, routines, scheduled-tasks, concurrency, flock, timeout]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-24
supersedes: []
---

# Routines can opt into single_instance

An agent routine whose front matter says `single_instance: true` holds an exclusive flock on
`<brain state>/task-locks/<id>.lock` for its whole run (`_bin/tasks.py`, `task_lock`).

- A scheduled tick that finds it still running skips it, logs `skipped <id>: already running` in
  the runner log and leaves its state alone; the next tick after it ends decides again.
- `tasks.py --force <id>` on a running one is refused with exit 75 (`EX_TEMPFAIL`).
- flock dies with the process, so a killed run leaves no stale lock. The lock file only carries
  the holder's pid and start time, to say who is running.

**Why the old guard was not enough.** `last_run_at` is saved when a run ends, so while an hourly
run is still going the next tick sees the previous hour's timestamp and starts a second copy.
For a routine that acts on something outside the vault (screening a queue, replying to messages),
two copies do the same work twice.

**Scope is opt-in.** Every other task runs as before. Add the flag to a routine only
where two overlapping runs would do harm, typically an `every Nh` row
([[2026-09-23-convention-hourly-tasks-use-the-every-nh-column]]) whose run can outlast its interval.

## Paired with timeout_minutes

A routine can also set `timeout_minutes: <n>` in its front matter; the default stays 30 minutes
(`DEFAULT_TIMEOUT`). It is for a routine whose job has no fixed size, a backlog it should work
through completely on each run rather than a fixed batch per interval. An overrun past the next
tick is then fine, because `single_instance` makes that tick wait. A per-run cap on the batch was
the alternative and was rejected: it leaves work waiting for no reason when the queue is long.
