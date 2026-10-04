---
id: 2026-08-20-decision-seeded-artifacts-outside-git
title: Everything seeded into a worktree is excluded from version control
type: decision
area: [harness, security]
projects: []
tags: [worktree, git, secrets, seed, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-20
supersedes: []
---

## What was decided

`_bin/seed_worktree.py` records every file it seeds into a worktree (the context pack, the protocol, the
plan, `.env.local`, any `.env*` it copies and any directory it links) and adds exactly that list to the repository's
`.git/info/exclude`. The list holds what was really seeded; it is never a fixed set of names.

## Why

The `verifier` agent noticed that a `git add -A` at commit time would sweep the seeded files in. The
regression test then showed the worst case: among them was the `.env` that seeding copies from the main
checkout. In a project without a `.gitignore`, the harness would have committed credentials into the
user's repository.

`info/exclude` rather than `.gitignore`: it is local, it does not dirty the user's repository and it does
not travel to other clones.

## Consequences

- The exclusion is per repository, since `info/exclude` is shared by all its worktrees. Acceptable: none of
  those files should ever be committed anywhere.
- A file that is already tracked is not affected by `info/exclude`.
- Agents still stage files by name, never with `git add -A`
  ([[2026-09-05-failure-worktree-shared-agent-git-add-dash-a]]).

## Links

- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
