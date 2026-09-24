---
id: 2026-09-22-failure-session-git-commit-in-the-vault-races-vault-sync
title: "A session running git commit in the vault races vault_sync.py: cannot lock ref HEAD, and its files land in the daemon's commit"
type: failure
area: [harness]
projects: []
tags: [vault_sync, gate_write, git, concurrency, flock, hooks]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-24
supersedes: []
---

# A session committing in the vault races vault_sync.py

## What happened

A session wrote a file in the vault and committed it by hand, the obvious way:

```
git add 90-Meta/some-file.json && git commit -m "..."
fatal: cannot lock ref 'HEAD': is at 23087d7... but expected 5a6804e...
```

`git status` then showed the file as already committed, inside a commit the session never made:
the sync daemon's own, next to dozens of unrelated `40-Skills/` files. The message explaining why
the file changed was gone. It happened twice more in the same session, and a `git push` was
rejected half way because another machine had pushed.

## Why

`vault_sync.py` says it in its first line: it is the only process that touches git in the vault;
sessions write files and never commit or push. It serialises on a flock, runs
`reindex, secret scan, add, commit, push` from the scheduler every 10 minutes, and again at the end
of every turn as `vault_sync.py --hook`.

Both sides behaved as written. The daemon took the lock and moved `HEAD` while the session's own
commit was in flight; git refused the ref update, and the daemon's `add` had already swept the
session's files into its commit. **The rule existed only as a docstring.** Nothing enforced it,
and a session doing the most natural thing, committing its own work, broke it without being told.

## The fix

`gate_write_core.bash_rewrites_vault_history()`, wired into the Bash branch of the `PreToolUse`
gate (`gate_write.py`), denies `commit`, `push`, `pull`, `rebase`, `merge`, `cherry-pick`,
`revert`, `reset` and `stash` **when the command is aimed at the vault checkout**, with a message
pointing at the daemon.

Still allowed, because the rule is about the vault's own history and nothing else:

- git in any other repository, including `cd <other repo> && git commit` started from the vault;
- **worktrees of the vault**: a separate checkout with its own HEAD that the daemon never touches;
- `git merge --ff-only` of a branch finished in a worktree, the integration step of `/task`. Its
  commits already exist with their own messages, so nothing can be swept into the daemon's commit;
  if it meets the daemon's lock it fails and is retried;
- reads (`status`, `log`, `diff`, `show`) and `fetch`;
- `git add` on its own: staging is harmless, the daemon commits whatever is staged.

Two details worth keeping:

- The verb has to be git's **subcommand**. Matching the bare word anywhere denied
  `git log -- <this very note>`, a plain read, because the filename contains "commit". So git's
  own options and their values (`-C <dir>`, `-c k=v`, `--git-dir=...`) are skipped and nothing
  after `--` is read.
- `cd` cannot be judged per shell segment the way the protected-folder rule judges writers.
  `cd <vault> && git commit` splits into a segment with the `cd` and no git, and one with git and
  no path. The first version passed its own tests while letting exactly the incident's command
  through. `cd` sets the directory for everything after it, so it is tracked across segments,
  relative paths included.

## How to apply

- **Write the files and stop.** The end-of-turn hook commits them and the daemon pushes and
  retries every 10 minutes. This is the normal path and needs no action.
- Need it on the remote now? Run the daemon's own pass, which takes the lock properly:
  `/usr/bin/python3 ~/Brain/_bin/vault_sync.py`. It also pushes commits the remote does not have.
- A message that has to survive (explaining a decision) belongs in a **note**: the daemon's
  commits describe what moved, never why.
- Writing code? That goes in a worktree anyway, where committing by hand is correct.

## What the daemon's commits say

The messages used to be `vault: N file(s)` plus a time, identical for every pass, with routine
catalogue syncs indistinguishable from a decision. `commit_message()` in `vault_sync.py` now writes
only what it can verify:

| Case | Subject |
|---|---|
| one file | `vault: 30-Knowledge/note.md (<time>)` |
| several | `vault: 30-Knowledge, _bin (3 files) (<time>)` |
| only harness upkeep | `chore: 40-Skills (40 files) (<time>)` |

The body lists every path, so `git show --stat` is not needed. `chore:` covers the skill
catalogue, the harness maintaining itself, so `git log --oneline | grep -v chore:` shows the real
history. One non-routine file in the set makes the whole commit `vault:`, so a decision travelling
next to a catalogue refresh is never hidden. No machine name goes in: the commit is pushed.

It still says only what changed, because the daemon runs unattended with no session and no
model, and a plausible reason it cannot verify would be worse than a plain one.

## Links

- [[2026-09-16-convention-push-vault-changes-immediately]]
- [[2026-09-21-failure-vault-sync-unmerged-presence-file-silently-stopped-mac-pulls]]
