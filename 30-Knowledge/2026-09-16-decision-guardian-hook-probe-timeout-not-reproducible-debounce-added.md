---
id: 2026-09-16-decision-guardian-hook-probe-timeout-not-reproducible-debounce-added
title: Guardian hook probe timeouts and the probe mail debounce
type: decision
area: [harness]
projects: []
tags: [guardian, hooks, probe, timeout, alerting, email, debounce, investigation]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## What happened

The guardian's hook probe raised three FAIL findings in one run (`hooks:probe:stop-memory-gate`,
`hooks:probe:sync`, `hooks:probe:session-end`): those hooks timed out at their 10 to 20 second
budgets in the probe's scratch environment. All three were gone on the guardian's next run, 15
minutes later, with no change in between, and the user had already been paged for them.

## Investigation outcome

Not reproduced. The exact scratch layout the probe uses was rebuilt and every canonical hook was
timed, cold and under artificial CPU load: every one finished in 0.1 to 0.4 seconds against 5 to 20
second budgets, and the slow-operation log stayed empty. The one artifact that could have shown
where the time went lived inside the probe's scratch directory, which the probe deletes when it
finishes. The cause is unknown; the note records the method so the result is not read as "the hooks
are fine" forever.

## What was decided

A debounce for `hooks:probe:*` FAILs only, in `probe_mail_worthy()` in
`_bin/guardian_core/domain.py`:

- a probe FAIL new this run gets the desktop notification but is not mail-worthy;
- still open on the next run, it becomes mail-worthy and `mail_decide()` pages it once;
- after that it is carried by the daily digest like any other open FAIL;
- resolved and later back, it starts silent again.

Every other FAIL is mail-worthy on its first appearance: nobody but a person renews a dead token, so
the first occurrence is the only prompt chance to say so.

## Alternatives considered

- **Raise the probe's timeouts.** Rejected: there is no evidence the timeouts were real slowness, and
  loosening a budget to hide an unproven cause hides the next real regression too.
- **Never mail probe findings.** Rejected: a probe failure that stays open for hours is exactly what
  needs a person.
- **Escalate every FAIL by duration.** Not built: only probe findings have been seen to clear by
  themselves within one cycle.

## Consequences

- If a probe finding ever needs a person faster than one cycle, this debounce is the wrong lever.
- If probe timeouts recur, capture the elapsed time and output before the scratch directory is
  deleted, then investigate.

## Links

- [[2026-09-20-decision-guardian-mail-only-for-findings-a-person-must-fix]]
- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
