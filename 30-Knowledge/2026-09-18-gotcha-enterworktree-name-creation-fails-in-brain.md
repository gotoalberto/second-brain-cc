---
id: 2026-09-18-gotcha-enterworktree-name-creation-fails-in-brain
title: EnterWorktree by name fails in the vault, so create the worktree with git and pass its path
type: gotcha
area: [harness, devex]
projects: []
tags: [worktree, enterworktree, claude-code, hooks, seed-worktree, gotcha]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-18
supersedes: []
---

## What happens

Claude Code's `EnterWorktree` tool, asked to create a new worktree by `name` inside the vault,
fails with:

```
WorktreeCreate hook failed: hook succeeded but returned no worktree path
```

## Why

The vault registers its own `WorktreeCreate` hook, `_bin/seed_worktree.py`. It is a seeding hook:
it copies into the new worktree the state that worktree needs, and it always exits 0. It does not
print a worktree path. When a `WorktreeCreate` hook is registered, the tool's name based creation
expects the hook to create the worktree and report its path, which this hook never does. The hook
is working as designed; the two simply do not fit.

## What works

Create the worktree with git, then enter it by path:

```sh
git -C ~/Brain worktree add -b <branch> <path> main
```

and call `EnterWorktree` with `path: <that path>` instead of `name:`, so the harness still tracks
it. Clean up afterwards with `git worktree remove <path>` and `git branch -d <branch>`.

The same hook is why Remote Control's `--spawn worktree` mode must not be used on the vault; see
[[2026-09-21-runbook-install-on-a-new-machine]].

## Links

- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-09-21-runbook-install-on-a-new-machine]]
