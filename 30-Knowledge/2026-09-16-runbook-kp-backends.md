---
id: 2026-09-16-runbook-kp-backends
title: Runbook for the two KeePass backends of kp.py (keepassxc-cli and kpcli)
type: runbook
area: [security, credentials]
projects: []
tags: [keepass, kp, kpcli, keepassxc, credentials, kdbx, file-kdbx, perl, backend, keyfile, portability]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

# The two KeePass backends

`kp.py` is the only path to the credentials, and it speaks one vocabulary: `keepassxc-cli`'s.
Which client actually answers depends on the machine, and `_bin/kp_backend.py` is the only place
that knows the difference.

| backend | what runs | how it reads the kdbx |
|---|---|---|
| `keepassxc` | `keepassxc-cli` | the reference; argument lists pass through untouched |
| `kpcli` | `_bin/kp_kdbx.pl` on Perl's `File::KDBX` | kp_backend translates each call |

`BRAIN_KP_BACKEND=keepassxc|kpcli` forces one. Without it `keepassxc-cli` is preferred, and the
kpcli backend is picked only when `kp_kdbx.pl` is found on `PATH` and `keepassxc-cli` is not. The
helper sitting in the checkout is not a signal on its own: that made kpcli win on every machine
without KeePassXC, including a bare CI checkout. A forced `kpcli` that finds no `kp_kdbx.pl`
on `PATH` runs the checkout's own `_bin/kp_kdbx.pl`, so nothing has to be put on `PATH` by hand.
`kp.py status` prints the live backend on its
`cli` line.

## Why the kpcli backend does not drive kpcli

`kpcli` is an interactive shell. Its `find` asks a question on the terminal that piped stdin
never answers, its `ls` lists groups rather than the entries inside them, and its replies carry
colour codes and banners. What it brings to a machine is its dependency, `File::KDBX`, which
reads and writes KDBX 4 directly. `kp_kdbx.pl` binds that module and prints the shapes kp.py
already parses, so no caller in kp.py changed.

## Installing the kpcli backend

```bash
curl -sL https://cpanmin.us -o /tmp/cpanm
perl /tmp/cpanm --local-lib=~/perl5 --notest File::KDBX
BRAIN_KP_BACKEND=kpcli python3 ~/Brain/_bin/kp.py status
```

`kp_kdbx.pl` loads `~/perl5/lib/perl5`, or `BRAIN_KP_PERL5LIB` when set, through Perl's `lib`
pragma so the architecture directory comes with it: that is where the compiled dependencies
(`CryptX`, `Crypt::Argon2`) are installed, and a bare `unshift @INC` misses them.

On macOS with only the Command Line Tools, `Crypt::Argon2` can fail with `'EXTERN.h' file not
found` followed by `unsupported option '-msse3'`. The second error is caused by the first: the
SSE probe wrongly succeeds when the headers are missing. Point the build at the SDK's Perl
headers and both go away:

```bash
SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
PERLV=$(perl -e 'printf "%vd", $^V' | cut -d. -f1,2)
SDKROOT="$SDK" CPATH="$SDK/System/Library/Perl/$PERLV/darwin-thread-multi-2level/CORE" \
  perl /tmp/cpanm --local-lib=~/perl5 --notest Crypt::Argon2 File::KDBX
```

## Key files and keyfile-only stores

Both backends take a key file. `kp.py` adds `-k <path>` to every call when one is configured
(`kp.py init --keyfile PATH`, or `BRAIN_KP_KEYFILE`). keepassxc-cli reads it from its argv. For
the kpcli backend `kp_backend.build()` strips `-k <path>` and passes the path to the helper as
`BRAIN_KP_KEYFILE` in its environment, set even when empty so a value inherited from the caller
cannot leak into a call that did not ask for it. A path is not a secret; the master still goes
through a mode 0600 file, because argv and the environment are visible to `ps`.

`kp_kdbx.pl` then builds the `File::KDBX` key: the master and the key file together, or the key
file alone when there is no master. An empty password next to a key file is a different key from
the key file alone, and it fails the header check, so the empty password is dropped rather than
passed. keepassxc-cli behaves the same way, which is why `--no-password` exists.

A keyfile-only store has no master at all, for a machine where nobody can type one:

```bash
python3 ~/Brain/_bin/kp.py init --db ~/secrets/agent.kdbx --keyfile ~/secrets/agent.key --create --no-password
```

With a key file configured, kp.py opens the store once with `--no-password`. When that works it
never asks for a master, never caches one, and `kp.py status` says the keyfile is the whole key;
`unlock` has nothing to do. When it fails the store also has a password and the normal master path
runs. `BRAIN_KP_NO_PASSWORD=1` skips the probe on a machine where the answer is known. A store
created by keepassxc-cli opens on the kpcli backend and the other way round; both write KDBX 4.

## What the kpcli backend does not do

It refuses with the reason instead of improvising, because a wrong guess corrupts the credential
store: anything outside `ls`, `search`, `show`, `mkdir`, `add`, `edit`, `mv`, `rm`, `rmdir`
(attachments, for one); the clipboard (use `--pipe` or `--show`); `kp.py locks`; and
`kp.py init --create`. Run those on a machine with `keepassxc-cli`.

`mv`, `rm` and `rmdir` were on that list until 2026-09-22. In `kp_kdbx.pl`, `mv` only relocates
the entry and `kp.py cmd_mv` renames it with a follow-up `edit -t` (translated to `--title`); `rm`
detaches the entry with no recycle bin; `rmdir` checks again that the group is empty, because on a
shared store the check in `kp.py` and the delete can be minutes apart. `kp.py rm` itself asks first:
[[2026-09-22-decision-kp-rm-refuses-without-yes-and-reports-refs]].

## Things that must stay fixed

- **The master never reaches argv or the environment.** keepassxc-cli gets it on stdin. The kpcli
  helper cannot, because stdin is where a new secret arrives, so it goes into a 0600 file that is
  overwritten and removed right after the call.
- **A new secret is sent twice and must be stored once.** With `-p` kp.py writes the secret and its
  confirmation, which keepassxc-cli expects. `kp_backend.split_confirmation()` collapses the pair
  for the kpcli helper, and only when both halves are identical, so a secret with newlines in it
  survives. See [[2026-09-17-failure-kpcli-backend-stored-every-secret-twice]].
- **A write saves with the key it opened with.** `kp_kdbx.pl` saves with the composite key, never
  the bare master: on a keyfile-only store the master is "" and saving with it re-keys the store
  under an empty password. `kp.py` also refuses to put back any file that opens without its key
  (`keyed_as_expected`). See [[2026-09-22-failure-kpcli-write-saved-store-without-keyfile]].
- **Nothing on stdin ahead of the call on a keyfile-only store.** Not even a newline: keepassxc-cli
  reads it as the next thing it asks for, which on `add -p` is the new secret.

## Checking a change

`_bin/kp_backend_test.py` covers routing, translation and the key file handoff with fakes.
`_bin/kp_kdbx_pl_test.py` runs the helper against real `File::KDBX` databases, keyfile-only and
password plus key file included, when the module is installed (`PERL5LIB` pointing at the local
lib), and skips otherwise. `_bin/kp_test.py` runs a keyfile-only store end to end against the real
keepassxc-cli when it is installed. After any change to the backend, also read a real store before
believing it: `kp.py ls -R`, `kp.py get <entry> --pipe 'wc -c'`.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]: the credential model this serves; the kdbx is the
  only home of a credential and kp.py the only path to it.
- [[2026-09-17-failure-kp-py-deleted-cache-on-a-transient-read-error]]: why only a rejected key
  discards the cached master.
