---
id: 2026-08-25-convention-pitches-as-web-artifacts-with-infographics
title: Pitches and presentations as web pages with one infographic per slide
type: convention
area: [deliverables, design]
projects: []
tags: [pitch, presentation, slides, infographics, animation, house-style, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The convention

**A pitch or presentation is always a published web page**, not a slide file, a PDF or a memo, unless the
user asks for another format for a specific case. The deliverable is the page and its link, plus the HTML
file. [[2026-09-15-convention-every-artifact-also-as-html-file]]

Every slide is built from three things at once:

1. **An infographic or drawing in HTML or SVG that explains that slide's concept**: the mechanism, the
   relationship or the magnitude the slide is about. Not decoration and not a repeated template.
2. **Bullet points**, not paragraphs.
3. **Room for the presenter to talk.** The slide anchors the idea and the person presenting develops it.
   Never put everything that will be said on the slide.

## Motion, always subtle

Every presentation carries subtle animation: staggered entrances, a gentle ease-out curve, restrained
emphasis. It is part of the deliverable, not an extra for when there is time. Always honour
`prefers-reduced-motion`, on every redraw and not only the first.

## House style

Brand colours, typefaces, the motion vocabulary (curves, durations, keyframes) and any preferred animation
library are the user's **house style**. Record it once as a convention note in `30-Knowledge/` and follow it
in every pitch, page and report, instead of reinventing a look per deliverable. Until one exists, ask for
references (see the design interview in the `dev` skill) and propose a clean, restrained style: high
contrast, generous whitespace, one idea per screen.

## Content

- **Slide titles and section headings name the topic**, never a punchline; the finding goes in the bullets.
  [[2026-09-10-convention-write-like-a-person]]
- **Figures come from their real source**, never made up or rounded into a new claim.
- **Diagrams as inline SVG**, legible in light and dark themes.
- Design work on a web deliverable follows the `dev` skill's gates: design skills, critique rounds, one
  round only about images, and a look in a real browser after every correction.

## Anti-AI-slop pass

The same techniques that keep a web deliverable from reading as AI-made apply to slides: seed-string
or ambitious-prompt variety across an infographic set instead of the same template repeated per
slide, a blind fresh-context critic pass on the rendered slides before calling the deck done, and
generated image or video where a CSS-only graphic would look generic.
[[2026-09-18-convention-anti-ai-slop-design-techniques]]

## Why

A presenter speaking live is competed with, not supported, by a dense slide. A drawing that explains the
concept does work a paragraph cannot: the listener sees the shape of the idea while hearing it. A page is
shared by link and updates without resending files.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-08-25-convention-deliverables-to-the-vault]]
- [[2026-08-26-convention-code-development-pipeline]]
