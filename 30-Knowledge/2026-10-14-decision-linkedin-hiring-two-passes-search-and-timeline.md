---
id: 2026-10-14-decision-linkedin-hiring-two-passes-search-and-timeline
title: The LinkedIn hiring post review runs two passes, a formula search and the full timeline
type: decision
area: [research, career]
projects: []
tags: [job-search, linkedin, hiring-posts, timeline, search, browser]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-14
supersedes: []
---

## What was decided

Every run of the review of LinkedIn posts by people who are hiring (step 2b of the `job-search` skill,
reference `linkedin-hiring-posts.md`) makes two passes, both mandatory.

1. **Search pass.** Search the phrases people write when they open a position, each paired with
   exactly one of the user's domain terms, on top of the measured title queries, which stay.
   - English formulas: "we're hiring", "I'm hiring", "my team is hiring", `#hiring`, "open role",
     "know anyone", "send me your CV", "DM me", "join my team", "first hire".
   - Formulas in the user's second language, written the way people there write them (the hiring
     verb in that language, the job title kept in English, as measured in
     [[2026-09-23-howto-linkedin-content-search-calibration]]).
   - Results pages are scrolled until the date window ends, not for a fixed number of scrolls.
2. **Timeline pass.** Read the user's home feed from the top back to the previous run. Stop when the
   posts are older than the gap since the last report, or when three scrolls in a row bring nothing
   new. The report states how many posts were read and where the reading stopped.

The old "keep the volume low" rule became "once a day, read only".

## Why

Hiring posts often carry no job title at all ("my team is growing, ping me"), and some only show in
the user's network feed, so title queries alone cannot find them. A bare formula with no domain term
was measured to return spam, so every formula is paired with one term.

## Consequences

- **More page loads per run**, around seventy on top of the measured set. Watch for throttling.
- **The new pairs are unmeasured.** The first runs record which formula and term pairs return real
  hiring posts, and the reference file keeps only those.
- **The feed is ranked, not chronological.** A post already quoted in an earlier report is not a stop
  signal; only the age of the posts is
  ([[2026-10-16-convention-absence-in-partial-lists-proves-nothing]]).
- The feed collection snippet keys on stable attributes and is rechecked when it captures zero posts.

## Links

- [[2026-09-23-howto-linkedin-content-search-calibration]]
- [[2026-09-22-decision-job-search-accepts-onsite-and-hybrid-in-a-configured-area]]
