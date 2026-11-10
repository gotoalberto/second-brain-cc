---
id: 2026-11-08-decision-x-linkedin-tasks-share-social-lock-and-wait
title: "Routines that drive the same browser accounts share a lock group and wait for it"
type: decision
area: [harness]
projects: []
tags: [routines, lock-group, browser, x, linkedin, tasks-py, browser-lock]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-08
supersedes: []
---

## Rule

- Every routine that drives the same accounts in this machine's Chrome (X, LinkedIn, any site where
  several accounts share one browser profile) names the same group in `lock_group:`, which is a list
  now: `lock_group: social, image-credits`.
- A due routine whose group is busy **waits** for it, with no time limit, and starts when it is free.
  `timeout_minutes` counts from that start, never the wait. While it waits it holds its own task lock,
  so the ticks that come meanwhile see it as running and leave it alone. Groups are taken in sorted
  order, so two routines that share several never deadlock.
- A run that waited past midnight is recorded on the day it was due: waiting must never cost a routine
  its next day's run.
- Before each task the runner re-reads the state, so a process that waited does not rerun what other
  ticks ran meanwhile.
- Interactive sessions take the same lock with `_bin/browser_lock.py hold --group <name>` and let go
  with `release`. Inside a routine `hold` does nothing, since tasks.py already holds the routine's
  groups.
- `release` frees only the caller's own hold. A session whose `hold` had timed out (exit 75, it held
  nothing) once ran `release` and freed the hold of another session that was using the browser; now a
  hold owned by another Claude session is refused with exit 75 and the holder printed. `--force` is only
  for the user's explicit word or a holder known to be stuck.

## Why

A session switched an X account while a routine was posting from that same Chrome, and the routine went
on in the wrong account. Before this change a busy group made a routine skip the tick, which cost it its
day, and some routines that drove the browser had no lock at all.

## Where

`_bin/task_locks.py` (the one module for lock files, used by the runner and by browser_lock.py),
`_bin/tasks.py` (`run_task`, `group_locks`, `refresh_state`), `_bin/browser_lock.py`, their tests.

## Links

- [[2026-10-11-decision-lock-groups-for-routines-sharing-a-scarce-resource]]
- [[2026-11-08-decision-chrome-restart-only-desktop-chrome-under-chrome-lock]]
- [[2026-11-10-convention-browser-lock-hold-in-button-sessions]]
