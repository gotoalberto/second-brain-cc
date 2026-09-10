---
id: 2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them
title: Instrument audit: what each gate and report claims versus what it sees
type: analysis
area: [memory-system]
projects: []
tags: [gates, hooks, observability, audit, analysis]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-08
supersedes: []
---

## What prompted this

Three unrelated failures in one session had the same shape: a language rule reached
sessions and never reached subagents; an inventory of scheduled work that called itself
complete was missing several tasks; and the memory gate insisted nothing had been saved on a
turn that had saved. So every gate, report and metric in `_bin/` was audited against one
question: what does it claim to cover, and what does it actually see?

Almost all of them had the gap. It is the default failure mode of instrumentation.

## The audit

| instrument | claims | actually watched | gap |
|---|---|---|---|
| `gate_write.py` | denies direct writes to `10-Projects/` and `70-Entities/` | matcher `Edit\|Write\|NotebookEdit` | shell writes were not gated at all |
| `doctor.py`, note hygiene | "notes with no links: 0" | whether a note contains `[[` | never checked whether a link resolves; almost a fifth of the edges pointed at nothing |
| `gate_memory.py` | "nothing was saved" | `COUNT(*)` over `vault_writes`, keyed on (session, path) | rewriting a note the session already wrote did not count |
| `compass.py` | injects the protocol | `SessionStart` | there is no `SubagentStart`; subagents never receive it |
| `protocol_budget.py` | startup budget | the compact protocol | measures what a session receives, not what a subagent receives (nothing) |
| `log_subagent.py` | the session's subagent trace | matcher listing six agent names | general-purpose subagents were invisible |
| `doctor.py`, retrieval | "below threshold: noise" | prompts that scored under the threshold | calls them noise; it cannot tell a correct filter from a miss |

## The real hole

`gate_write.py` exists so two sessions cannot corrupt a shared note. Its matcher did not
include Bash, and some permission modes tell the agent to prefer shell commands over the
file tools. Followed literally, that routes every write around the gate. Reproduced by
appending a line to a project note with a shell redirect: no denial, no warning, no lock.

The observers (`vault_ledger.py`, `protocol_guard.py`) already matched Bash; the enforcer did
not.

## Why they all fail the same way

Each instrument was written to close a specific incident and took the shape of that
incident as its frame. Then the frame silently became the claim. **The tell is a green line,
not a red one.** A red number gets investigated; "0 orphans" gets read as "the graph is
healthy" and skipped.

## What was done

| fix | change |
|---|---|
| `gate_write.py` matches Bash | a heuristic denies a command that names a protected folder and looks like a write; `vw.py`, `va.py`, `s3v.py` and `git` are exempt so the gate never blocks its own remedy |
| `vault_ledger.py` detects what the gate misses | a protected note whose mtime moved without `vw.py` (which now marks its own writes) raises a warning |
| `doctor.py` reports the graph | edges, broken, fixable, meeting topics, pending entities, classified by `linkfix` |
| `gate_memory.py` sees a rewrite | compares `MAX(ts)` of the session's writes, not only the count; changes to agents, skills or scheduled-task prompts under `~/.claude` also count as work to save |
| `log_subagent.py` matcher `*` | every subagent is logged |
| `doctor.py` stops calling it noise | the below-threshold line says it does not measure misses and a hand-judged sample is needed |
| `protocol_budget.py` reports subagents | lists each agent definition and flags the ones missing a core rule; `protocol_guard.py` warns the moment an edit drops one |

## How to apply

When adding a gate, report or metric, write down what it claims and what it actually
watches, and make the output say the second one. A number reported about a region the tool
never entered is worse than no number.

## Links

- [[2026-09-08-failure-scheduled-tasks-write-into-the-vault-unguarded]]
- [[2026-09-10-decision-every-search-finds-and-fixes-broken-links]]
