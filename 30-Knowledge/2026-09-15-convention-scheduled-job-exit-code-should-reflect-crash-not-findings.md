---
id: 2026-09-15-convention-scheduled-job-exit-code-should-reflect-crash-not-findings
title: A scheduled repair job exits non-zero only when the run itself fails
type: convention
area: [harness, monitoring]
projects: []
tags: [scheduler, launchd, systemd, exit-code, monitoring, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

The guardian's repair command, which the scheduler runs every 15 minutes, exited 1 whenever any
finding was still open, even a warning. The scheduler recorded a failed last run, and the
guardian's own health check then reported its own job as failing. Since the guardian is what
leaves findings open until they are fixed, the alert could never clear: the tool meant to catch
that class of problem was generating it.

## The rule

One exit code was answering two questions: "did the run work?" and "did it find something
wrong?". They need two signals.

- The command a person or a script runs to **ask** whether anything is wrong (`guardian.py check`)
  uses severity in its exit code: 0 ok, 1 warn, 2 fail. That is the right contract for a caller
  who acts on the answer.
- The command a **scheduler** runs to do the work (`guardian.py repair`) exits 0 whenever the run
  completed, whatever it found, and non-zero only when its own logic failed. Findings travel
  through the tool's own channels (notification, email, log, `status`), never through the
  scheduler's exit status.
- As a second guard, a probe that reports "job X's last run failed" exempts the monitoring job's
  own label, so a genuine crash still shows in its own log without an alert loop.

## How to apply

Before wiring any health check into launchd, systemd or cron, decide which exit code means
"broken" and which means "found something", and never let the second alias the first.

## Links

- [[2026-09-15-runbook-brain-guardian]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
