---
id: 2026-08-31-howto-artifact-own-meta-charset-is-unreliable
title: Character encoding in hosted artifacts
type: howto
area: [frontend, deliverables]
projects: []
tags: [artifacts, encoding, mojibake, html, howto]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-31
supersedes: []
---

## The symptom

A published deck showed broken accents ("cafÃ©" for "café", "naÃ¯ve" for "naïve"). The source file and the bytes saved
for the artifact were both correct UTF-8: the corruption happened at render time.

## Why

A hosted artifact is not served as your raw file. The platform wraps it in its own document, and your
file lands inside the wrapper's `<body>`. If your file starts with its own
`<!doctype html><head><meta charset="utf-8">`, that `<meta>` ends up in the body, where it declares
nothing: HTML honours `<meta charset>` only in the head, and only early. In the case observed, the
wrapper's own charset declaration also sat after a large inline script, past the first 1024 bytes that
browsers scan for it, so even that one could lose.

## What to do

In any artifact with accented or other non-ASCII text, do not rely on your own `<meta charset>`. When
mojibake shows up, write the characters as HTML entities (`&eacute;`, `&iuml;`, `&ntilde;`) or numeric
references; they render the same whatever charset the bytes are read as. Check the published page, not
only the file. This was observed on one hosting platform at one point in time; confirm it still happens
before converting a whole document.

## Links

- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
- [[2026-09-15-convention-every-artifact-also-as-html-file]]
