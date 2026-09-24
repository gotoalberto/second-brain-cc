---
id: 2026-09-23-failure-editing-a-routine-file-while-its-task-is-running
title: "Editing a routine file while its scheduled task runs: the edits land in a rebase autostash and vanish from disk"
type: failure
area: [harness]
projects: []
tags: [tasks, routines, git, autostash, rebase, concurrency, scheduled-tasks]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

# Editing a routine file while its task runs

## Context

A session was extending a routine in `90-Meta/routines/` (a new data collection step and a log
line) when the hourly task of that same id fired. The run goes through the vault sync, which does
`git pull --rebase --autostash`.

## What happened

Four edits made with the Edit tool **silently disappeared from disk**. `grep` found none of the new
sections, `git status` was clean, and the file was back at the last commit, as if the edits had
never been made. The harness had even warned "changed on disk since you last read it", which reads
like a deliberate change by someone else rather than a loss.

They were not lost: the autostash had swallowed them. `.git/rebase-merge/autostash` held a commit
whose diff was exactly the missing work (about a hundred lines in the routine plus the registry
row), and the rebase had stopped half way, leaving a rebase in progress so nothing could be
committed afterwards.

Recovering it:

```
cat .git/rebase-merge/autostash                 # the stash commit sha
git show --stat <sha>                           # confirm it holds the missing work
git show <sha>:<path> > /tmp/f && cp /tmp/f <path>
rm -rf .git/rebase-merge                        # only once HEAD is back on a branch
```

Check `git symbolic-ref -q HEAD` first: on a detached HEAD the fix is different, and removing the
directory would lose the way back.

## The rule

**Do not edit a routine file, or its registry row, while that routine may be running.** Check first:

```
python3 ~/Brain/_bin/tasks.py --list | grep -A4 <routine-id>     # "not yet (...)" is safe
pgrep -fl tasks.py                                               # nothing = nothing in flight
```

A row that says `DUE NOW` or a live `tasks.py` process means wait, or the runner reads the file
mid-edit and gets a half-written procedure. With `every Nh` rows the window is much easier to hit
than with a daily one: a row that runs 24 times a day is in flight 24 times as often.

**Let the edit be committed before running or forcing anything.** An edit that lives only in the
working tree is what the autostash grabs; a committed one is not. In the vault that means the sync
daemon's pass (`_bin/vault_sync.py`), not a hand commit
([[2026-09-22-failure-session-git-commit-in-the-vault-races-vault-sync]]).

## Links

- [[2026-09-21-failure-vault-sync-unmerged-presence-file-silently-stopped-mac-pulls]]: the other
  autostash failure.
- [[2026-09-23-convention-hourly-tasks-use-the-every-nh-column]]: the schedule format that makes
  this window frequent.
