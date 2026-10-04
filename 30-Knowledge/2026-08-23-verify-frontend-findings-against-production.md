---
id: 2026-08-23-verify-frontend-findings-against-production
title: Verifying visual findings against the rendered page
type: convention
area: [frontend, testing]
projects: []
tags: [verification, nextjs, css, cache, cssom, screenshots, viewport, contrast, measurement, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The rule

A visual finding measured on a dev server is not a finding until it reproduces on the production build
(locally or deployed). And a measurement is not a look: when something can be seen, it has to be seen.
Each case below fooled an audit in one direction or the other.

## Stale image optimizer cache

Two agents measured a cover image losing a quarter of its width to `object-fit: cover`, as if the file
were 16:9 in a 4:3 box. The file on disk was 4:3. The framework's image endpoint was serving the cached
optimized version of the previous cover:

```
naturalWidth x naturalHeight, local:      800 x 450   (the old file)
naturalWidth x naturalHeight, production: 800 x 600   (the new one)
```

The same happens with `next start` after a full `npm run build`: `.next/cache/images` survives the
build, and its key does not include the source file's hash. **When the file on disk and the rendered
page disagree, the image cache is the first suspect.** Clear it (`rm -rf .next/cache/images`) and
restart, or measure against the deployed site.

## Properties dropped by a CSS pipeline

A nav with `backdrop-filter: blur(12px)` computed to `none`. `CSS.supports()` said the browser supported
it; the framework's CSS pipeline in that version had removed the declaration. Wrapping it in
`@supports` made it worse: the rule survived with the declarations inside it gone, leaving a translucent
background with no blur, so the page read through the nav. Never assume a property applies because it
is in the source: check it with `getComputedStyle`, and walk the CSSOM to tell "dropped" from
"overridden":

```js
for (const ss of document.styleSheets)
  for (const r of ss.cssRules)
    if (r.cssText?.includes("backdrop")) console.log(r.cssText);
```

## Findings reported by a subagent

A critique agent opened with a severe finding about placeholder text in a named image. The image was
fine; the agent was describing the previous version. The real problem existed in two other files at a
lower severity. The same report was right about a grid misalignment, confirmed by measuring. Open the
artefact before touching code ([[2026-09-17-convention-open-a-subagents-artefact-not-just-its-report]]).

## Colour parsing in contrast scripts

Browsers return computed colours both as `rgb(0-255 ...)` and as `color(srgb 0-1 ... / a)`. Reading the
second as 0 to 255 turns near-white into near-black and produces a list of false failures near 1:1.
Handle both forms.

## When the capture tool is broken

A browser tool kept returning solid black screenshots while its DOM and JavaScript calls answered
correctly, so a design pass was verified by measurement instead: contrast, computed fonts, geometry,
overflow. Every number was clean. A working browser then showed, in one look:

1. the right half of every section was empty at desktop width ("no horizontal overflow" was true and
   said nothing about composition);
2. a canvas diagram drew a detail line above its label, an inverted reading order no DOM query can see;
3. animated canvases finished drawing after they had scrolled out of view.

The next screenshot, after the fix, caught a regression the fix introduced. Measurement answers exactly
the questions you know to ask and nothing else: not composition, hierarchy, reading order, or anything
painted on a canvas. Measuring is a complement to looking, never a replacement.

## Window size and viewport size

One browser tool's resize changed the OS window (`window.outerWidth`) but not the page viewport
(`window.innerWidth`), so every "at 375 px" measurement after it still measured the old width. Check
`innerWidth` after any resize, and use a tool or a headless context that sets a real emulated viewport
for breakpoint checks.

## Measuring resource weight

A page's JavaScript weight measured through the Resource Timing API came back five times too high with
code that should have been split out: the tab had visited another route earlier, and the router's
prefetches for it counted. A fresh tab measured the real weight. Both readings went into the report with
the contamination explained; the gap between them was the evidence.

## Measuring how much of a layout is used

A "half the layout is unused" finding was measured three times. A class name grep said most pages had
no columns (false: full-width tables and auto-fit grids also fill the width). `getBoundingClientRect()`
on leaf elements said everything was nearly full (false: a block element fills its container even when
its text stops at 40%). Only the real extent of text and painted boxes answers the question:

```js
const range = document.createRange();
range.selectNodeContents(textNode);
for (const r of range.getClientRects()) { /* real extent of the text */ }
```

united with the boxes of `canvas`, `svg`, `table` and `img`. That found only three underused zones
across the pages; the rest was a deliberate reading measure of about 70 characters.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-08-30-howto-mobile-content-unreachable-with-no-signal]]
- [[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]
- [[2026-09-04-howto-verify-contrast-on-translucent-card-by-pixel-sampling]]
