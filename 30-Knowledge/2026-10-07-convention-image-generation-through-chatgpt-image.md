---
id: 2026-10-07-convention-image-generation-through-chatgpt-image
title: Choosing the source of an image, and generated images through the chatgpt-image skill
type: convention
area: [harness, design]
projects: []
tags: [convention, images, image-generation, html, svg, chatgpt-image, skills]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-07
supersedes: []
---

## The rule

Not every image request is a request for a generated image. For each image, the agent first decides
which source fits best and says why in one line:

- **HTML or SVG**: anything that is read or must be exact. Text, figures, charts, diagrams,
  infographics, cards, branded layouts.
- **A real image from the internet**: something that exists (a person, a product, a logo, a
  screenshot, a place, an event), with its licence respected and the source link kept.
- **A generated image**: a picture that does not exist yet (an illustration, an atmosphere, an
  invented scene, a texture, a concept), always through the `chatgpt-image` skill.
- **A mix**: a generated or found picture as background or element, with the text and figures built
  in HTML on top.

When the user names the generator in the request, that settles it. `chatgpt-image` is the one
generator in use; no other image API unless the user asks for it. Without a browser that can reach
the generator, say so instead of switching tools.

## Never generate what is read

A generated image carries no text, figures, logos or charts. An image model gets letters wrong,
invents numbers and redraws logos, and none of that can be checked or fixed afterwards. Titles,
numbers, labels, charts and brand marks are built in HTML or SVG, on top of a generated picture
when one is wanted.

The same holds for branded formats. A project's cards, social images and report pages are built in
HTML in the project's own style; a generated picture is at most a loose, textless piece inside them
(a backdrop under a dark veil, one illustration on a cover), optional and off by default. Asking a
generator for the whole card was tried and rejected: it breaks the brand system and its figures
cannot be trusted.

## Example

An invented bakery newsletter needs a header for its autumn issue and a chart of the month's best
sellers. The header is a generated illustration of loaves on a wooden table, prompted with no
lettering; the issue title is set in HTML over it. The chart is SVG from the sales table. The
bakery's logo comes from its own asset file.

## Where it is wired in

- The `chatgpt-image` skill carries this decision as its first section, and the list of skills that
  call it.
- The `dev` skill uses it for still images on websites.
- Reports and pitches may carry one optional generated illustration
  ([[2026-10-04-convention-reports-use-the-project-style]],
  [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]).

## Links

- [[2026-08-24-convention-local-ocr-to-audit-text-in-images]]
- [[2026-10-10-convention-global-quota-ledger]]
