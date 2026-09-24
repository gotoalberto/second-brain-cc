---
id: 2026-09-22-decision-kp-rm-refuses-without-yes-and-reports-refs
title: kp.py rm refuses without --yes and reports which vault notes reference the entry first
type: decision
area: [security, credentials]
projects: []
tags: [keepass, kp, kpcli, credentials, deletion, safety, kdbx]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

# kp.py rm asks first and names the notes that point at the entry

## Context

`rm` sat in `kp.py`'s set of mutating subcommand names, which made it look implemented when
searching the code, but there was no `rm` subcommand at all. The kpcli backend could not delete,
move or drop a group either: `kp_backend.translate()` refused `mv`, `rm` and `rmdir`, and
`kp_kdbx.pl` had no such operations. On a machine with only the kpcli backend there was no way to
tidy the agent group. Both gaps were closed together. The backend split is in
[[2026-09-16-runbook-kp-backends]].

## Decision

`kp.py rm <entry>` deletes nothing unless `--yes` is passed, and before deleting it prints every
vault note whose `kp://` reference points at the entry (`find_refs()`). After the delete it names
those notes again as now broken. In `kp_kdbx.pl` the delete detaches the entry with no recycle bin.
Like every other command that changes the store, it only works inside the agent group.

## Alternatives rejected

- **Delete silently, like a file `rm`.** A KeePass entry is not a file. If it is the only copy of a
  credential nobody wrote down, deleting it destroys the access itself.
- **Soft delete into a trash group or KeePass's own recycle bin.** A second, half hidden place that
  may or may not hold the entry makes "is it actually gone?" unanswerable.
- **Repoint the references, the way `mv` does with `rewrite_refs`.** A move has a new path to point
  at; a delete has nothing. So `find_refs()` only reports, and it reports before the delete, because
  afterwards the note is the only record left of what the credential was for.

The backup taken before every write and the verify-or-restore after it apply to `rm` unchanged, so
a mistaken delete stays recoverable from `<STATE>/kp-backups/` until those rotate out. That is a
second layer. `--yes` is still required.

## Links

- [[2026-09-16-runbook-kp-backends]]
- [[2026-09-22-failure-kpcli-write-saved-store-without-keyfile]]
