---
id: 2026-10-23-decision-skill-notes-use-home-relative-paths
title: Skill catalogue notes use home-relative paths
type: decision
area: [harness]
projects: []
tags: [skills-index, sync, guardian, heartbeat, rebase, conflicts]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-23
supersedes: []
---

## Context

`_bin/skills_index.py` writes one note per installed skill under `40-Skills/`, and each note carries a
`**File**` line with the skill's path. It used to write the machine's absolute home
(a Linux home directory on one machine, a macOS one on another). Every
machine with a different home then rewrote all the catalogue notes on each pass, each sync committed
the other machine's rewrite back, and the two machines kept trading the same commit. That churn is a
steady source of sync conflicts on files nobody edits by hand.

Separately, a guardian alert such as "hook sync failed 5 of its last 5 runs (status error)" can come
from a machine that is not the one reading the mail. `vault_sync.py` returns 1 on every pass while a
rebase is in progress (committing would land on a detached HEAD), and a non-zero exit with no
exception is recorded in the heartbeat as `status error`.

## Decisions

- **The `**File**` line is home-relative.** `skills_index.py` writes it as `~/.claude/...` through
  `home_relative()`, so every machine produces the same text and no pass rewrites a note another
  machine wrote. Tests in `_bin/skills_index_test.py`.
- **A sync that fails on every pass is read as a possible stuck rebase first.** Check which machine
  sent the alert, then on that machine look for `.git/rebase-merge` or `.git/rebase-apply` before
  anything else. The repair is
  [[2026-09-26-runbook-unwedge-the-vault-sync-after-a-stuck-rebase]], and since
  [[2026-10-23-decision-sync-never-rebases-on-a-deadline]] the session start of that machine also says
  so in its own block.
- **Never abort a rebase that has been open for long without a backup.** The abort resets to the
  original head and drops every note written on that machine since, because the blocked sync never
  committed them. Save the rebase directory and the staged and unstaged changes as patches first.
  Continuing the rebase with a no-op editor is not a safe shortcut either: it can commit a file with
  conflict markers inside.

## Links

- [[2026-10-23-decision-sync-never-rebases-on-a-deadline]]
- [[2026-09-16-gotcha-skill-notes-are-truncated-not-corrupt]]
- [[2026-09-15-runbook-brain-guardian]]
