---
id: 2026-09-24-convention-check-calendar-conflicts-before-booking
title: Check calendar conflicts before adding or moving an event
type: convention
area: [apis, calendar]
projects: []
tags: [google, calendar, conflicts, scheduling, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-24
supersedes: []
---

## Rule

Every time an event is added to a calendar or moved, first look at what is already in that
slot. If something is there, do not book on top of it: tell the user what clashes and propose
free alternatives. Book the overlap only if the user says so.

## Context

An interview was moved onto a slot that already held a recurring team meeting, and nobody
noticed until the day before. The request that followed was to always look at the slot first
and offer alternatives on a conflict.

## How to apply

- Check the user's own calendar for the new slot, ignoring free, cancelled and declined events
  and the event being moved. Where the calendar API lets you, also check the free/busy of the
  other attendees; an address you cannot read is "not checked", never "free".
- A change to the title or description alone needs no check; a new time or a new attendee does.
- Offer a few free alternatives inside working hours, and drop the ones that fall at night for
  an attendee in another time zone.
- On a conflict, stop and ask. Do not pick an alternative on the user's behalf.
- Write events through the script that does the check, never through a raw token and curl,
  which would skip it.

## Enforcement

`_bin/google.py api` runs the calendar guard (`_bin/google_core/calendar_guard.py`) on every
event it creates or moves. When the slot overlaps an event or a busy attendee it writes
nothing, prints the conflicts and free alternatives, and exits with status 3. Show them to the
user and rerun with the chosen slot, or with `--force` once the user accepts the overlap.
`google.py slots --account NAME --start ISO [--minutes N] [--with ADDRESS ...]` runs the same check
without writing, for proposing times before anything is booked.

## Links

- [[2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms]]
