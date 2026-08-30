---
name: task
description: Runs a task end to end with the full protocol — searches the vault for context, isolates in a git worktree, plans, implements, verifies and saves what was learned. Use it for any task that touches code, has several steps or involves decisions.
argument-hint: [task description]
---

Orchestrate the task «$ARGUMENTS». You do **not** implement: you coordinate subagents and
keep your window clean. Do not read code files yourself except to unblock something.

## Current state

- Directory: !`pwd`
- Repository: !`/usr/bin/git rev-parse --show-toplevel 2>/dev/null || echo "(not a git repo)"`
- Branch: !`/usr/bin/git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "-"`
- Active sessions: !`/usr/bin/python3 __VAULT__/_bin/claim.py --list 2>/dev/null | head -5 || true`

## Before starting: does this produce code?

If the task is going to produce **code** — backend, frontend, scripts, a website or an
HTML deliverable — this pipeline is **not enough**: the `/dev` gates apply on top (tests
before implementation, hexagonal architecture, and if it has an interface, a design
interview and critique rounds). Invoke `dev` and follow both.

If the task produces no code — research, writing, data analysis, reorganising the vault —
follow only what is below. The `/dev` gates do not apply and forcing them would be
ceremony.

## Procedure

### 1. Context (always first)
Invoke `context-scout` with the task. Wait. Read the pack it returns and mark the session:
```
/usr/bin/python3 ~/Brain/_bin/mark_pack.py <pack-path>
```
If the scout declares gaps that block the work, **ask the user before continuing**.

### 2. Isolation
If you are in a git repo (and it is not the vault), create a worktree for the task:
```
SLUG=<short-task-slug>; SID=$(date +%H%M%S)
/usr/bin/git worktree add ../.wt-$SLUG-$SID -b feat/$SLUG-$SID
```
- If `git worktree add` fails on `index.lock`, retry up to 3 times with growing backoff.
- If it is **not** a git repo, carry on without a worktree and say so explicitly.
- All later work happens inside the worktree. Never in the main checkout.

### 3. Plan
For tasks touching more than one file, invoke `planner` with the pack path and the
worktree path. For a single-file change, skip this step and say so.

### 4. Implementation
Invoke `implementer` passing it: worktree path, pack path, plan path. Remind it not to go
looking for context on its own.

### 5. Verification
Invoke `verifier` in the same worktree. If the verdict is FAIL, go back to step 4 with
whatever it reported. Two rounds maximum; on the third, stop and tell the user.

### 6. Integration
```
/usr/bin/git -C <worktree> rebase <base-branch>
```
If the rebase conflicts, **do not resolve it blind**: report it. If it is clean, run
`verifier` again. Clean rebase + green verifier is the only valid exit.

### 7. Memory (mandatory)
Invoke `librarian` with: what was done, what was decided and why, what was learned about
the code. Have it write the notes and update the project MOC.

### 8. Closing
Summarise for the user: what changed, where the worktree and branch are, the verification
verdict, and what was saved to the vault. If you spot a procedure you have now repeated
twice, propose `skill-forge`.

## Rules
- One subagent per step, in the foreground, in order. Do not parallelise unless the steps
  are genuinely independent.
- If a step fails, stop and say so. Do not improvise an alternative path silently.
- When done, release the claims: `/usr/bin/python3 ~/Brain/_bin/claim.py --release`
