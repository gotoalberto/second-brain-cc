---
id: 2026-08-24-convention-local-ocr-to-audit-text-in-images
title: Auditing text inside images with local OCR
type: convention
area: [deliverables, verification]
projects: []
tags: [ocr, tesseract, images, placeholder, filler, audit, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The convention

To check what text a set of images contains before a deliverable ships (filler copy in screenshots,
strings that should not ship, text that contradicts its caption), use local OCR with Tesseract, not a
vision API.

- **No quotas**: it can run on every build.
- **Deterministic**: the same image gives the same text. A model may describe instead of transcribing, or
  quietly "fix" the filler.
- **Nothing leaves the machine**: a client's screenshots do not travel to a third party.

A vision model is still the tool for judgement: whether a caption describes its image, whether a
composition is badly framed.

## How

UI screenshots need preparing first:

```sh
magick in.webp -resize 1600x\> -colorspace gray -normalize -sharpen 0x1 out.png
tesseract out.png stdout --psm 6
```

Search for patterns, and iterate: the first pattern list is always too short. Scan, look at the images,
extend the list, scan again, until a round adds nothing. Three families:

- **Latin filler**: `lorem ipsum`, `dolor sit amet`, `consectetur`, and the rarer words (`curabitur`,
  `nullam`, `euismod`, `porttitor`).
- **Slot labels**: `(name|title|description) of the`, `goes here`, `[text in square brackets]`,
  `replace this`. Misspellings count too.
- **Slot values**: `XX points`, sample dates and figures.

A pattern that catches legitimate text is fixed or removed, not papered over with exceptions.

## Every finding lands in one of three places

1. **Fixed**, when clean material exists. First priority for anything large and uncaptioned (covers,
   heroes), where the filler is the message.
2. **Allowed**, when the filler is the subject of the figure (an unconfigured template, a wireframe), on an
   explicit list with the reason written next to it.
3. **Declared**, when the figure is evidence and the filler came with it (a spec export, a staging
   screenshot): the fix is to the framing, a short note saying where it comes from and what it does prove.

**Never fill a gap with plausible invented text.** That fabricates evidence.

Keep the three groups separate in the scanner and let only undeclared findings fail the check.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-09-10-convention-report-deliverable-shape]]
