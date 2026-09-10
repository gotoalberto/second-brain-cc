---
id: 2026-08-21-convention-worktree-isolation-per-deliverable
title: Worktree isolation per deliverable
type: convention
area: [engineering]
projects: []
tags: [git, worktrees, isolation, agents, concurrency, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-21
supersedes: []
---

## The rule

**The unit of isolation is the unit of merge.** Everything that will be reviewed and
integrated as a single change shares a worktree. Whatever gets integrated separately, or
competes with the rest, goes in a separate worktree.

Three levels come out of that:

1. **Read-only or exploration:** no worktree. Work in the main checkout and commit nothing.
2. **One deliverable that writes:** one worktree with its branch, seeded with
   `seed_worktree.py`. Not "one per session": a session with three independent tasks needs
   three worktrees, and three sessions on the same branch share one.
3. **Several writing agents at once:** by default they share the task's worktree,
   partitioned by file, each declaring its own with `claim.py`. If two claims collide, you
   serialize, you do not isolate.

A worktree of its own per agent only in three cases:

- The files genuinely overlap and cannot be divided up.
- Each agent needs a build, tests or a server at the same time.
- They are competing alternatives, of which one will be picked.

Then the child worktrees branch off the task branch and are integrated one at a time, running
`verifier` after each merge.

## Why not one worktree per agent

It turns a concurrency problem into N merges, and merges of generated work over the same
files are semantic, not textual: each agent rewrites imports, helpers and signatures its own
way. It also multiplies the seeding cost. The real failure is launching writers in parallel
without dividing the files first. If you cannot say in advance which files each agent
touches, do not launch them in parallel.

## What a worktree does not isolate

Ports, databases, containers, queues, global caches and cloud resources. Parallel agents that
start servers or touch a database need their own port or schema, or must be serialized, even
with separate worktrees. If the directory is not a git repo, carry on without a worktree and
say so; never improvise a copy of the project.

## Links

- [[2026-09-05-failure-worktree-shared-agent-git-add-dash-a]]
- [[ARCHITECTURE]]
