---
id: 2026-09-26-runbook-unwedge-the-vault-sync-after-a-stuck-rebase
title: Unwedging the vault sync after a stuck rebase
type: runbook
area: [harness]
projects: []
tags: [vault_sync, git, rebase, conflicts, autostash, gate_write, runbook]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-26
supersedes: []
---

# Unwedging the vault sync after a stuck rebase

## What wedges it

`_bin/vault_sync.py` aborts a conflicted `pull --rebase` and writes a `00-Inbox/CONFLICT-sync-*.md`
notice. When the abort itself does not complete (an `index.lock`, or another process committing while
the rebase is open), the checkout stays mid-rebase and every later pass refuses on arrival, by
design. Nothing is pushed, and beyond the guardian's failing sync line nothing warns, so a machine can
sit like that for days with local commits piling up on one side and remote ones on the other.

A lighter variant needs no surgery on the checkout: the sync aborts cleanly every time but the same
real conflict comes back on every pass, one more CONFLICT notice each time.

The usual culprits are files that several machines write at the same time: append-only logs in
project notes, and machine-generated files such as the per-machine skill index under `40-Skills/`.

`vault_sync.settle_rebase()` covers the narrow case where the only unmerged paths are ones the
machinery regenerates (`EPHEMERAL_PREFIXES`): it keeps the remote's copy, continues or skips, and
repeats until the rebase ends. In this vault that list is empty, so the function is inert and any
stuck rebase comes here.

## Repair

1. **Pause the sync daemon** so it cannot race the repair: `systemctl --user stop
   second-brain-sync.timer` on Linux, `launchctl bootout gui/$(id -u)/com.secondbrain.sync` on macOS.
   In the lighter variant (clean aborts, no rebase in progress) this step can be skipped: a commit
   the daemon makes meanwhile rebases on top of the merge afterwards.
2. **Tag what exists** before touching anything: the branch tip and, when a commit was made in the
   middle of the rebase, that commit too. It costs nothing and makes every later step reversible.
3. **Do the history surgery in a scratch worktree**:
   `git worktree add /tmp/vault-merge --detach origin/main`. The write gate blocks `commit`, `push`,
   `pull`, `rebase`, `merge`, `reset` and `stash` aimed at the vault checkout and exempts worktrees,
   so a worktree is the sanctioned place for this.
4. **Merge rather than replay.** `git merge <local main tip>` resolves the whole divergence in one
   pass, where a rebase would replay every local commit. For each conflicted file:
   - generated files (the skill index, anything the machinery rewrites) take the remote side;
   - append-only logs written by two machines take a union of both sides. Get the three stages with
     `git show :1:F > base`, `git show :2:F > ours`, `git show :3:F > theirs`, then
     `git merge-file --union -p ours base theirs > F`;
   - after a union, read the result: a union does not catch a table row or a frontmatter block that
     now appears twice.
5. **Push from the worktree**: `git push origin HEAD:main`. Local `main` is now an ancestor of the
   remote, so the checkout only needs a fast forward.
6. **Abort the stuck rebase in the checkout** (`git rebase --abort`). This is the one step the gate
   blocks that no worktree can do for you, because the rebase state lives in the checkout's `.git`.
   Ask the user before overriding the gate, and keep the daemon paused.
7. **The autostash comes back with the abort.** A genuine uncommitted edit in it will conflict with
   the merged file: lift the added block out, `git checkout -- F`, let the sync pull, then put the
   block back in its place.
8. Run `python3 _bin/vault_sync.py` until it prints a commit and `push OK`. For each unmerged stop on
   a generated file, take the remote side. A `database is locked` crash in the reindex is another
   session indexing; run it again.
9. **Re-enable the daemon** and confirm it runs (`systemctl --user status second-brain-sync.timer`,
   or `launchctl print gui/$(id -u)/com.secondbrain.sync`).

## Leftovers

- **CONFLICT notices.** One is written per failed pass, so a conflict left open overnight leaves
  dozens. Once the conflict is resolved, archive them (set `status: archived` and move them out of
  `00-Inbox/`) so they drop out of retrieval.
- **Autostash entries.** `settle_unmerged()` drops the autostash only when every conflict was an
  ephemeral file, so each real conflict can leave one more entry in `git stash list`. Before clearing
  them, check each one's content made it: take the lines it adds with
  `git diff -U0 <stash>^1 <stash>` and grep the current file for a distinctive phrase of each (log
  entries often come back with a slightly different prefix, so search a phrase rather than the whole
  line). Write the stash hashes down somewhere durable, since they stay recoverable with
  `git stash apply <hash>` until garbage collection. Then clear them while holding the daemon's own
  lock (`brainlib.flock` on `_index/.gitlock`), re-checking that the list did not change, with
  `git stash clear`.
- **The guardian's sync finding** stays failing until enough successful passes age out the failed
  ones.

## Links

- [[2026-09-21-failure-vault-sync-unmerged-presence-file-silently-stopped-mac-pulls]]
- [[2026-09-22-failure-session-git-commit-in-the-vault-races-vault-sync]]
- [[2026-09-15-runbook-brain-guardian]]
