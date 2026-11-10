---
id: 2026-11-08-decision-shared-routine-preamble-blocks
title: "Rules every routine needs word for word live once, in preamble blocks"
type: decision
area: [harness]
projects: []
tags: [routines, tasks-py, preamble, humanizer, browser]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-08
supersedes: []
---

## Decision

Paragraphs that many routines need word for word (the humanizer pass for every text for people, the
browser probe and restart) live once in `90-Meta/routines/_preamble/<block>.md`. `tasks.py` puts them
between the routine's front matter and its body when it builds the prompt.

- A routine names its blocks in its front matter, `preamble: [humanizer, browser_restart]`, or
  `preamble: []` for none. Without the key it gets `humanizer`, plus `browser_restart` when its
  `agent_args` allow Claude in Chrome.
- The blocks always go in the same order, each once. A routine body that still carries its own copy of a
  block (a line starting with the block's opening words and a parenthesis) does not get a second one.
- A block file that is missing or empty refuses the run, exit 2, before any token is read: a routine
  must never go out without the rules it was meant to carry.
- `tasks.py --prompt <id or routine path>` prints the whole prompt a run would receive, preamble
  included, and runs nothing.

## Why

The same paragraph pasted into twenty routine files drifted into six variants within weeks, and a fix
reached some of them and not others.

## How to apply

Edit a shared rule in its block, never in a routine. A routine keeps only what is stricter for it
(language, length, voice).
