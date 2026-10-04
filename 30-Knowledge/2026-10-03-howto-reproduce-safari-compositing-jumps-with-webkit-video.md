---
id: 2026-10-03-howto-reproduce-safari-compositing-jumps-with-webkit-video
title: Reproducing Safari compositing pixel jumps with Playwright WebKit and video frames
type: howto
area: [frontend, testing]
projects: []
tags: [safari, webkit, playwright, compositing, will-change, css, ios, video, ffmpeg, animation]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-03
supersedes: []
---

## The symptom

On iPhone, a sliding underline under a row of tabs moved up by one device pixel exactly when its
slide ended. `getBoundingClientRect()` never changed, so it was a paint and compositing artifact,
not layout.

## The cause

Safari promotes an element to its own compositing layer only while a `transform` transition runs.
When the transition ends, the element is repainted into the page layer and snapped to a different
device pixel (one device pixel at a 3x scale factor is easy to see on a thin coloured line).

## The fix

`will-change: transform` on the indicator, so it stays on its own layer at rest and in motion. In the
measured case, the line covered rows 120 to 125 while moving and 119 to 124 at rest before the fix,
and 120 to 125 always after it.

- Snapping layout to integer pixels was discarded: fractional offsets come from fonts and layout
  above the element and cannot be controlled everywhere.
- An element that animates `clip-path` rather than `transform` does not switch layers and does not
  need this.

## Reproduction technique

1. **Chrome does not reproduce Safari compositing jumps.** Its screencast showed constant rows. Use
   real WebKit.
2. **Playwright WebKit**, headless. The WebKit build must match the `playwright-core` version that
   expects it; when a cached browser is already on the machine, install the `playwright-core` version
   that matches that cache rather than downloading another browser.
3. **A phone context**: viewport around 400x870, `isMobile: true`, `hasTouch: true`,
   `deviceScaleFactor: 3`, and `recordVideo` at the device pixel size (viewport times 3).
4. **Extract frames from the video** with ffmpeg, scan each frame for the pixel rows that hold the
   indicator's colour, and print whenever the set of rows changes.
5. **Page screenshots taken during the animation do not show the jump**: a screenshot forces a fresh
   paint. Only the recorded video, which is compositor output, shows it.
6. **A hidden agent tab cannot time animations at all**: with `document.visibilityState` "hidden",
   CSS transitions and `requestAnimationFrame` do not run
   ([[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).
7. **Drive the page from its local fake data mode**, so the tab row exists without any backend
   ([[2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed]]).

## Links

- [[2026-10-03-convention-motion-in-web-interfaces]]
- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
