---
id: 2026-09-16-convention-orchestrator-does-the-step-that-kills-agents
title: When a subagent dies twice at the same step, the orchestrator does that step
type: convention
area: [agents]
projects: []
tags: [agents, orchestration, subagents, context, worktree, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-16
supersedes: []
---

## What happened

Several agents worked in one shared worktree on a reverse engineering task. Two of them died at the
same step: reading a raw artefact of about 100 KB (a machine generated trace). One reported that the
machine had gone to sleep, the other that it stalled with no progress for ten minutes. The common
cause was loading the whole artefact into context.

Retrying the same brief would have failed a third time. What worked: the orchestrator did that step
itself, wrote the result to a small summary file on disk, and relaunched the agent with "this step
is DONE, read the summary, do not load the raw file; if you need parts of it, extract them with a
script that prints only what you need". That agent finished its whole assignment.

Doing the step also gave the orchestrator the most important finding of the session, so the effort
was not wasted.

## The rule

- A subagent failing twice at the same step is a problem with the brief, not bad luck. Change the
  brief or do the step yourself; never relaunch it unchanged.
- Big raw artefacts (traces, dumps, binaries, query exports) are for scripted extraction, not for
  reading. Say so in the brief, with the exact "print only what you need" instruction.
- Solving the hard step once and handing over the result is cheaper than three dead agents, and the
  orchestrator keeps the finding.

## Two more things shared worktree parallelism needs

- Give each agent an explicit list of its files and an explicit list of files it must not touch,
  naming the other agents' files. The one conflict seen came from an agent dropping scratch files
  at the repository root.
- Check the agents' work, do not just merge it. Agents found real bugs in what the orchestrator had
  written, and corrected claims already written down. Each correction was verified independently
  before it was propagated.

## Links

- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-09-15-convention-agent-orchestration-per-task]]
- [[2026-09-11-convention-agent-write-findings-to-disk-incrementally]]
