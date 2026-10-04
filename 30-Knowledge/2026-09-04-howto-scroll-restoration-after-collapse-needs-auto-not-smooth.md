---
id: 2026-09-04-howto-scroll-restoration-after-collapse-needs-auto-not-smooth
title: Scroll restoration and focus after collapsing a tall region
type: howto
area: [frontend]
projects: []
tags: [scroll, accessibility, focus-management, react, motion, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-04
supersedes: []
---

## Scroll correction after a collapse

Collapsing an expanded list removed a couple of thousand pixels of page height in the same React commit.
`window.scrollTo({ top, behavior: "smooth" })` animated toward a `top` measured before the collapse, while
the layout shifted under the animation, and it landed far from where it should. `behavior: "auto"` (an
instant jump), run after the collapse has committed, avoids it: there is no animation in flight for the
layout shift to invalidate.

## Focus after a collapse

If the control the user activated (a "show more" toggle) sits inside the region that unmounts,
`document.activeElement` silently becomes `<body>`: no error, just lost keyboard focus. Move focus
explicitly to a control that survives the collapse (the disclosure's own toggle, now reading "show less").

## Rule

Any collapse or removal that changes layout height in the same tick as the user's action:

1. corrects scroll with `"auto"`, after the DOM change has committed, not with `"smooth"` computed before;
2. re-targets focus to something that still exists afterwards.

## Links

- [[2026-10-03-convention-motion-in-web-interfaces]]
