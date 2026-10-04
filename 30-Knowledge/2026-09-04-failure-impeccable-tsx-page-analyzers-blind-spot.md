---
id: 2026-09-04-failure-impeccable-tsx-page-analyzers-blind-spot
title: Design detector coverage on .tsx pages
type: failure
area: [frontend, testing]
projects: []
tags: [impeccable, detector, tsx, react, linting, verification, decoys]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-04
supersedes: []
---

## What happened

The `impeccable` detector came back clean (exit 0, no findings) over the pages of a Next.js app written in
`.tsx` with plain CSS and `className`. A clean that empty was not taken at face value.

Decoys with obvious anti-patterns were planted in the code under review (a glowing `box-shadow`, brochure
copy, a `<marquee>`), and they came back clean too. A third decoy of a different kind did fire, which
proved the detector worked in general, just not over those files.

Reading the detector's source in the version installed then: its page-level analyzers ran only for files
with the extensions `.html`, `.htm`, `.astro`, `.vue` and `.svelte`. Six page-level rules (glow effects,
flat type hierarchy, monotonous spacing, marketing buzzwords, dash overuse, aphoristic cadence) never ran
on `.tsx` pages, and with plain CSS classes the style extraction had nothing to read either. The
detector's browser engine, which works on the rendered DOM instead of file extensions, needed a headless
browser package that was not installed.

The upstream code may have changed since; check the installed version before relying on either outcome.

## The lesson

A clean result from a detector means "nothing it knows how to read matched", not "no problems". On a
React or Next.js codebase, run the detector's browser engine against the rendered pages, or review the
skipped rules by hand.

**Plant a decoy before believing an almost empty clean.** This generalises to any linter or detector: a
clean result never proves the tool looked at what mattered until you have seen it fail when made to.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
- [[2026-09-01-convention-web-development-skill-stack]]
