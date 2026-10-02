---
id: 2026-09-26-convention-gate-a-report-on-proof-its-prerequisite-ran
title: Gate a scheduled report on proof that its prerequisite step ran
type: convention
area: [harness]
projects: []
tags: [routine, report, stamp, run-id, digest, email, scheduled-task]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-26
supersedes: []
---

# Gate a scheduled report on proof that its prerequisite step ran

## Context

A daily report promised that it had read the user's mailbox before ranking what it found. Several
runs claimed to have read the whole mailbox and finished far too fast to have done so: the agent had
been handed a raw dump far too big to read, skimmed it, and missed a message that mattered. The text of the report was the
only evidence that the step had happened, and the text was wrong.

## The rule

When a scheduled report says it did a step (read the mailbox, ran the checks, refreshed the data),
the send refuses unless that step left proof:

- **A stamp written by the step itself**, in the state directory, carrying this run's id, the time it
  was made and what it covered (the window, the number of items). A stamp from another run, or older
  than a fixed maximum age, does not count.
- **The body states the step's own count.** The send compares the number in the stamp with the text
  of the report, so a report that skipped reading what it fetched cannot pass by accident.
- **A failed step still sends.** When the step could not run (the account was offline, the API
  refused), it stamps a failure with the reason, and the report must then carry a fixed marker and
  that reason at the top. Silence is worse than a report that says what it could not do.

The gate lives in the send command (a flag such as `--require-review`), so the routine cannot reach
the user without passing it, and the routine's allowlist only grants the send with that flag.

## Reducing a source too big to read

Proof that a step ran does not help if the step cannot be done well. A two-week mailbox dump was
megabytes of JSON, most of it machine notifications and tracking URLs. The fix was a digest that fits
one read, written by a script and read whole:

- messages from people and from tracking systems that matter (replies from people, support tickets) in full, with
  quoted history and long URLs trimmed;
- alerts as one row per item, deduplicated by their own id;
- newsletters and automated notices one line each;
- everything else counted.

The raw dump stays on disk and is opened only for one message at a time, when the digest points at
it.

## Links

- [[2026-09-15-convention-success-contracts-must-check-the-log-not-the-models-final-words]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
- [[2026-09-15-runbook-brain-routine-auth]]
