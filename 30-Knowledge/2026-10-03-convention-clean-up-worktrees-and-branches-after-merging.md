---
id: 2026-10-03-convention-clean-up-worktrees-and-branches-after-merging
title: Cleaning up worktrees, branches and scratch files after a merge or publication
type: convention
area: [harness, git]
projects: []
tags: [git, worktree, cleanup, branches, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-03
supersedes: []
---

## The rule

Once work is merged (or pushed and published) and verified, clean up **at once and without asking**.
The user answered the recurring "shall I clean these up?" question with a standing yes, so the
question is no longer asked.

## What goes

- Every worktree the task created, removed with `git worktree remove`.
- Their branches, local only (`git branch -D` is fine once the content is merged or published).
- Backup branches made before a history rewrite or a squash (say `backup/pre-squash-1a2b3c4d`). They
  make the rewrite reversible until the push lands; after the push, what remains in them is exactly
  the content that was meant to be removed.
- Working files outside the repos: inventories, implementer briefs, plan files, commit message
  drafts in a temporary directory.

## When it does not apply yet

- Before the merge or push has happened and been checked (tests green, deploy verified, the remote
  branch tip equal to the commit that was pushed).
- When a worktree is still used by a live process: check `ps` and each process's working directory
  first, as in [[2026-09-26-runbook-unwedge-the-vault-sync-after-a-stuck-rebase]].
- Content that is not merged anywhere: a branch whose commits are not in main, and whose content was
  never checked to be there, stays, and the reply says why.
- Reusable tooling stays (a scanner or a script kept for the next run is not a scratch file).

The closing reply says in one line what was removed.

## Links

- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-09-30-convention-pull-requests-ready-on-main-merged-by-the-agent]]
