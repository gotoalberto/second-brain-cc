---
id: 2026-10-16-convention-absence-in-partial-lists-proves-nothing
title: Absence in a lazily loaded, paginated, truncated or time windowed list proves nothing
type: convention
area: [automation]
projects: []
tags: [convention, routines, browser, pagination, lazy-loading, false-negative, accents, dedupe, scheduled-tasks]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-16
supersedes: []
---

## The rule

A name, post, message or record that is not in a lazily loaded, paginated, truncated or time windowed
list is not evidence that it does not exist or did not happen.

## Why

Web pages render the first rows of a long list and load the rest on scroll; APIs return a page and a
cursor; a page read with a length cap cuts the end off; a search is bounded by a date facet. A
routine that looks for an item in such a list and does not find it has learned nothing, yet the
natural next step is to report the negative: "declined", "not posted", "no reply".

The incident that set the rule: a routine that tracked invitations sent on a social network looked
for each invited person in the "sent" list and the "recently added" list, did not find several of
them, and reported them as probably declined. Both lists rendered only their first rows (the sent
list showed about half of the people). Every one of them was still pending, and the same check on each person's own
page found acceptances the routine had never recorded. An audit of the other routines then
found the same shape in many more places: feeds read until the first familiar item, searches read
from one page, replies counted instead of compared.

## How to apply it

- **Check the item itself.** The person's profile, the post's own page, the thread: that is the
  source of truth. For an invitation, the profile says whether the person is connected, pending or
  open to a new request.
- **Otherwise read until the window is covered.** Scroll or follow the cursor until the oldest item
  is past the window you care about, and log the oldest date seen ("window covered" or "window NOT
  covered"). If that cannot be reached, fail closed: report "unknown", never a guess.
- **Find what you just published by its content.** After posting, take the new post's URL by
  matching its first line and open it before logging it, never by taking the first item of a list.
- **Match by stable ids, not display names.** A profile URL, an activity or message id, a
  conversation URL. Where a name is unavoidable, fold accents (NFKD) and match whole words.
- **Never report a negative state without the direct check.**
- **Compare by content, not by count.** Counting replies to detect a new one breaks on lazily loaded
  threads and on hand written summaries. Compare texts, and when a fresh copy of a thread is shorter
  than the stored one, warn and keep the stored copy.
- **Short texts do not match.** A one word reply ("ok", "yes") must not match a routine's own long
  texts; a partial match needs both sides above a minimum length (40 characters works).
- **A ranked feed is not chronological.** Stop reading a ranked feed on the age of the posts, never on
  the first post already seen.
- **Logs written newest at the bottom are read to the last line.** A read capped at the first N lines
  of such a log misses exactly the recent entries.

## Alternatives discarded

- Trusting the list views: lazy and partial by design.
- Counting replies or items: broken by partial loading and by summaries.

## Links

- [[2026-09-23-howto-linkedin-content-search-calibration]]
- [[2026-09-15-convention-scheduled-job-exit-code-should-reflect-crash-not-findings]]
