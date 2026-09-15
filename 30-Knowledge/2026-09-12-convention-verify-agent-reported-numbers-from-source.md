---
id: 2026-09-12-convention-verify-agent-reported-numbers-from-source
title: Re-derive numbers that agents and documents report
type: convention
area: [ai-agents, verification]
projects: []
tags: [verification, agents, documentation, drift, tests, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

When a report or a document claims a total and says all of it checks out, re-derive the total from
the source before believing it, and look for what the round number absorbed. The exceptions are
usually where the information is.

Shapes this takes:

- **A completeness claim that is false.** A README said tens of thousands of migrated records were
  "all imported". About twenty were not, all of the same kind, and working out why produced the
  rule the implementation had been missing.
- **A claim describing a state the code has left.** Documents said "this feature is not implemented"
  next to a directory holding the implementation.
- **A label that hides a category change.** A count of items "validated" climbed across drafts,
  while the operation behind the label had quietly changed from "appears in the logs" to
  "passes an end-to-end test". Only about half passed the stricter bar.
- **A green gate with zero tests.** A test command exited 0 on a module with no test functions; the
  real check ran as a separate binary.

## Why it happens

A second pass adds a capability and does not revisit the prose the first pass wrote. With several
agents in parallel this is the default outcome: each brief points at what the agent adds, and
nothing points at what the addition invalidates.

## How to apply

- Verify a subagent's headline numbers yourself before acting on them: grep for the construct, run
  the tests, read the evidence file.
- Check scope as well as content: which files the branch touched against the files it was given.
- Ask what operation produced a word like "validated" or "confirmed".
- Check that each green gate reports a non-zero test count, not only a zero exit code.
- Put the negative-result standard in the brief: "report what did not reproduce and why".
- Route documentation drift to whoever owns the file, in the session it is found.

## Links

- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
- [[2026-09-11-convention-agent-write-findings-to-disk-incrementally]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
