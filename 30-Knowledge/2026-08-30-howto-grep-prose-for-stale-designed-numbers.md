---
id: 2026-08-30-howto-grep-prose-for-stale-designed-numbers
title: When a designed number or mechanism changes, grep every prose occurrence, data structures included
type: howto
area: [frontend, writing]
projects: []
tags: [copy, verification, refactor, content, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The rule

After any decision that changes a number the product states about itself (a split, a percentage, a
deadline, an address, a version), search for **every representation of the old value** across the whole
frontend, beyond the pages you remember mentioning it. Include:

- prose inside `.md` and `.mdx` content;
- string values inside data and config arrays that feed copy. They do not look like content when you
  scan the JSX, so earlier sweeps skip them; in the case behind this note, the old split survived two
  sweeps inside such an array;
- anything that presents the number as a verified or historical fact ("measured in production"). That is
  actively false, not merely outdated, so it is fixed first.

An invented example: a climbing gym split its bouldering wall time 60/40 between members and day-pass
visitors, and the new rule is 50/50. Before calling the copy change done:

```sh
grep -rnE "60%|40%|60/40|sixty percent|three in five" app/ src/ content/
```

## Stale mechanisms

An invented example: a redesign of a gym's help pages carried forward a flowchart saying that a late
class cancellation "is reviewed by the duty instructor, who may waive the strike". The duty instructor
role had gone when check-in became self-service at the door; nothing in the current system routed a
cancellation to any person at all. The reskin did not invent the error, it moved old copy to a more
prominent, more polished place.

A wrong number looks wrong to someone who checks it against the spec. A wrong mechanism (a role, a step,
a destination) reads as a coherent explanation, so nobody checks it. Whenever a system removes a role, a
step or a destination, grep the prose for the **name of the removed thing and for what it used to do**,
not only for its numbers. Do it every time a rewrite starts "from the existing copy": old copy is trusted
because it exists, not because anyone re-verified it.

When, after the fix, the two branches of a conditional diagram say the same thing, that can be the
correct outcome and a stronger argument; the diagram has not lost its point.

## Links

- [[2026-09-02-convention-interface-copy-and-data-labels]]
- [[2026-09-17-convention-a-single-sample-constant-acquires-false-precision]]
