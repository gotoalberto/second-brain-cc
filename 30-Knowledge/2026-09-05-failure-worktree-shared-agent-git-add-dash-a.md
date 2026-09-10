---
id: 2026-09-05-failure-worktree-shared-agent-git-add-dash-a
title: git add -A in a worktree shared with a running agent swept up its files
type: failure
area: [engineering]
projects: []
tags: [git, worktrees, agents, concurrency, failure]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-05
supersedes: []
---

## What happened

An agent was writing tests in a worktree. While it ran, a small unrelated fix was made in the
same worktree and committed with `git add -A`. The commit swept up the agent's half-written
files, which did not even compile yet.

## How it was undone without damage

1. `git reset --soft HEAD~1` undoes the commit and leaves everything staged; it does not
   touch the working tree.
2. `git restore --staged <the agent's files>` takes them out of the index without touching
   them on disk.
3. Commit only your own files again.

`--soft` and `restore --staged` never touch the working tree, so the agent's files did not
move and it kept working without noticing. Any variant with `--hard`, `checkout .` or
`clean` would have destroyed its work in progress with no way back.

## The rules that come out of it

- **One worktree, one active writer.** "One worktree per deliverable" did not cover stepping
  into a worktree where someone is already working. If an agent is active there, the small
  fix goes in another worktree or waits.
- **Never `git add -A` or `git add .` in a tree you are not sure is yours alone.** Add by
  explicit path.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
