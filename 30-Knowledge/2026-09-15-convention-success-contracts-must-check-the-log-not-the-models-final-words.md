---
id: 2026-09-15-convention-success-contracts-must-check-the-log-not-the-models-final-words
title: Success contracts for unattended agent runs are checked against a side-effect log
type: convention
area: [harness, ai-agents]
projects: []
tags: [success-contract, headless, agent, determinism, send-log, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

A headless routine's success contract required the model's final answer to contain a
`sent to <address>` marker. The first real run did send the email (the send command returned a
message id), but the model then kept working, saving notes and starting a subagent, and its final
text no longer carried the marker. A run that had succeeded was judged a failure.

## The rule

**Do not decide whether an unattended agent run succeeded by matching the model's last words.** A
model's final answer is not a deterministic function of what it did: it can keep working after the
important action, summarize differently each time, or drop a marker it was told to include, all
without the action itself having failed or succeeded.

Check a durable record of the side effect instead, written by the deterministic code that performed
it, not by the model narrating it:

- an append-only log, one JSON line per event, written by the send or write function itself;
- keyed by a run id minted by the runner before the model is invoked and passed to it in the
  environment;
- the contract asks "does the log show this run id delivered X", never "does the transcript say X".

The model's text stays useful as information but is never authoritative. An answer that only
claims a send does not count; a run that sent counts whatever its answer ends on.

## How to apply

Any contract of the form "did the headless agent do the important thing" should be answerable from
a log the code writes on its own. In this repo the routine runner sets `BRAIN_ROUTINE_RUN_ID` and a
send log path for every attempt, and a routine declares `required_sends` in its success contract.

## Links

- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-15-convention-headless-agent-prompt-must-be-framed-as-an-order]]
