---
id: 2026-10-04-convention-reports-use-the-project-style
title: Reports for a project always carry that project's visual style
type: convention
area: [deliverables, design]
projects: []
tags: [reports, pdf, style, branding, house-style, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The rule

Any report, analysis or document produced for a project (PDF, HTML page, deck) uses that project's own
visual identity: its palette, typefaces, brand mark and chart style, **taken from the project's code,
never invented**. The user set this as a standing rule for every project, after a report came out
looking like the project it was about.

- For a project with a web, read its global stylesheet and tokens first; that is the source of truth.
- For a project with no defined style yet, read whatever CSS exists; ask only if there is none.
- Without any project, the user's house style applies
  ([[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]).

## Record the style once, as a reference

The first time a report for a project is accepted, write its style down as a convention note (and
keep the HTML template and build script with the project's files), so the next report starts from it.
The note covers:

- **Page**: size, light or dark, background on the page itself (`@page { background }` plus
  `print-color-adjust: exact`), surface and rule colours, ink levels.
- **Accent**: one accent colour for section numbers, key figures and chart marks; semantic colours
  (up, down) only for what they mean.
- **Typefaces**: one for text, one (often monospace) for figures, table numbers and axes.
- **Cover**: the brand mark from the project's own asset, kicker, title, a row of key figures,
  sources and date.
- **Body**: how sections are numbered and whether each starts a page; the running footer from
  `@page` margin boxes.
- **Charts**: line weight, fill, grid, axis labels, reference curves.
- **Tables**: header style, number alignment, how links and flags look.
- **Copy**: language, number format, time zone, the writing rules
  ([[2026-09-10-convention-write-like-a-person]]).
- **Build**: HTML template plus a script that fills it, printed with headless Chrome, then every
  rendered page looked at before delivery ([[2026-09-10-convention-report-deliverable-shape]]).

## Example

An invented project "Lumen" whose web defines `--bg: #18202a`, `--fg: #e8ecef` and one teal accent in
`globals.css`: its reports are dark A4 pages with the teal accent on section numbers and chart lines,
the Lumen mark from `public/icon.svg` on the cover, and nothing borrowed from another project's look.
