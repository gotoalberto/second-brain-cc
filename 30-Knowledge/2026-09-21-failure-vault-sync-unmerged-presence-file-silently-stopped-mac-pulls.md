---
id: 2026-09-21-failure-vault-sync-unmerged-presence-file-silently-stopped-mac-pulls
title: Vault sync and unmerged files left by an autostash pull
type: failure
area: [harness]
projects: []
tags: [vault_sync, git, sync, autostash, unmerged]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## What happened

On one machine `git pull --rebase --autostash` exited 0, but re-applying the autostash conflicted on a
file that had been edited locally and deleted on the remote. The file was left unmerged and the
autostash entry stayed in the stash list. Every later pull then failed with "Pulling is not possible
because you have unmerged files", which `vault_sync.py` logged as a plain pull failure. The machine
silently stopped receiving the vault for hours, until someone ran `git pull` by hand. In that vault
the file was a machine-generated one; any unmerged file stalls the sync the same way.

## The fix

In `_bin/vault_sync.py`:

- `settle_unmerged()` runs before the pull and after it. Files under `EPHEMERAL_PREFIXES` (paths the
  machinery regenerates on its own) are settled from the remote: the `HEAD` copy, or removed when
  `HEAD` deleted them, and the leftover autostash entry is dropped when those were the only
  conflicts. In this vault the list is empty, because nothing is committed periodically by a machine
  (presence, leases and the machine registry live outside git).
- Any other unmerged file stops the pass loudly: a `stopped-unmerged` log event, a
  `00-Inbox/CONFLICT-sync-*.md` note naming the files, and exit 1.
- In the same change: a pull that brings changes under `integrations/claude-code/plugin/` refreshes
  the plugin in the same pass, a provably stale `.git/index.lock` (no git process running and older
  than two minutes) is removed, a lock failure is no longer reported as a conflict, and scheduled
  passes start after a random wait of up to `BRAIN_SYNC_JITTER_S` seconds (30 by default) so machines
  on the same interval stop colliding.

Tests: `_bin/vault_sync_test.py`, against real temporary git repositories.

## Lesson

A command that exits 0 can still leave the repository in a state that breaks every later run. A sync
that believes it works and does not is worse than one that stops and says so.

## Links

- [[2026-09-15-runbook-brain-guardian]]
