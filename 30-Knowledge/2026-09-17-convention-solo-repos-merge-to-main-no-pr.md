---
id: 2026-09-17-convention-solo-repos-merge-to-main-no-pr
title: Repositories the agent creates and alone maintains merge to main with no pull request
type: convention
area: [git, devex]
projects: []
tags: [git, github, pull-requests, merge, main, personal-repos, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

## The rule

For a repository the agent created for the user and is the only one to maintain (no other reviewer,
no team), there is no pull request. The work merges straight into `main` and is pushed often. If the
user asks for it, the work happens on `main` directly, with no feature branch at all.

Shared or team repositories keep their own flow (pull requests, the team's target branch, signed
commits, whatever the team requires). Both rules hold at the same time; the question that decides
is who owns and reviews the repository.

## Why

A pull request with no second reviewer is ceremony. Nobody reviews it, and nothing in the merge
benefits from the review interface when the one who writes the code is also the one who merges it.
The user asked for this explicitly after a session opened a pull request on such a repository.

## How to apply

1. Do the work on a branch (or on `main`, if the user asked for that).
2. Before merging, check that `main` is an ancestor of the branch:
   `git merge-base --is-ancestor main <branch>`.
3. Merge with `git merge --ff-only`, which keeps history linear with no merge commit.
4. `git push origin main`, and confirm that the local and remote heads are the same commit.
5. Do not run `gh pr create` for this class of repository.
6. Delete a feature branch once it is merged. A branch checked out in a worktree cannot be
   deleted: `git worktree remove <path>` first, after checking that `git status -s` is clean there
   and `git log main..HEAD` is empty, then `git branch -d <branch>`.

## Tension with the worktree rule

The protocol says that writing code always happens in a worktree. Working on `main` in the primary
checkout, when the user asks for it on this class of repository, is an explicit exception from the
user. It is recorded here so that a later session does not "correct" it back. Whether the protocol
text itself should carry the exception is the user's call.

## Links

- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-09-16-convention-push-vault-changes-immediately]]: a different rule, about when the vault
  itself is pushed
