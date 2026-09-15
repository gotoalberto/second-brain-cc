---
id: 2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement
title: Negative results describe the instrument's reach
type: analysis
area: [verification]
projects: []
tags: [verification, negative-results, measurement, instruments, analysis]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

Over one long investigation, results of the form "X never happens" or "the scan found nothing" were
wrong often enough, and for different enough reasons, to become a rule: a negative result describes
what the instrument looked at, not what is true, until the instrument itself has been checked. It is
the forward-looking form of [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]].

## What treating negatives as provisional overturned

- Several "never observed" claims, from distinct causes: a low base rate a short sample never
  reached, a sample window that had moved, a scan over the wrong population, and a sample keyed to
  the wrong identifier for a service that had been set up twice.
- Two false zeros from one scan, for two unrelated reasons. A zero can hide more than one bug.
- A "no credits" error that was an API key never sent: a plumbing bug that looked like a resource
  limit.
- A large positive result that came from reading stale data: the same disease as a false negative.
- A structural refutation that had searched only the region it already knew about.

Every one of those instruments reported what it saw. The mistake was reading "reports nothing" as
"there is nothing".

## Rule to apply

1. **Ask what the instrument looked at**: the window, the population, the key or identifier, whether it
   received live input at all.
2. **A zero is not self-explanatory.** If two causes could produce it, check whether both apply.
3. **A result that looks too good gets the same suspicion**: check data freshness, identifiers and
  credentials.
4. **Calibrate before believing a zero**: run a control that must come back positive.
5. **Coverage claims state their boundary.** "Not seen after this stated effort" is a result; "not
   seen" with no stated effort is not.

This holds for any pipeline that reports "found nothing": a security scan, a log grep, a monitor, a
test suite.

## Links

- [[2026-09-05-convention-verify-negative-claims-about-third-parties-before-writing]]
- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
