---
id: 2026-08-28-convention-links-must-resolve-and-be-verified-open
title: Links handed to the user must resolve and be verified
type: convention
area: [communication, verification]
projects: []
tags: [links, urls, verification, apis, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Every link given to the user resolves, and anything presented as live (a listing, a page, a record) is
verified to still exist at the moment it is written down.

## Never construct a URL

A dead link once reached the user because it had been assembled from an aggregator's slug; that host and
path never existed, and the real URL was in the API response all along. Use the URL field the API or page
actually returned (`url`, `hostedUrl`, `absolute_url` and so on). Never assemble one from an id or a slug.

## An HTTP 200 is not proof

Many sites are single-page apps: they answer 200 with a shell and resolve "not found" in the browser. A
200 on several guessed paths of the same site is the same shell answering everything, not corroboration.
Check the authoritative source instead, usually the service's own API, and read its full fields (a record's
complete location list, not the headline value).

## When it cannot be verified

Say so next to the link ("not verified"). Never present something as live on a third party's word alone:
aggregators and caches lag by months.

## Links

- [[2026-08-28-convention-clickable-links-and-send-files]]
- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
