---
id: 2026-09-23-convention-hourly-tasks-use-the-every-nh-column
title: A sub-daily task is an every Nh row, never a scheduler job of its own
type: convention
area: [harness]
projects: []
tags: [tasks, cron, launchd, systemd, harness, scheduling, guardian]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

# Sub-daily tasks use the every Nh column

**A task that has to run more than once a day is an `every Nh` row in
`90-Meta/scheduled-tasks.md`. It never gets a launchd job, systemd timer or cron line of its own.**

`tasks.py` used to fire a row once a day: `routine_due` refused anything whose `last_run_date` was
today. The obvious workaround is a second scheduler, a job with a one-hour interval that calls
`tasks.py --force <id>`. It works, and it is wrong: the cadence then lives outside the registry, the
guardian sees a scheduler job it cannot explain, and the table's schedule is a lie about what
actually runs.

The infrastructure already had the hard part. The tasks runner polls **every 10 minutes**; a
sub-daily task needs no new timer, only a due-ness rule that can express the gap.

## The shape

- `time` accepts `every Nh` (`every 1h`, `every 6h`) beside `HH:MM` and `--`.
- An interval row **ignores the once-a-day mark** and measures the gap since `last_run_at`.
- `days` still applies, so `every 1h` with `1-5` is hourly on weekdays only.
- **A missed interval is not caught up.** If the machine slept through an hour, the next poll runs
  it once and the clock restarts. No burst of catch-up runs, no report at an odd time.

## Where it lives

| Piece | File |
|---|---|
| The rule | `_bin/guardian_core/domain.py`: `parse_every_hours`, `routine_due` (takes `last_run_at`) |
| The column parser | `_bin/tasks.py`: `read_registry` |
| The state it reads | `last_run_at`, already written by the runner |
| Tests | `_bin/guardian_core/domain_test.py`, `_bin/tasks_test.py` |
| The format, for whoever edits the table | `90-Meta/scheduled-tasks.md`, Columns |

## Why it matters

The registry is meant to be **the single inventory of everything that runs on a schedule**. A
scheduler job doing the real scheduling behind a row is the same drift as a task only the desktop
app knows about, with more moving parts. Keeping the cadence in the row means `tasks.py --list`
tells the truth, the guardian's audit of scheduler jobs stays a closed set, and the per-task log,
the alerting, the routine token and the success contract are the ones every other task uses.

An hourly routine is also in flight far more often than a daily one, which makes two things more
likely: a run that overruns into the next tick
([[2026-09-24-decision-single-instance-flag-for-routines]]) and an edit landing while it runs
([[2026-09-23-failure-editing-a-routine-file-while-its-task-is-running]]).
