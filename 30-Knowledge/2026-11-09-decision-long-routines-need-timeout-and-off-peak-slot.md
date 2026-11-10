---
id: 2026-11-09-decision-long-routines-need-timeout-and-off-peak-slot
title: "Long agent routines need an explicit timeout and an off-peak slot"
type: decision
area: [harness]
projects: []
tags: [routines, timeout, schedule, tasks-py, coverage]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-09
supersedes: []
---

## What happened

A daily search routine produced partial runs for a week: it read a handful of feed posts, skipped one of
its passes and never got to another, and still sent its report. The routine file had no
`timeout_minutes`, so `tasks.py` applied its 30 minute default, and nothing gated the send on the passes
having been done.

## Decision

- A routine that does a full multi-pass job sets `timeout_minutes` explicitly, from the pace measured on
  a real run plus a margin.
- Coverage is enforced, not hoped for: the routine records each pass as it does it (a small state file
  or a counter script), and the send refuses a report whose passes are incomplete without a recorded
  reason. The report says which passes were done.
- The slot is chosen against the queue. On a machine where one runner process takes due tasks one after
  another, a two hour routine placed just before a cluster of short morning routines delays all of them;
  put it after the cluster, or where its own delay matters least.

## Why

A timeout that kills a run halfway looks, from the outside, exactly like a run that decided there was
little to report. Only an explicit budget and a coverage gate make the difference visible.

## Links

- [[2026-10-14-decision-scheduled-task-models-and-fallback-repair]]
- [[2026-09-24-decision-single-instance-flag-for-routines]]
