---
id: 2026-09-10-convention-report-deliverable-shape
title: Shape and build of report deliverables
type: convention
area: [deliverables, writing]
projects: []
tags: [reports, pdf, html, bilingual, summaries, charts, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Default shape of an investigation report

When the user asks for an investigation and a report, the default covers, without being told each piece:

- **Identity first**: what exactly was examined, and whether the thing named is the real entry point or a
  front for something else. Report both.
- **The current version in depth**; older versions only as context (history, abandoned instances that
  still carry risk).
- **Everything related, in full**: the pieces discovered along the way get their full detail in the
  deliverable, not a one-line summary.
- **Extra depth on the highest-risk finding**, quantified, even when it is not what was asked about.
- **What is verified, what is inferred and what could not be determined**, said plainly.

## Format

- A PDF built from an HTML source in the house style, with diagrams, charts and code where they explain
  something; not a plain text write-up. [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
- Headings name the topic; no dashes as punctuation. [[2026-09-10-convention-write-like-a-person]]
- Code stays in its original language whatever the report language.
- The source HTML and the PDF are both stored with the project.
  [[2026-08-25-convention-deliverables-to-the-vault]]

## A second language should be cheap

Build in the language requested first, but structure the build so a full second version needs no
re-authoring:

- prose in `sections/*.md` with template tags for everything that is not prose (charts, figures, code,
  includes), resolved by a `--lang` switch;
- a mirror tree (`en/`, `es/` and so on) for translated includes, picked by the build under that switch;
- chart labels in one dictionary keyed by string id, with number and date formatting per language applied
  in one place.

Then the second version is: translate the mirror, flip the switch, rebuild. Translate faithfully: same
structure, same images, the target language's number formatting.

## Rendering a full-bleed PDF with headless Chrome

- Set the page background on `@page`, not only on `body`, or the margins print white.
- Page numbers come from `@page` margin boxes; pass `--no-pdf-header-footer` so Chrome does not add its own.
- For async content (fonts, charts) add `--virtual-time-budget=10000`.
- For a fixed page size, set `@page { size: ...; margin: 0; }` in a print stylesheet.

```sh
chrome --headless=new --no-pdf-header-footer --virtual-time-budget=10000 \
  --print-to-pdf=out.pdf file:///path/to/report.html
```

## Summaries of a meeting or recording

- Summarize everything presented, including answers to questions with their figures and dates.
- Every number comes from a slide or the audio; nothing invented, nothing rounded into a new claim.
- Label each section with where it is in the recording (part and timestamp) so the reader can jump there.
- Captions say what an image shows and where it comes from.
- When a page limit is set, render and look at every page, not only the page count. Fit by pairing
  figures side by side and tightening captions, not by shrinking type below readable size (about 9 pt).
- Close with next steps, open questions and anything the audience was asked to do.

## Links

- [[2026-09-15-convention-language-per-audience]]
- [[2026-08-24-convention-local-ocr-to-audit-text-in-images]]
