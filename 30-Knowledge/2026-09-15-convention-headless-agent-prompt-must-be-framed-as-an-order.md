---
id: 2026-09-15-convention-headless-agent-prompt-must-be-framed-as-an-order
title: Framing the prompt of a headless agent run
type: convention
area: [harness, ai-agents]
projects: []
tags: [headless, prompt, cli, agent, routines, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

A scheduled routine handed its whole procedure file, verbatim, as the prompt of a non-interactive
CLI agent run. The file opened with an HTML comment block written for a human reader. The model read
the body as background material, answered within seconds without using a tool, and said it had no
request to fulfil. The procedure was correct; the framing of the handoff was missing.

## The rule

An agent invoked non-interactively, with nobody at the keyboard to say "yes, do it", has to be told
explicitly that the text it receives is an order to execute now, not material to consider. Without
that, a model treats a bare document, especially one that opens with a comment block or reads like a
spec, as context for a conversation that has not started.

## How to apply

1. Strip what reads as documentation for a person: frontmatter and `<!-- -->` comments.
2. Wrap the rest in an explicit instruction: this is an unattended run happening now, the procedure
   below is the order, do not ask for a request and do not wait for input.
3. State the run's constraints in the wrapper: the run id, the scratch directory it may write to,
   no subagents or background jobs (they die with the process), one command at a time instead of
   chained commands, temporary files only in the scratch directory.
4. Repeat inside the routine's own prompt any constraint its specific steps would otherwise break.

This applies to any cron, launchd or systemd triggered model call: its prompt is not the same speech
act as a person typing into a chat.

## Links

- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-15-convention-success-contracts-must-check-the-log-not-the-models-final-words]]
