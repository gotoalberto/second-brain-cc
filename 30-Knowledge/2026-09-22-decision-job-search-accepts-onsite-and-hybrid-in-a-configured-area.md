---
id: 2026-09-22-decision-job-search-accepts-onsite-and-hybrid-in-a-configured-area
title: Job search accepts on-site and hybrid roles in an area the user configures
type: decision
area: [career]
projects: []
tags: [job-search, location, remote, on-site, hybrid, preferences, decision]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## The decision

The `job-search` skill is no longer remote only. A role qualifies when it is:

- fully remote and open to the user's location, anywhere; **or**
- on-site or hybrid **inside the area the user names** in `80-Private/job-search/preferences.md`,
  line "On-site or hybrid acceptable in".

On-site or hybrid anywhere else is still a hard fail. With no area named, the search stays remote only.

It came from a user who said every on-site role in their own city interested them. Hybrid in that
city was included by inference, as it asks for less office time than on-site; a user who disagrees
narrows the preference line.

## What changes in the run

- **Two searches every run** when an area is set: remote, and that area with no work mode filter. A
  "remote" filter hides exactly the local roles that were asked for.
- **Ranking**: remote open to the user's location and on-site or hybrid inside the area share the top
  tier. Local rows carry their mode (on-site, hybrid, days in the office).
- **Email subject** counts takeable roles, not remote ones.

A side effect worth keeping: the first local sweep also surfaced a remote role that the remote queries
had missed, because the posting listed the user's country only among secondary locations.

## Links

[[2026-09-23-howto-linkedin-content-search-calibration]]
