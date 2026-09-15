---
id: 2026-09-02-convention-interface-copy-and-data-labels
title: Interface copy and data labels
type: convention
area: [design, writing]
projects: []
tags: [ui, copy, labels, loading, rounding, badges, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## No explanatory prose above a control

On a screen where the user acts (buy, send, confirm, sign), no explanatory paragraph sits between the
title and the input. Whoever opens that screen has already chosen the action; what they came to see is
what they put in and what they get back, and every line in between splits that one question in two.

- The test for a sentence is not "is it true" but "is it sitting above a control".
- The content does not disappear: what is being confirmed is said under the button, at the moment of
  acting; background and risk figures live on their own page or tab with their context.
- A unit label inside the field is not prose above it.
- A caveat that explains a number which will genuinely swing (a rate annualized from a short window, say)
  may stay, as a deliberate exception.

## A quantity label never claims there is none

- A formatter never prints "0" for a value that is not zero. When the display budget (decimals, column
  width) would erase every significant digit, the budget yields. Cutting at some other wrong digit is not
  a fix either.
- Two different states never share one sentinel: "unlimited" and "exhausted", "unknown" and "zero",
  "pending" and "failed" each need their own value. A collapsed value makes an affirmative wrong claim,
  which is worse than admitting not knowing.

## An "unknown" mark cannot also mean loading

A dash or blank used for "known to be absent" must not also render while data is still loading or when
the source failed. Loading is a different axis (time) and needs its own signal, often a slot that is empty
precisely while loading anyway. Wherever a sentinel mark appears in a data-driven label, check that the
loading state is read.

## Degrade per datum, not per sentence

When a sentence mixes figures from two independent sources, guard each figure by its own source. A
combined guard (`sourceA && sourceB`) hides the whole sentence when one source fails, including what the
other source knows perfectly well. This comes back every time markup is regrouped, so check for it in any
review that touches phrasing in a multi-source component.

## Badge the frontier, not every item

In a roadmap or changelog with many completed entries, badge only the frontier: the item in progress and
the latest completed one, derived from status and order rather than hardcoded. A wall of identical
"done" badges carries no information.

## Links

- [[2026-09-15-convention-descriptive-language-no-internal-labels]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
