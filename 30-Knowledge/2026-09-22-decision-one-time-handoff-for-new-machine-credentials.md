---
id: 2026-09-22-decision-one-time-handoff-for-new-machine-credentials
title: One-time handoff for a new machine's credentials, without a cloud service
type: decision
area: [security, credentials]
projects: []
tags: [credentials, keepass, kdbx, keyfile, handoff, onboarding, machines, openssl, decision]
status: active
confidence: high
source: agent
provenance: "generalized from onboarding a machine that had no SSH, AirDrop or USB path to the others in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## Problem

A new machine needs what reaches the credential store before it can read anything else: the
KeePass keyfile when the database uses one, the `.kdbx` itself unless it already sits in a
synced folder, and a few settings (where the database lives, the shared and files directories).
The install runbook ([[2026-09-21-runbook-install-on-a-new-machine]], step 5) used to say
"copy the keyfile over SSH". Often there is no SSH between the two machines: a work laptop
behind policy, a server nobody has keyed yet, a machine on another network.

Pasting the keyfile into a chat, a note or an email to yourself is what happens next when
nothing better exists, and each of those keeps a copy forever.

## What was decided

`_bin/handoff.py`, two commands:

```sh
python3 ~/Brain/_bin/handoff.py issue [--to shared|inline|PATH] [--with-db] [--ttl-min 20]   # on a machine that works
python3 ~/Brain/_bin/handoff.py redeem '<TOKEN>' [--force]                                     # on the new machine
```

**issue** builds a small tar in memory: the keyfile `kp.py` is configured with (it refuses one
that is readable by group or others), the `.kdbx` only with `--with-db`, and `settings.json`
with non-secret settings only (the database path as recorded, its place under the shared
directory and under home, the shared directory, the files directory, the KeePass group, the
names of the Google accounts). It encrypts that with a random one-time passphrase and prints
one token plus the exact redeem command.

**redeem** runs from any working directory. It decodes the token, checks expiry, fetches the
ciphertext, checks the MAC, decrypts, checks the archive members by hand, writes the files mode
600 (never over an existing file without `--force`), records them with
`kp.py init --db PATH --keyfile PATH`, deletes the handoff file and prints the next steps:
`kp.py status`, and `kp.py unlock` when the database also has a master password.

## Transports

- **shared**, the default when a shared directory is configured (`BRAIN_SHARED_DIR`, or the
  first run's `multi_machine` step): the ciphertext goes to `<shared>/handoff/handoff-<id>.enc`
  and the token carries the id, the passphrase and the MAC.
- **PATH**: the same, into a directory the user names: a USB stick, any synced folder.
  `redeem --from DIR` finds it when the stick mounts somewhere else on the new machine.
- **inline**, the default without a shared directory: the token carries the ciphertext
  itself, to be pasted once into the new machine's terminal. Refused over 64 KiB, which a
  keyfile never reaches and a database usually does; `--to PATH` is the answer then.

## Security model, stated plainly

- **Time boxed.** The token records when it was issued and its ttl (20 minutes by default, at
  most 60). `redeem` refuses it afterwards. `--ignore-expiry` exists for a slow sync, and is
  refused for a handoff file more than an hour old.
- **Encrypted.** `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt` with a passphrase from
  `secrets.token_urlsafe(24)`. The passphrase reaches openssl through the child's environment
  (`-pass env:SBH_PASS`), never argv, where `ps` would show it. Plaintext goes through pipes and
  never touches the disk.
- **Authenticated before decrypting.** `enc` has no authenticated mode, so an HMAC-SHA256 over
  the ciphertext, keyed from the passphrase and carried in the token, is checked first. A file
  altered in the shared folder is refused before openssl sees it.
- **Single use through a file.** A successful redeem deletes the handoff file, and every issue
  deletes handoff files older than an hour. Nothing accumulates in the shared folder.
- **An inline token is as sensitive as the keyfile.** It is the payload. It expires, but a copy
  kept in a chat or a ticket is still a copy of the keyfile for its first minutes, and a record
  of it after. Paste it once, into a terminal, and nowhere else.
- **Redeem trusts nothing in the archive.** Only flat regular files with the expected names
  pass: no absolute paths, no `..`, no links, no directories, no extra members. This is done by
  hand instead of `tarfile`'s extraction filter, which Python 3.9 does not have, and nothing is
  extracted to disk at all.
- **Never the master password.** The tool does not carry it, ask for it or handle it. The human
  types it where `kp.py` asks, on the new machine, as with any other secret prompt. Refresh
  tokens and other secrets are not carried either: they live in the database.

## Why no cloud service

A time limited link to a cloud file store or a paste service would work over nothing but internet, and was
the obvious alternative. It was not taken:

- It would add an account, credentials and a dependency the rest of the harness does not have.
  Everything here is local files plus a folder the user already syncs.
- Such a store cannot delete on first read without compute in front of it, so "one time"
  would mean only "time limited". A file in the user's own shared folder can be deleted by the
  redeem itself.
- The inline transport already covers the case with no shared folder at all, at the cost of
  one long paste.

`age` would have been a better encryption tool, and was not chosen because `openssl` is already
on every macOS and Linux machine, including the brand new one with the least tooling.

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]: step 5 uses this as the normal path
- [[2026-08-20-decision-credentials-in-keepass]]: what the keyfile and the database are for
