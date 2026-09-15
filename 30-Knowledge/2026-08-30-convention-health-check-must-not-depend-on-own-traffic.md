---
id: 2026-08-30-convention-health-check-must-not-depend-on-own-traffic
title: Liveness signals move independently of the system's own activity
type: convention
area: [monitoring]
projects: []
tags: [health-check, liveness, freshness, heartbeat, monitoring, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

A background worker was running and processing its queue, yet the project's status page kept
saying "the worker is stalled". Freshness had been computed as the timestamp of the last record the
project's own users created, not the last item the worker had processed. With little activity, a
quiet week was indistinguishable from a dead worker.

## The rule

A liveness or freshness signal is measured against something that moves whether or not there is work
to do: a clock-driven heartbeat written by the process itself, the
scheduler's own tick. Never against the system's own output, which can legitimately go quiet. A
heartbeat that only beats when there is a customer is not a heartbeat.

Claiming to be broken while working is the worse of the two lies a health check can tell: it destroys
the credibility the check exists to build.

## How to apply

- Read the processor's real checkpoint or cursor, not the latest business event.
- Where an undocumented checkpoint encoding has to be decoded, test that the fields are read from the
  right positions: a wrong window returns a small plausible number, not an error.
- Keep a second independent signal (a heartbeat timestamp) for when the first is ambiguous.
- The same idea drives hook liveness in this repo: every hook writes a heartbeat line when it runs,
  and a synthetic probe runs the hooks in a scratch state, so health does not depend on a session
  happening to exercise them. [[2026-09-15-runbook-brain-guardian]]

## Links

- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
