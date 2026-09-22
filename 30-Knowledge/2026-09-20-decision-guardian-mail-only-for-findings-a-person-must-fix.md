---
id: 2026-09-20-decision-guardian-mail-only-for-findings-a-person-must-fix
title: Guardian mail policy for findings a person must fix
type: decision
area: [harness]
projects: []
tags: [guardian, alerting, email, severity, repair, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-20
supersedes: []
---

## What was decided

The guardian's inbox is owned by one pure function, `mail_decide(mail_worthy, previous, now)` in
`_bin/guardian_core/domain.py`. It receives only the mail-worthy findings (FAILs still open after
this run's repair was attempted, after the probe debounce) and the previous mail state, and returns
what to send: one mail the first time a finding becomes mail-worthy, then at most one digest every
24 hours while any stays open. Its state lives in `state["alerts"]["mail"]` as `mailed` (the keys
already paged) and `last_digest`. A key that resolves drops out of `mailed`, so a fresh occurrence
pages again.

`_alert()` in `_bin/guardian_core/application.py` keeps two independent channels:

- the desktop notification, built from `decide()`'s per-run actions (new, escalated and resolved
  findings, and repairs), unchanged;
- the mail, built only from `mail_decide()`.

A repair that worked, a problem that resolved, a warn: desktop and `guardian.py status` only, never
mail.

## Why

The first version gated the mail on "is any FAIL open" and then mailed every action of that run. A
successful, unrelated repair therefore reached the inbox whenever some other FAIL happened to be
open. In the working vault this came from, one agent file was reinstalled on every scheduled run
(a hash comparison that never matched on a second machine), and a routine had been failing for days,
so every repair notice was mailed: dozens of mails a day about something nobody could act on. The
module's own docstring already said a successful repair is not an inbox message; the code did
something else.

## Alternatives considered

- **Skip repair actions in the mail loop.** Stops this one flood but leaves the inbox riding on the
  desktop actions, which mix repairs, resolutions and real failures. The next new action kind could
  reopen the same hole. Rejected in favour of giving mail its own function and its own tests.
- **Page once and never again.** Rejected: a fail mailed once can fall off the radar. One digest a
  day while something needs a person is still a request for attention, not noise.

## Consequences

- A new kind of finding that should reach the inbox goes through `mail_decide()`. Do not add a mail
  branch inside `_alert()`'s notification loop; that loop is desktop only.
- A fail that stays open keeps producing one digest a day until it is fixed. That is intended.
- Regression tests: `test_mail_decide` in `_bin/guardian_core/domain_test.py`, and "a repair that
  worked is not mailed just because an unrelated fail is open" in
  `_bin/guardian_core/application_test.py`.

## Links

- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-16-decision-guardian-hook-probe-timeout-not-reproducible-debounce-added]]
- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
