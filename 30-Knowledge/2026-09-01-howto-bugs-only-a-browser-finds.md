---
id: 2026-09-01-howto-bugs-only-a-browser-finds
title: Bugs found only by opening the page
type: howto
area: [frontend, testing]
projects: []
tags: [testing, e2e, frontend, verification, degradation, formatting, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

Every bug here passed the build and a green suite of a few hundred tests, and fell over on opening the
page. They share a shape: **the bug lives on the boundary between layers that each test covers
separately.** A green build and a green suite say each layer does its own job; neither says the whole
works in a browser against the real backend. If the product is used from a browser, it has to be opened.

## A read-only component that required the sign-in provider

The home page of a bookings app deployed and came up blank with a "provider not found" error. Heavy
client providers, the sign-in session among them, were mounted per route deliberately, so public pages
would not load them. A new read-only "rooms left tonight" widget reused a hook that also read the
signed-in session, which needs the provider. The fix keeps the architecture: a read-only hook with the
same wiring minus the session part, not providers hoisted to the root. Nothing caught it at
build time because the widget was loaded with `ssr: false`, which skips the prerender where it would have
failed.

## Errors that look like the expected degraded state

An availability route answered "search unavailable" with the search service up and documents in it.
The field was named `guests_over_18`, not the `guests_over18` the code guessed, because the ORM's
snake_case conversion splits before digits. The expensive part was not the error but the `catch` that
swallowed its reason and returned the same message as a missing search service, which was exactly what
anyone expected to see.

**A bug disguised as the expected degraded state is the most expensive kind.** Degrading without taking
the page down is fine; doing it without leaving a trace is not.

## Zeros and dashes in a gracefully degrading interface

Three more bugs all showed as "no data" or "0": a sync job configured to start from a cursor in the
future (it waited forever and looked like a brand-new listing), a query against a column removed from the
schema (a silent 502 that looked like an empty history), and an amount read with another currency's minor
units ("0 refunded" instead of a small positive figure). The interface had been designed to say "not known yet"
gracefully, and the bugs hid inside that same degradation. Check the dashes and zeros in production
against the source of truth now and then; none of these could be seen by reading the code.

## Scales that come from another system

A constant assumed every partner reported prices in cents; one partner's currency used three minor-unit
digits. Nothing errored: that partner's nightly prices came out ten times too large, and the loyalty
points shown next to them ten times too generous, on a screen that worked normally.
Any scale that comes from someone else's system is read from it. A default only holds for what your own
system creates, and as a fallback when the other side does not answer.

## Two formatters for one amount

A canonical formatter truncated (`8.27961` to `8.27`); a new compact helper went through a float and
`toFixed(2)`, which rounds (`8.28`). Both appeared on the same page for the same amount. A value that
already has a canonical formatter is never re-derived through a float for display: a new presentation
either delegates to the canonical one or stays in the range where the two cannot disagree. Rounding
against truncation is invisible in review and obvious on screen.

## Extrapolated figures

A projected monthly booking growth computed from the first forty minutes of a new listing read 310%.
Hiding it below a minimum window was tried and turned out to be worse product. The figure stays, with its window
next to it ("projected from 40 minutes, expect it to move a lot"). `null` is still right when there is no data;
when there is little data, the answer is context, not silence.

## Copy found wrong by reading screens

Found by reading screens, not code: a page still listing components that no longer exist (it read
perfectly, which is what made it dangerous), and a panel saying "no reviews yet" when it simply had no
search service to ask. Not knowing a figure allows "I don't know"; it does not allow asserting the opposite.
See [[2026-08-30-howto-grep-prose-for-stale-designed-numbers]].

## A recorded false positive

A supposed clipping on mobile was a stale screenshot: the element measured well inside the viewport. The
difference between looking at a screenshot and measuring the DOM separates a finding from noise, in both
directions ([[2026-08-23-verify-frontend-findings-against-production]]).

## Links

- [[2026-09-02-convention-interface-copy-and-data-labels]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
