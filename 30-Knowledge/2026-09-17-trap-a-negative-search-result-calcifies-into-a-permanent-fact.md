---
id: 2026-09-17-trap-a-negative-search-result-calcifies-into-a-permanent-fact
title: A negative search result written without its date or method becomes a permanent fact
type: analysis
area: [verification]
projects: []
tags: [verification, negative-results, staleness, methodology, analysis]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

## What happened

A repository built as context for agents stated in four places, including its `README.md` and
`AGENTS.md` (both read first by every agent), that nothing in a certain ecosystem is listed in a public
registry. Checking one component against that registry found it listed. The
negative had been written as a property of the ecosystem, not as the result of a search run on a
given day.

## Why it happens

A search result ("X is not verified", "nothing was found") is true on the day it ran, for the tool
and the query used that day. It is not a lasting property of the thing searched. Written down as a
bare negative, with no date, tool or query, it gives nobody downstream a signal that the cheap check
is worth running again, and it hardens into a fact everyone builds on.

The worst place for one is onboarding material. Every future agent inherits it before doing any work
of its own, so it forecloses the check instead of inviting it.

## What to do instead

- Never write a negative search result as a bare fact. Write it as a dated claim with its method:
  "as of 2026-01-10, none of these 9 items is verified on service Y". That tells the next reader the
  check is cheap and worth repeating.
- Treat a negative claim in onboarding material (README, AGENTS.md, a methodology page) with extra
  suspicion, precisely because it is presented as settled.
- When one counterexample breaks a standing negative, re-run the check over the whole population
  before updating the write up. Here that separated "one component is verified" from "verification
  has become common". The conclusion barely changed, but it became a checked conclusion instead of
  an inherited one, and it is dated.
- Ship the correction together with the re-run, not instead of it.

## Links

- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
- [[2026-09-05-convention-verify-negative-claims-about-third-parties-before-writing]]
- [[2026-09-09-convention-memory-must-not-assert-mutable-state]]
- [[2026-09-17-convention-re-edit-the-agent-entry-point-as-a-kb-grows]]
