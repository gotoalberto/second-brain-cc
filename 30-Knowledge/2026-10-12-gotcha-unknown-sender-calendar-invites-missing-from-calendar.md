---
id: 2026-10-12-gotcha-unknown-sender-calendar-invites-missing-from-calendar
title: Calendar invitations from unknown senders are missing from Google Calendar and must be found in Gmail
type: failure
area: [calendar, email]
projects: []
tags: [calendar, google-calendar, gmail, invitations, scheduling-links, gotcha]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-12
supersedes: []
---

## Symptom

The user mentions a meeting ("my call on Thursday") and it is not on any of their calendars, although
the invitation was sent and they received it.

## Cause

Google Calendar does not add invitations from senders it does not know, depending on the "Add
invitations to my calendar" setting. Gmail holds them instead, as a mail whose subject starts with
the localized form of "Invitation from an unknown sender". Bookings made through a scheduling link by
someone new (a first call with a new contact, a booking tool's confirmation) are the typical case.

## What to do

1. Search Gmail for that subject, plus the organiser's name or domain. The mail carries the time, the
   video link and an `invite.ics`.
2. Check the slot for conflicts across the user's calendars before anything else
   ([[2026-09-24-convention-check-calendar-conflicts-before-booking]]; `google.py slots` or
   `google.py meeting`).
3. Either the user clicks the link in the mail that marks the sender as known, and the real invitation
   then shows with its RSVP, or the agent writes a plain event of the user's own with the time and the
   video link in its location and description, no guests (`google.py api --method POST` on the events
   endpoint). The plain event has no RSVP link back to the organiser; say so.
4. For the long run, the user can change the "Add invitations to my calendar" setting. That is their
   call: it also lets unsolicited invitations in.

## Discarded

`events/import` with the `iCalUID` from the `.ics` (plus organiser, attendees and conference data)
creates an event that can be read by its id with status confirmed, yet it never appears in
`events.list`, not even with `showHiddenInvitations=true`. It is invisible in the calendar. If one was
created, delete it by id (`--method DELETE`, which answers 204) and write a plain event instead.

## Links

- [[2026-09-24-convention-check-calendar-conflicts-before-booking]]
