---
id: 2026-09-11-convention-agent-write-findings-to-disk-incrementally
title: Long-running agents write findings to disk and commit as they go
type: convention
area: [ai-agents, process]
projects: []
tags: [agents, parallel, usage-limits, commits, resilience, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

Several agents were running in parallel on a long investigation when a usage limit killed all of
them in the same minute. What survived was only what had been written to a file. One agent had
completed a substantial analysis that existed nowhere but its own context, and it was lost.

The same thing happened later with six agents. This time most had been committing per finding:
dozens of commits survived, nothing committed was lost, and each agent could be resumed by telling
it where it had stopped. The one agent that had saved everything for a final commit lost its work.

## The rule

An agent doing long investigative or implementation work writes each result to its target file
(evidence file, document section, vault note) as soon as it is established, and commits each
coherent finding as its own commit. It does not hold results in context for one write at the end.

Any kill signal has the same effect on unflushed context: usage limits, timeouts, crashes, a manual
interrupt. Design agent tasks assuming the process can die at any moment, and treat "written and
committed" as the only durable unit of progress.

## Corollaries

- **A dying agent's last status line is worth reading.** It names where the agent had got to, and
  relaunching with that hint is far cheaper than starting over.
- **Stage parallel agents.** Three or four at a time, refilled as they finish, gets the same work done
  without every agent hitting the limit together. Plan a large fan-out expecting at least one reset.
- **Commit findings, regenerate artefacts.** Large working files (downloaded datasets, generated dumps)
  stay on disk and out of git through `.gitignore`.
- **Run the final check in the foreground**, and stop every background job before reporting done.

## Links

- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
