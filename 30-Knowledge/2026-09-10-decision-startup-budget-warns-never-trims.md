---
id: 2026-09-10-decision-startup-budget-warns-never-trims
title: Startup context budget only warns and is raised when full
type: decision
area: [memory-system]
projects: []
tags: [context, budget, compass, startup, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-10
supersedes: []
---

## What was decided

The startup block that `compass.py` injects has a cap (`MAX_TOKENS` in
`_bin/protocol_budget.py`). The cap only warns. When the block needs more room, the cap goes
up. Nothing is ever cut from the context to stay under it.

## Why

- The cap never protected the context window. The block is about 1,500 tokens, injected once
  per session and carried in the prompt cache. Going over costs next to nothing.
- What trimming cost was real: on a busy morning whole sections (the active projects list)
  were dropped to save about 50 tokens, and those 50 tokens were noise.
- What the cap is still good for is discipline: it flags when the protocol is getting fat.
  That needs a warning, not a trim.

## What changed

- `compass.fit()` no longer drops sections. It returns the whole block and the verdict.
- Over the cap, the user gets a `systemMessage` saying nothing was cut and the cap should go
  up. `protocol_guard.py` and `protocol_budget.advice()` say the same.
- `MAX_TOKENS` went from 1400 to 1600.
- `compass.overlapping()` skips directories that are not a real project (a session in the
  home directory is not a project), which was the noise pushing the block over.

## How to apply

- Budget in WARN or OVER: first look for duplication with what the harness already injects
  and for fat bullets (`python3 ~/Brain/_bin/protocol_budget.py`). If every rule is needed
  and thin, raise `MAX_TOKENS`. Do not drop a rule or a section to fit.
- Never reintroduce trimming in `compass.py`.

## Links

- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
