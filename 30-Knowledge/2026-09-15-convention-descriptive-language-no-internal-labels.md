---
id: 2026-09-15-convention-descriptive-language-no-internal-labels
title: Descriptive language instead of internal labels
type: convention
area: [writing]
projects: []
tags: [writing, language, labels, jargon, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

In anything written for the user, say what a thing is or does. Never refer to it by a label that
only makes sense to someone who read the source document.

## What that excludes

- **Phase and wave labels** copied from design docs or pull requests: "wave B", "phase 0 to 1",
  "step C2".
- **Codes invented to organize a document:** item ids, question ids, section codes, unowned ids.
  Name the item instead ("the move to the new backup schedule", "the decision on the meeting room
  booking rules").
- **Unexplained jargon and tool vernacular:** "DLQ", "readiness", "backfill", "flip", "PoC". Either
  use plain words or add a short gloss the first time ("the bot that closes inactive pull
  requests").

## What to write instead

A short description that a reader who has not seen the code or the meeting understands: what
changes, where, for whom and why it matters. Pull request numbers, file paths and code identifiers
can stay as references next to a description, never in place of one.

## Scope

Status pages, proposal tables, summaries, reports and chat replies. Tickets follow the same spirit.

## Links

- [[2026-09-10-convention-write-like-a-person]]
