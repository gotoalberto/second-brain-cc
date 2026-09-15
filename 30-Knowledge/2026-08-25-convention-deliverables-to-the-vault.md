---
id: 2026-08-25-convention-deliverables-to-the-vault
title: Deliverables are stored with their project, intermediate versions included
type: convention
area: [deliverables, memory-system]
projects: []
tags: [deliverables, versions, object-storage, sources, projects, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Every project deliverable is stored and referenced from the project's note, intermediate versions too:
every version shown to the user is a deliverable. Showing it in the chat and moving on does not count;
the chat gets lost.

Files go to object storage with `s3v.py`, anchored to the note that explains them.
[[2026-08-26-decision-file-vault-in-s3]]

## What gets stored

- **The source**, always: what can be versioned and rebuilt (the HTML, the build scripts, the text).
- **The result**: the PDF, image or report.
- **The published URL**, if there is one, in the note itself.
- **The decisions behind that version**: what changed and why. A deliverable without its why forces
  someone to rediscover it.

## Build artefacts and source material

Two things of similar weight are handled in opposite ways:

- **A build artefact** (a self-contained bundle, a zip) is regenerated on every revision. Store its
  source and the command that rebuilds it, and say in the note where the bundle is.
- **Source material** (recordings, screenshots, transcripts, raw data) is stable and nothing can be
  rebuilt without it. Store it once, compressed, with a note saying what each piece actually shows. A
  file whose name does not match its content costs a full review the next time.

## Why

Without the stored deliverable, three things are lost: which version was shown and what was in it, the
ability to iterate on it instead of redoing it, and the reasons behind each change.

## Links

- [[2026-09-15-convention-every-artifact-also-as-html-file-to-s3]]
- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
