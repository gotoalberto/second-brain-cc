---
id: 2026-08-30-howto-mobile-content-unreachable-with-no-signal
title: "Mobile breakage pattern: content unreachable with no signal that it exists"
type: howto
area: [frontend]
projects: []
tags: [css, responsive, mobile, accessibility, canvas, tables, details, dataviz]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The pattern

A container clips or scrolls its content **with no visible sign that there is more**. On desktop nothing
looks wrong because the viewport happens to be wide enough; on a phone the desktop layout degrades into
something that looks intentional. Three instances found in one pass at 375 px:

1. **A nav as a horizontal scroll rail with `scrollbar-width: none`.** Most of the links were off-screen
   and the hidden scrollbar removed the one hint that there was more. Fix: a `<details>` disclosure, no
   JavaScript, an honest "there is more, tap to see it".
2. **A table with `min-width: 600px` inside a 340 px column**, scrolling sideways with no visible
   scrollbar, so the column the copy called the headline simply did not exist for a phone reader. Fix:
   stack the rows on narrow screens, with `data-label` attributes shown by `content: attr(data-label)` in
   a `::before`. One markup, two renderings.
3. **Canvas diagrams placing labels at a fixed radius or offset.** A canvas has no overflow to notice:
   text past its edge is clipped mid-word, silently.

## Diagrams on narrow screens

Shrinking the font until the diagram fits is the wrong fix. A well composed list says the same thing, and
unlike text drawn on a canvas it can be selected, translated and zoomed. Keep **one data source** (the
array the diagram already draws from) and render it two ways, chosen by a media query. Do not copy the
data into a second hardcoded list.

The switch point is not a screen width picked by eye but whatever the drawing needs to keep saying what
it says (for a line chart, enough stroke length for its swings to stay visible). Written that way the
threshold can be argued about; written as `w < 420` it cannot.

A table whose columns repeat the same value in every row is not a table: one column and a sentence say
it better.

## Traps on responsive canvas and disclosure work

- **An inline `style` wins over a media query.** Canvases with `style="display: block"` set from
  JavaScript ignored the media query meant to hide them, so on a phone both the broken diagram and its
  list rendered. It looked intentional; only comparing the computed `display` of both showed it. Toggle a
  class instead of setting `display` inline.
- **A closed `<details>` does not stop an absolutely positioned child from being laid out.** Links inside
  a closed disclosure kept their geometry off to the right, and their tab focus. Use `display: none` while
  closed and the real display on `[open]`, not visibility, opacity or positioning tricks. Found by
  measuring overflow, since invisible elements do not show in a screenshot.
- **Measure canvas text instead of reserving room for it.** Call `ctx.measureText()` before drawing and
  size the layout from that, never from a hand-written width or a percentage of the container. A width
  step like `w < 420 ? 60 : 110` only moves the error to another range of screens. Measure and paint the
  same constant string, and when a caption does not fit, shrink it to a legible minimum rather than let
  it clip.

## Links

- [[2026-08-23-verify-frontend-findings-against-production]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-09-30-howto-web-css-and-build-traps]]
