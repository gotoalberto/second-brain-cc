---
id: 2026-10-24-decision-success-contract-day-subject-for-days-already-delivered
title: "Success contract day_subject for days already delivered under another run"
type: decision
area: [harness]
projects: []
tags: [routines, success-contract, send-log, guardian, double-run]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-24
supersedes: []
---

# Success contract day_subject for days already delivered under another run

## What happened

A daily routine mails the user the day's options. One evening the user asked for the next day's
options in a chat session, which sent them by hand: a real delivery, logged in the send log with no
run id. The next morning the scheduled run's own guard saw the day was done, correctly sent nothing,
and ended on its success line. The guardian then raised a failure: the contract required one delivered
email for this run, and the send log held none under the run's id.

## What was decided

The success contract takes an optional `day_subject`, a strftime format such as
`"Daily report %d/%m:"`. A send whose subject starts with it, formatted on the run's date, and whose
timestamp is within the last 36 hours counts for the run, whatever its run id, or none.

- `_bin/routine_auth_core/domain.py`: `SuccessContract.day_subject`; `parse_success_contract` accepts it
  only as a format containing `%` and only together with `required_sends` and `sends_to`, otherwise it
  is a contract problem; `day_sends(records, day_subject, now)` with `DAY_SEND_WINDOW` of 36 hours.
- `_bin/routine_auth_core/application.py`: `_apply_contract` adds those records to the run's sends.
- The routine's guard keys "already done" on what was delivered for the date, never on when a log entry
  was written.

## Alternatives considered

- Trust a "skipped" marker in the answer: rejected. Only the send log proves a delivery, never the
  agent's claim ([[2026-09-15-convention-success-contracts-must-check-the-log-not-the-models-final-words]]).
- Match on the subject alone: rejected; subjects carry no year, hence the window.

## Consequences

- A manual send the evening before is a legitimate delivery for the day, and the contract sees it
  without weakening the rule that proof comes from the send log.
- Any routine whose day can be delivered by hand can reuse `day_subject`.

## Links

- [[2026-09-15-runbook-brain-routine-auth]]
