---
id: 2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file
title: Smoke checks isolate every path the code writes to
type: convention
area: [testing, harness]
projects: []
tags: [smoke-test, isolation, testing, state, scratch, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

A smoke check simulated an event (an agent app switching accounts) by pointing the file watcher
at a scratch copy of the log it reads, through the one environment variable that chooses the
input. That variable only chose what was read. The run still wrote its cursor, its watch state
and a raised alert into the real state directory. The next scheduled guardian run emailed a
false alert about the simulated event, which then had to be cleared by hand.

A second case of the same shape: a self-test built a throwaway KeePass fixture but resolved the
database path from the default, and wrote over the real one.

## The rule

**A smoke check that redirects one input is not isolated** unless every path the code can write
to is redirected too. Sandboxing the input creates a false sense of safety: the code looks like it
runs against test data while its writes land in the one shared state the real system depends on.
Any tool that takes one variable to point at test data but derives its outputs from a separate
default does this.

## How to apply

- Before a smoke check against anything stateful, list the variables and config values the code
  reads to decide **where it writes**, not only where it reads, and redirect all of them to the
  same scratch directory: `HOME`, `BRAIN_VAULT`, `BRAIN_STATE`, `TMPDIR`, database paths.
- Never let a test touch the real kdbx, the real `~/.claude`, the real scheduler or the real
  vault. Scheduler, mail and git adapters go through fakes in tests.
- As a second guard, code whose write path can double as a footgun refuses to run rather than
  write to a default: the file watcher exits 2 when its input log is not the real one unless the
  state directory is also outside the default.
- After the check, confirm the real state did not change (compare mtimes before and after).

## Links

- [[2026-09-15-runbook-brain-events]]
- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
