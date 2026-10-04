---
id: 2026-09-01-howto-css-source-order-and-override-traps
title: "CSS override traps: reduced motion, source order, inline padding and subgrid alignment"
type: howto
area: [frontend]
projects: []
tags: [css, accessibility, specificity, reduced-motion, subgrid, responsive, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

Each of these is invisible when reading the rule that looks responsible, and only shows up measuring the
rendered page. All share one shape: a rule that is correct on its own, defeated by a second rule whose
interaction with it nobody checked. Sibling list: [[2026-09-30-howto-web-css-and-build-traps]].

## Reduced-motion catch-alls

A `prefers-reduced-motion` block declared softer, non-zero durations for a few named animations and then
ended with a catch-all in the same block:

```css
@media (prefers-reduced-motion: reduce) {
  .fade-soft { animation-duration: 600ms; }
  *, *::before, *::after { animation-duration: 0.01ms !important; }
}
```

The catch-all comes later and wins, so the site's promise of "less motion, not none" delivered none.
Exclude the named classes from the catch-all (`*:not(.fade-soft)`), or put the catch-all first.

## Display toggles that depend on source order

`.chart-narrow { display: none }` lost to `.chart { display: block }`: equal specificity, and `.chart` came
later in the file, so both responsive variants rendered stacked. It happened twice in the same repo. A
`display` value that depends on which selector is declared last is not a responsive switch: put it inside
a real `@media` query, or use selectors that can never both match at the same breakpoint.

## Inline padding shorthand and a gutter class

`style={{ padding: "32px 20px 48px" }}` on an element that also has `.page-gutter` (which sets the
horizontal padding) overrides that padding, because inline styles beat any class. The footer started
20 px inside everything else. When a class owns one axis, set only the other axis inline
(`paddingTop`, `paddingBottom`).

## Modifiers declared before their base rule

A modifier `.note--wide { margin-top: 20px }` declared before `.note { margin-top: 8px }` in the same
file lost; prefixing it with its container (`.readout .note--wide`) fixed it. When a modifier "does
nothing", compare source order and specificity before anything else.

## Align two columns whose labels wrap differently with subgrid

Two side-by-side cells (label, figure, note) drifted on phones when one label wrapped to two lines and
pushed its figure below the other. Share the rows through subgrid:

```css
.pair { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: auto auto auto; row-gap: 10px; }
.pair > .cell { grid-row: 1 / span 3; display: grid; grid-template-rows: subgrid; }
.pair .label { align-self: end; }   /* a short label sits on its figure */
```

Rows stay aligned for any label length and font size, and the desktop render was unchanged (measured).
Shortening labels, `nowrap` and fixed label heights were the rejected alternatives. When such a block sits
inside a shape that scales with the viewport, size it from the same quantity (`width: min(560px, 60vmin)`
with `container-type: inline-size`, figures in `cqi`), and keep an amount and its unit together with
`white-space: nowrap` on a wrapper.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-08-23-verify-frontend-findings-against-production]]
- [[2026-08-23-failure-inherited-theme-tokens-in-opposite-background-subtree]]
