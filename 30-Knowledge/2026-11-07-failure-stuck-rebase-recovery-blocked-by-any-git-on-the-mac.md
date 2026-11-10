---
id: 2026-11-07-failure-stuck-rebase-recovery-blocked-by-any-git-on-the-mac
title: "A laptop stayed stuck for a day on a rebase that died before it began"
type: failure
area: [harness]
projects: []
tags: [sync, vault-sync, rebase, autostash, recovery, laptop]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-07
supersedes: []
---

## What happened

A laptop pushed its last commit and stayed mid-rebase. The rebase carried the sync's own marker, so
`vault_sync` should have recovered it after twenty minutes
([[2026-10-23-decision-sync-never-rebases-on-a-deadline]]). A day later the guardian still read "vault
stuck mid-rebase for 24 h" and "hook sync failed 4 of its last 5 runs".

## Why

`.git/rebase-merge` held only `autostash`. No `head-name`, no `onto`: the `pull --rebase` was cut off
(most likely by the lid closing) right after it set the work in progress aside and before it replayed
anything. HEAD was still on its branch. Git sees the folder and reports a rebase in progress, but
`git rebase --abort` fails with `could not read '.git/rebase-merge/head-name'`, so the recovery ran on
every pass and failed every time. Nobody could tell why, because the abort threw git's error away.

The first guess was wrong: that any git process on the machine (`pgrep -x git`), or a recycled marker
pid, was blocking the recovery. The machine's own output showed no git running and the recovery being
tried.

## Fixes (`_bin/vault_sync.py`)

- `clear_unstarted_rebase`: when the abort fails, `head-name` is missing and HEAD is on a branch, the
  autostash goes to `git stash list`, where it can be looked at and applied, and the empty state is
  removed. Any other shape is left alone.
- `abort_rebase` keeps git's words (`LAST_ABORT_ERROR`), and they reach the recovery message and the
  sync log.
- Hardening found on the way: `git_running` counts only a git working on the vault (its directory, or
  the vault path in its command line), never `git fsmonitor--daemon`; and the marker's pid counts as
  alive only when the process is older than the marker.

## Unsticking a machine that cannot pull the fix

A machine stuck mid-rebase cannot receive a fix through the sync. Fetch the new file to a temporary
directory and import it ahead of `_bin`:

```
cd ~/Brain && git fetch -q origin && mkdir -p /tmp/vs && git show origin/main:_bin/vault_sync.py > /tmp/vs/vault_sync.py && python3 -c "import sys;sys.path[:0]=['/tmp/vs','_bin'];import vault_sync as V;print(V.abort_rebase(), V.LAST_ABORT_ERROR)" && python3 _bin/vault_sync.py
```

## Lesson

Keep the error a tool gives you, even when you plan to retry: a recovery that fails silently every pass
looks exactly like one that has not run yet.
