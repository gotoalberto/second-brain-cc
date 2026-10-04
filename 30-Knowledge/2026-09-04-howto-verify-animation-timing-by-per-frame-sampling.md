---
id: 2026-09-04-howto-verify-animation-timing-by-per-frame-sampling
title: Verifying animation timing by per-frame sampling
type: howto
area: [frontend, testing]
projects: []
tags: [animation, motion, framer-motion, playwright, performance, verification, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-04
supersedes: []
---

## Late content and slow entrance animations

The user said a disclosure of five cards "takes a while to load" when opened. Nothing in that path fetched
or mounted late, so the suspect was the entrance animation.

Sampling the DOM every frame with Playwright and a `requestAnimationFrame` loop showed the text of all five
cards present within the first frame after the click. The slowness was entirely animation: opacity ran for
the full duration of the height transition, behind a long per-card stagger, so the last card started fading
in late and finished well after the first.

Retuned to a short fade with a tight stagger, all cards were fully opaque in about a quarter of a second,
checked with no per-frame opacity gap longer than a couple of frames.

The timings moved from an inline constant into an exported pure function, so a test pins the tail duration
(last card start plus its duration). Otherwise stagger and duration drift back to slow with no test catching
it ([[2026-10-03-convention-motion-in-web-interfaces]]).

**Before optimizing a perceived-slow interaction, sample the DOM per frame**, not only at the end. The fix
for "content is late" and for "content is animating in slowly" are completely different.

## Per-frame computed style and painted pixels

The same probe showed a one-frame `opacity: 0` on the last card right after it had reached 1, which looked
like a flicker. Reading `getComputedStyle` every frame forces a synchronous style recalculation, which can
observe an intermediate state that the compositor never paints.

Checked against painted output instead: repeated screenshots, counting the pixels of the accent colour over
time. The count rose and held flat, with no dip. There was no flash.

When a per-frame computed-style probe suggests a visual glitch, confirm it against painted pixels before
fixing it. For compositing glitches that screenshots cannot see either, record video
([[2026-10-03-howto-reproduce-safari-compositing-jumps-with-webkit-video]]).

## Links

- [[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]
- [[2026-09-04-howto-verify-contrast-on-translucent-card-by-pixel-sampling]]
