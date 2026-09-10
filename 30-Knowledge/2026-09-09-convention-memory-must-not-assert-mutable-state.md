---
id: 2026-09-09-convention-memory-must-not-assert-mutable-state
title: Memory must not assert mutable state
type: convention
area: [memory-system]
projects: []
tags: [memory, staleness, verification, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-09
supersedes: []
---

## The rule

A fact that can change on its own (an access scope, a quota, a feature flag, a plan tier,
whether a service is enabled, an effective date not yet known) is not written into memory as
a flat present-tense claim. Two things go in instead:

1. **The command that answers it right now.** For an OAuth grant, that is asking the
   provider what the live token carries, not reading the scopes a script requests.
2. **If the state matters enough to record anyway, a dated observation** framed as a
   snapshot that decays: "as of 2026-09-09, granted: X", never "X is read-only".

## Why

An agent wrote a cross-session memory saying an account was read-only and that sending mail
needed a new consent. Within the same session the user granted the consent and the sentence
became false. Because that memory is loaded into every future session, it would have taught
the corrected error again.

A stale sentence is read with the same confidence as a true one and stops the reader from
checking, where no sentence at all would have forced a check. The failure is not that facts
go stale (they do); it is that the note removed the incentive to verify.

## How to apply

When writing a note or memory, ask of each present-tense claim: can this change without
anyone editing this note? If yes, replace it with the check, or date it.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
