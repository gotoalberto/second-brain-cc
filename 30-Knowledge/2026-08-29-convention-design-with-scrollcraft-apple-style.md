---
id: 2026-08-29-convention-design-with-scrollcraft-apple-style
title: "Design work: clean Apple-like style, scroll-linked animation and HTML infographics"
type: convention
area: [design, frontend]
projects: []
tags: [design, apple-style, animation, parallax, scroll, infographics, scrollcraft, house-style, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The convention

Whenever design comes up, for any project, the result is:

- **clean, in an Apple-like style**: restrained, high contrast, generous whitespace, one idea per
  screen. A default to follow, never reinterpreted per project;
- **animated**: scroll-linked animation and parallax are part of every web the user asks for, never
  kept for when the design "fits" it;
- **explained with infographics built in HTML** (or SVG, or canvas), never a paragraph where a drawing
  would show the mechanism.

The user then added that every web closes with the `impeccable` skill's `critique` command, as in the
web pipeline ([[2026-09-01-convention-web-development-skill-stack]]).

## The tool for scroll animation

The user named [ScrollCraft](https://github.com/singhharsh1708/scrollcraft) as the builder for
scroll-linked animation: an open source (MIT) builder for cinematic scroll animation sites, canvas
based, no WebGL and no heavy framework, exporting plain HTML, CSS and JS. It installs as a Claude Code
plugin:

```
/plugin marketplace add singhharsh1708/scrollcraft
/plugin install scrollcraft@scrollcraft
```

Its local mode needs Node 20 or newer and ffmpeg.

**Use the tool itself, not only its technique.** A landing page was once built with scroll-linked
canvas animation in the same spirit but without the plugin, and without a critique pass; the user
corrected both. Install the plugin when design work starts, before producing mockups or animation
code.

## How it fits with the rest

- The motion itself is still decided with the animation skills (curve, duration, interruption,
  reduced motion) and the user's motion preferences
  ([[2026-10-03-convention-motion-in-web-interfaces]]).
- Pitches follow the same style with their own rules
  ([[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]).
- Honour `prefers-reduced-motion` on every redraw path
  ([[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]).
