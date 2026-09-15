---
id: 2026-08-30-convention-impeccable-craft-floor-rules-for-web
title: Craft floor for web pages and web deliverables
type: convention
area: [design, deliverables]
projects: []
tags: [web, design, accessibility, contrast, motion, critique, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

Critique passes on web deliverables kept finding the same violations. These are checked before a page,
pitch or report page is called done, alongside the `dev` skill's design gates.

## Layout and typography

- **No eyebrow or kicker labels above a headline.** The headline carries its own weight.
- **No coloured `border-left` accent thicker than 1px** on cards, lists or callouts.
- **Monospace only for code, data and measurements**, never as a costume for "technical".
- **A route with no `<h1>` usually has no page title either**; check both.
- **Fill an empty half of a layout with evidence for the claim beside it**, not with decoration. If no
  evidence exists, the claim may not either. Before widening a narrow column, check whether its width is a
  deliberate reading measure (around 70 characters).
- **A semantic colour marks the block, not its body.** A warning set entirely in the warning colour reads
  as a sticker and less urgent; colour the heading, keep the body in normal ink.

## Motion and visibility

- **One animated moment per page, starting from an already visible state**, not the same reveal repeated
  on every section.
- **Never hide content until JavaScript runs.** `opacity: 0` in server-rendered HTML revealed by script
  leaves the first paint blank, and permanently blank if the script fails. Animate on top of content that
  is already legible.
- **`prefers-reduced-motion` is honoured on every redraw path** (resize, font load, orientation change),
  not only on first render.

## Contrast and controls

- **Audit contrast starting from disclaimers, fine print, table headers and form labels.** Headlines get
  checked by reflex; low contrast concentrates where nobody looks first.
- **A decorative divider colour is not a control border.** Controls need 3:1; keep a separate stronger
  token for anything clickable or editable.
- **Recompute a contrast ratio after every fix**, never reason about it on paper.
- **`input:focus { outline: none }` beats `:focus-visible`** on specificity; check what else targets
  `:focus`.
- **Browser-painted surfaces are part of the design**: selection, caret, scrollbars, focus ring, underline
  colour.
- **A disabled control cannot explain itself**: screen readers skip it. Put the reason in its own line
  with `aria-live="polite"`.

## Honest actions and links

- **Never show an action the system will refuse.** If nothing can be done yet, say what is available
  instead of a button that bounces.
- **Every absolute URL in the page resolves on the day it ships** (canonical links, social card images,
  metadata base), not on the day an intended domain is expected to exist.
- **A title template in the layout means page titles are fragments**; do not repeat the site name.

## How to check

- Measure the rendered page, not the stylesheet: inline overrides only show up live.
- Look at it in a real browser at several sizes and in both themes; numbers alone miss empty screens and
  off-screen drawing.
- When two evaluations run in parallel and one causes changes, record which commit each measured.
- Run design review and detector or browser evidence as two separate agents; they catch different things.
- Treat a detector hit that contradicts an explicit brief (a deliberate grid background, say) as a question
  about the brief, not an automatic finding.

## Links

- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
- [[2026-08-26-convention-code-development-pipeline]]
- [[2026-08-24-convention-local-ocr-to-audit-text-in-images]]
