---
id: 2026-10-03-reference-x-cards-do-not-animate
title: X link cards and sharing to X from a phone
type: reference
area: [frontend]
projects: []
tags: [x, twitter, cards, og-image, gif, share, deep-link, ios, android]
status: active
confidence: medium
source: external
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-03
supersedes: []
---

# X link cards and sharing to X from a phone

Checked in X's archived "Cards markup" reference. `twitter:image` accepts JPG, PNG, WEBP and GIF, but
X uses only the first frame of an animated GIF, and SVG is not supported. A `summary_large_image`
card is therefore always static.

The Player Card is the only card that plays anything, and it does not fit a share card:

- X must approve it;
- it is reserved for linear video or audio;
- in the mobile apps it shows only in the post detail view, as a tap-to-play preview.

Moving content in a post needs the media attached to the post itself. A web intent cannot attach
files, so that is only possible from a phone, through the system share sheet with a file.

## What to do with an "animate the share card" request

Say the card cannot move, and offer only what can: a short video shared from the phone's share sheet,
an animated landing page that the card links to, or a richer static image. The user may well decline
all of them; a static card is the normal outcome.

## Sharing to X from a phone

A share button that opens `x.com/intent/post` in a new tab stays inside the phone browser, and inside
in-app browsers, instead of handing off to the X app. Universal links do cover that path
for the app, but a new-tab open from those browsers does not hand off. A pattern that does:

- **iOS**: navigate to the app scheme (`twitter://post?message=<text and url>`); after about 1.5 s, if
  the page is still visible, fall back to the web intent in the same tab. `visibilitychange`,
  `pagehide` or `blur` cancel the fallback.
- **Android**: an `intent://` URL for the app's package with `S.browser_fallback_url` set to the web
  intent.
- **Desktop**: the web intent as before.

Confidence is medium: if Safari shows an "Open in X?" prompt and the user waits past the timer, the tab
jumps to the web post. Confirm on a real device and tune the timer.

## Links

- [[2026-10-03-convention-motion-in-web-interfaces]]
