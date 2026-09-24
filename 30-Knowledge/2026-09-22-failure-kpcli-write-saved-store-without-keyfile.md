---
id: 2026-09-22-failure-kpcli-write-saved-store-without-keyfile
title: A kpcli backend write saved the credential store without its key file
type: failure
area: [security, credentials]
projects: []
tags: [keepass, kpcli, file-kdbx, credentials, kp, keyfile, silent-corruption, security]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

# A kpcli backend write saved the credential store without its key file

## What happened

A keyfile-only store (no master password) was shared between several machines. One `kp.py put`
from the only machine on the kpcli backend (File::KDBX through `kp_kdbx.pl`) left the store
encrypted with an **empty password and no key file**. Every other machine then failed with
"invalid credentials (HMAC mismatch)". The agent on one of them blamed its own key file and asked
the user to fix it. The key file was fine: its hash was identical on every machine and nobody had
touched it in days.

For as long as it lasted, the store opened for anyone who could read the file.

## Cause

Three faults, each enough on its own:

1. The helper loaded the store with the composite key but saved it with the bare master. On a
   keyfile-only store the master is `""`, so saving re-keyed the store under an empty password.
   Key file support had been added to the load side only.
2. `cmd_put` created the entry's group (a `mkdir`, which re-saves the file even when the group
   exists) BEFORE taking the write lock. So the broken file reached the store without the lock and
   without the verify-or-restore that follows every write. The `add` after it failed on the broken
   file, was reported as a wrong master, and the automatic restore never ran.
3. The guard in front of every overwrite checked what the file was (KDBX magic) and where it came
   from (our working copy or backup), but not how it was keyed.

## Fix

- `kp_kdbx.pl` saves with the key it opened with. `kp_backend_test.py` checks that every save in
  the helper uses the composite key, and `kp_kdbx_pl_test.py` checks, where File::KDBX is
  installed, that after a write a keyfile-only store still opens with the key file alone and does
  NOT open with an empty password.
- `kp.py keyed_as_expected()`, called from `write_over_db` before anything overwrites the store:
  refuses a file that opens with an empty password and no key file, or, on a keyfile-only store,
  one that no longer opens with the key file alone.
- `cmd_put` runs `ensure_group` inside the write lock.
- `keyfile_only()`: when the key file fails, it checks whether the store opens with no key at all
  and says so ("the keyfile here is not the problem"), instead of falling through to asking for a
  master the store never had.
- The kp skill's section on "cannot open the database" now leads with "the store was written with
  the wrong key" and gives the re-key procedure.

## Recovery

The broken file held everything from the newest good backup plus the new entry, so nothing was
lost. On a machine with keepassxc-cli, with nothing else writing: took a copy, ran
`keepassxc-cli db-edit --set-key-file <keyfile> --unset-password` on it, checked it opens with
`-k <keyfile> --no-password` and not with an empty password, compared the entry list against the
backup (one entry more, as expected), checked the store had not changed meanwhile, and put it back.
The local `kp-backups/` on each writing machine is the real fallback if the content itself is lost.

## Rules that come out of it

- "Cannot open" on more than one machine points at the store. The key file is rarely the cause. Compare key
  file hashes (first 16 hex characters only) before blaming a key.
- Never generate a new key file to "fix" a store that will not open.
- Anything that can re-save the store is a write: it goes inside the write lock.

## Links

- [[2026-09-16-runbook-kp-backends]]
- [[2026-09-17-failure-kpcli-backend-stored-every-secret-twice]]
- [[2026-09-22-decision-kp-rm-refuses-without-yes-and-reports-refs]]
