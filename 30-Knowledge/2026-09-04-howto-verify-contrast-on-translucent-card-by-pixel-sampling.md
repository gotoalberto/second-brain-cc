---
id: 2026-09-04-howto-verify-contrast-on-translucent-card-by-pixel-sampling
title: Contrast on translucent, blurred cards over artwork
type: howto
area: [frontend, testing]
projects: []
tags: [accessibility, contrast, wcag, backdrop-filter, screenshot-diffing, verification, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-04
supersedes: []
---

## Compositing arithmetic over a blurred background

Cards with a translucent background (`rgba(16, 40, 70, 0.7)`) and `backdrop-filter: blur(8px)` sat over an
illustration with light and dark areas. Flattening the declared background over an assumed colour gave
about 5:1 for the title text, a pass. Measured where the artwork is lightest under a card, it was barely
above 2:1, a hard fail. The blur samples the actual pixels behind the card, bright regions included; a
single assumed colour does not.

## The method

1. Screenshot the card with its text.
2. Screenshot the same card with `color: transparent` on the text, so only the background renders.
3. Diff the two to get a mask of exactly which pixels are glyph ink.
4. Sample the second screenshot's background only at the mask's coordinates, and compute contrast where
   the letters actually sit; an average over the card hides the worst spots.

**Capture each element in its own viewport clip**, not one very tall stitched capture: coordinates drift
across a stitched capture, and an early attempt reported backgrounds lighter than physically possible.

## Rule

Any contrast check on a translucent layer over non-flat art or photography is verified on the composited
render, not computed from the declared CSS. The gap is large enough to flip a verdict. Same discipline as
measuring what is painted elsewhere ([[2026-08-23-verify-frontend-findings-against-production]]).

## Links

- [[2026-08-23-failure-inherited-theme-tokens-in-opposite-background-subtree]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
