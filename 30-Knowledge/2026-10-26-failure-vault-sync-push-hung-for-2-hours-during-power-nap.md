---
id: 2026-10-26-failure-vault-sync-push-hung-for-2-hours-during-power-nap
title: "vault_sync push hung for two hours when a laptop slept mid-push; network git calls are now bounded"
type: failure
area: [harness]
projects: []
tags: [sync, vault-sync, git-push, ssh, timeout, power-nap, laptop]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-26
supersedes: []
---

## What happened

A session start showed "1 commit not pushed, oldest 6 h". From the power log and the vault's logs:

- In the night a Power Nap dark wake, a few seconds long, let a sync pass commit and start `git push`.
- The laptop went back to sleep mid-push. The SSH connection hung, with no keepalive to notice it was
  dead.
- Two hours later the subprocess timeout fired. The sync printed only `push failed: error`.
- In the morning, with the lid open, the next pass pushed fine.

Nothing was lost; the commit sat unpushed for hours and the sync gave no hint why.

## Fix (`_bin/vault_sync.py`)

- `NET_TIMEOUT_S = 90` and `SSH_OPTS` (`BatchMode=yes`, `ConnectTimeout=15`, `ServerAliveInterval=15`,
  `ServerAliveCountMax=2`).
- `ssh_command(configured)` keeps a repository's own `core.sshCommand` (a deploy key, say) and appends
  `SSH_OPTS`.
- `net_git(*args)` runs `pull --rebase --autostash` and `push` with that ssh command and the 90 s
  timeout.
- `net_failure(code, out, err)` turns the bare `error` into "no answer in 90 s (asleep, offline, or the
  SSH agent is locked); the next pass retries", and the push failure is logged.

## Alternatives considered

- Editing `~/.ssh/config`: rejected, what the vault needs lives inside the vault.
- `GIT_SSH_COMMAND`: rejected, it would override a repository level `core.sshCommand`.

## Limits that remain

An SSH agent that locks during dark wakes (a password manager's agent, for one) still makes overnight
pushes fail. They now fail fast and retry on the next pass. A file based deploy key for the vault,
set in the vault's own `core.sshCommand`, removes the dependency.

## Diagnostics worth reusing

`pmset -g log | grep DarkWake` lists Power Nap wakes on macOS and explains overnight sync gaps.

## Related

- [[2026-10-23-decision-sync-never-rebases-on-a-deadline]]
- [[2026-11-07-failure-stuck-rebase-recovery-blocked-by-any-git-on-the-mac]]
