---
id: 2026-08-23-failure-inherited-theme-tokens-in-opposite-background-subtree
title: Invisible text from an inherited theme colour token in a subtree that flips the background
type: failure
area: [frontend, design]
projects: []
tags: [css, custom-properties, tokens, contrast, accessibility, theming]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-23
supersedes: []
---

## The symptom

Photo captions were unreadable: near-white text on a near-white background, measured at barely above 1:1 against
the pixels actually painted.

## The mechanism

A theme defines coupled pairs of tokens at a section's root:

```css
--surface: #232a31;                          /* dark */
--on-surface-muted: hsl(205 25% 90% / .62); /* light, meant FOR that dark */
```

Inside the section, a component flips its background to light and resets `color`, but not the coupled
token:

```css
.card[data-scheme="inverse"] { background: var(--light-bg); color: var(--dark-text); }
```

and a global utility reads the token:

```css
.caption { color: var(--on-surface-muted); }
```

The caption is painted in the light colour meant for a dark background, on a light background. `color`
was reset; the token was not.

## The fix that held

Resetting the tokens on every light surface introduced the mirror bug: dark panels nested inside a light
one inherited the reset, and their captions failed from the other side. One set of names cannot serve
both contexts. Separate namespaces work:

- `--theme-surface`, `--theme-on-surface`, `--theme-on-surface-muted`: the section's palette, set once
  at its root and reassigned by nobody;
- `--surface`, `--on-surface`, `--on-surface-muted`: the roles of the surface you are on now. Every light
  surface reassigns them to dark-text values; every themed surface restores them from `--theme-*`.

Nesting then works in both directions at any depth. The caption utility reads no surface token at all:
`color: color-mix(in srgb, currentColor 70%, transparent)`. Measured: several hundred failing elements down to
zero, across every route and two widths.

## The rule

If a subtree changes `background`, it resets **every** colour token coupled to that background, not only
`color`. Best to worst:

1. every rule that sets `background` sets the coupled tokens in the same block;
2. secondary text utilities derive from `currentColor` with transparency;
3. a manual reset per component (the next component repeats the bug).

## How to hunt it

Reading the CSS will not find it. In the browser, walk every element with text, climb ancestors until one
has a non-transparent background, and compute the WCAG ratio; `color-mix()` or `rgba()` over `rgba()`
cannot be judged by eye. Over translucent or blurred layers, sample painted pixels instead
([[2026-09-04-howto-verify-contrast-on-translucent-card-by-pixel-sampling]]).

The bug was introduced by moving the theme variables from one component up to the section root to fix
something else. A fix that widens the scope of variables checks who else reads them.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-09-01-howto-css-source-order-and-override-traps]]
