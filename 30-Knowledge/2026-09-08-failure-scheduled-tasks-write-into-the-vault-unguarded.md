---
id: 2026-09-08-failure-scheduled-tasks-write-into-the-vault-unguarded
title: Rules injected at session start do not reach subagents, skills or scheduled tasks
type: failure
area: [memory-system]
projects: []
tags: [subagents, scheduled-tasks, skills, protocol, failure]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-08
supersedes: []
---

## What happened

A writing rule was added to the protocol, which is injected at session start. It reached
sessions. It did not reach the scheduled tasks that create notes every morning, whose
prompts never said which language to write in, and one of which still carried an old
filename template that had just been renamed across the vault.

Enumerating every path that writes into the vault showed the same hole almost everywhere:

| write path | had the rule? |
|---|---|
| session at startup (`compass.py`) | yes |
| note template | yes |
| decision template | no |
| every agent definition (`librarian`, `context-scout`, `planner`, `implementer`, `verifier`, `skill-forge`) | no |
| the core skills (`save`, `task`, `ctx`, `recall`, `vault-doctor`) | no |
| scheduled tasks that write notes | no |

## Why

`compass.py` runs on `SessionStart`, and that hook does not fire for subagents; there is no
`SubagentStart`. So `librarian`, whose whole job is writing notes, had never seen the rule it
was supposed to follow. The agent definition is the only thing a subagent reads.

A less obvious path: `skills_index.py` copies each skill's `description:` into
`40-Skills/INDEX-<host>.md`, so a skill described in another language puts that language in
the vault by itself.

## What was done

- The rule was pasted into every agent definition, core skill, template and scheduled task
  prompt that writes notes.
- `brainlib.AGENT_RULES` lists the rules a subagent cannot learn any other way;
  `protocol_budget.py` reports which agents lack them and `protocol_guard.py` warns the
  moment an edit drops one.

## How to apply

Any new write path into the vault (an agent, a skill, a scheduled task, a script) needs the
writing rules pasted into it, not assumed.

## Links

- [[2026-09-08-convention-vault-is-written-in-english]]
- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
