---
id: 2026-09-15-convention-agent-orchestration-per-task
title: Agent orchestration per task
type: convention
area: [ai-agents, process]
projects: []
tags: [agents, subagents, orchestration, models, effort, parallel, worktrees, verification, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The roster

Each agent is defined in `integrations/claude-code/plugin/brain/agents/<name>.md`. Its frontmatter
sets the model, the reasoning effort and the tools, and that frontmatter is the one place to change
them. Sync afterwards with `python3 ~/Brain/_bin/install_plugin.py sync`.

| agent | model | effort | tools | why this level |
|---|---|---|---|---|
| `context-scout` | haiku | medium | Read, Grep, Glob, Bash, Write (a hook limits writes to `60-Context-Packs/`) | searching and distilling is broad but shallow work; a small fast model keeps the cost of running it before every task low |
| `planner` | sonnet | high | Read, Grep, Glob, Write, Bash | a wrong plan is the most expensive mistake in the pipeline, so it gets high effort |
| `implementer` | inherits the session model | session default | all tools | it does the real work and should be as capable as the session that launched it |
| `verifier` | sonnet | high | Read, Bash, Grep, Glob; Write and Edit disallowed | it reads and executes only, so it cannot fix its way to a pass; high effort because a false PASS is what lets bugs through |
| `librarian` | sonnet | medium | Read, Write, Edit, Bash, Grep, Glob | writing notes needs judgement about what is durable, not deep reasoning |
| `skill-forge` | sonnet | medium | Read, Write, Edit, Bash, Glob, Grep, Skill | it uses the skill-creation skill, so it needs the Skill tool |

A subagent never sees the startup protocol, so the rules it must follow (English in the vault,
headings that name the topic, shared notes through `vw.py`) are written into its own definition.

## The pipeline for one task

The `task` skill runs these steps with **one subagent per step, in the foreground, in order**,
unless steps are genuinely independent. The orchestrator coordinates and keeps its context clean; it
does not read code except to unblock something.

1. **`context-scout` always first.** It writes a Context Pack and returns only the pack path and a
   summary of at most eight lines. Gaps that block the work go to the user before anything else.
2. **`planner` only when the task touches more than one file.** For a single-file change the step is
   skipped, and the orchestrator says so.
3. **`implementer`** gets the worktree path, the pack path and the plan path, and does not go looking
   for more context on its own.
4. **`verifier`** runs in the same worktree. On FAIL, back to the implementer with the report. At most
   two fix rounds; on the third failure, stop and tell the user.
5. **Integration.** Rebase on the base branch, run the verifier again, then fast-forward. A conflict is
   reported, never resolved blind.
6. **`librarian` before closing**, with what was done, what was decided and why, what was learned, and
   the files produced outside the vault.

Code tasks add the `dev` gates on top. [[2026-08-26-convention-code-development-pipeline]]

## When and how to parallelise

Run implementers in parallel only when the work splits cleanly by file, or when each needs its own
build, tests or server at the same time. Then:

- **One worktree per implementer, all created from the same base commit.**
  [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- **Explicit file ownership written into each prompt**: which paths the agent owns and which it must
  not touch. If ownership cannot be stated in advance, do not parallelise.
- **Register the files with `claim.py`**, so a colliding claim serializes the work instead of
  overwriting it.
- **One verifier per branch.**
- **Before merging, rebase each branch and run the full test suite on every supported interpreter**,
  then merge one branch at a time with a verifier after each merge.
- **The coordinator never implements.** It launches, reads results, routes findings and merges.

## Background agents

- Launch independent agents together, in one step, rather than one after another.
- **Never poll a running agent.** Wait for its completion notice.
- To check progress without interrupting, look at its worktree: new commits and file modification
  times. This is one reason agents commit per finding.
  [[2026-09-11-convention-agent-write-findings-to-disk-incrementally]]
- An agent can stop while waiting on a background command of its own and report itself finished. Send
  it a message telling it to run the command in the foreground and read the result.

## Size of a multi-agent workflow

Keep one workflow under about 15 agents unless the user asks for more. Large fan-outs hit usage limits
together and lose unsaved work; run parallel agents in waves of three or four and refill as they finish.

## Verification discipline

- **The verifier is independent** of the agent that wrote the code, and cannot edit.
- **Red then green proof** comes from temporary detached worktrees: check out the test commit alone and
  show it failing, then the implementation commit and show it passing, without touching the working
  branch.
- **Smoke checks redirect every state path.**
  [[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]
- **Before publishing anything**, a separate agent that did not write the material reads it through
  for private or identifying content, in addition to any automated scan.
- Headline numbers an agent reports are re-derived before acting on them.
  [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]

## Where to change models or effort

In the agent's frontmatter (`model`, `effort`, `tools`, `disallowedTools`) under
`integrations/claude-code/plugin/brain/agents/`, then `install_plugin.py sync`. The orchestration
rules themselves live in the `task` skill and in this note.

## Links

- [[2026-08-26-convention-code-development-pipeline]]
- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]
- [[2026-09-11-convention-agent-write-findings-to-disk-incrementally]]
- [[2026-09-05-failure-worktree-shared-agent-git-add-dash-a]]
