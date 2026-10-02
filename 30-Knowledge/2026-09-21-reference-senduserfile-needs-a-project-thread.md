---
id: 2026-09-21-reference-senduserfile-needs-a-project-thread
title: SendUserFile and sessions outside a project thread
type: reference
area: [harness]
projects: []
tags: [senduserfile, file-delivery, deliverables, remote-control, fallback]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-30
supersedes: []
---

# SendUserFile and sessions outside a project thread

## What happens

The agent's file-delivery tool, `SendUserFile`, can fail outright with a message saying the session
is not on a project thread and has nowhere to place a file. Size and type have nothing to do with it:
it depends on the kind of session. It was seen in a cloud session delivering a zipped code kit, after
the file had already been built.

## What to do

- **Do not retry it.** The same session fails the same way.
- **Have a fallback ready before promising a file**:
  - code that belongs in a repository goes on a branch or in a pull request;
  - the exact path on the machine, as a clickable link, so the user can open it themselves
    ([[2026-08-28-convention-clickable-links-and-send-files]]);
  - short text content pasted inline in the reply;
  - a copy kept in the file store with `files.py put <file> --to <note> --project <slug>`, so the
    deliverable is not lost when the session ends, plus a link from wherever the user shares files.
- **Open any link before handing it over** (a `curl -sI` that answers 200 or 206). A link that has
  not been opened is not a delivery
  ([[2026-08-28-convention-links-must-resolve-and-be-verified-open]]).

## Links

- [[2026-08-28-convention-clickable-links-and-send-files]]
- [[2026-08-28-convention-links-must-resolve-and-be-verified-open]]
- [[2026-09-15-decision-file-vault-in-a-local-directory]]
