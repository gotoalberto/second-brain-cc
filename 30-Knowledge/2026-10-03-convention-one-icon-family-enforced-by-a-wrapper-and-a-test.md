---
id: 2026-10-03-convention-one-icon-family-enforced-by-a-wrapper-and-a-test
title: One icon family and weight per project, enforced by a wrapper module and a test
type: convention
area: [frontend, design]
projects: []
tags: [icons, iconography, svg, emoji, design-system, testing, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-03
supersedes: []
---

## The rule

Once the user picks an icon set for a project (after seeing several candidate sets side by side), every
icon in that project comes from that family **in that one weight**. No other family, no other weight,
no hand-drawn SVG and no Unicode arrow standing in for an icon. The choice is written into the
project's own agent instructions (its `CLAUDE.md`) and into a vault convention note.

## How it is enforced

- Components never import the icon package directly. One module (`icons.tsx`) re-exports every icon the
  project uses and forces the weight: its props type omits `weight`, it defaults to `aria-hidden`, and
  it imports from the package's server-safe entry point so it works in server and client components.
- A test fails if any other file imports the icon package, or if the wrapper stops forcing the weight.
  When two apps share the wrapper by copy, the test also fails if the copies differ.
- A new icon is added to the wrapper by its name in the icon set, never inlined where it is used.
- An icon needed in a pseudo-element (the arrow after a text link, say) is the same family's SVG used as
  a CSS `mask`, since a pseudo-element cannot hold a component.

## What stays text

Arrows inside chart labels (`↑ 4%`) or between two figures (`12 → 15`) are typography, not icons, and
stay as characters.

## Emoji used as ornaments

An emoji used as a recurring brand or UI ornament (a mark after every heading, say) is a design
liability:

- it cannot be recoloured, so its contrast cannot be guaranteed; one measured close to 1:1 on a dark
  translucent card read as a grey smudge;
- every OS and font draws it differently, so the codebase does not control what the brand mark looks
  like.

Replace it with an inline SVG in `fill: currentColor`, added by the presentation layer, so domain data
(titles, labels) stays plain text. The same glyph then measured well above 4.5:1 and looked the same on every
platform.

## Links

- [[2026-10-03-convention-motion-in-web-interfaces]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
