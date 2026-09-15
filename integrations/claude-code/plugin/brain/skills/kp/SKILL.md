---
name: kp
description: Reads and files credentials in the user's local KeePass database through kp.py. Use it whenever a secret is needed (API key, token, password, SSH key), whenever the user says they have added one, or whenever a secret shows up in the conversation and has to be filed instead of left lying around.
argument-hint: [what you need or what to file]
allowed-tools: Bash(/usr/bin/python3 __VAULT__/_bin/kp.py:*), Read
---

## Current state

!`/usr/bin/python3 __VAULT__/_bin/kp.py status 2>&1 | head -12 || echo "(kp.py status failed: run it in a terminal)"`

## Rules

The local `.kdbx` is the single home for credentials. No `.env` files with secrets, no copies,
no secrets in vault notes: a note carries `kp://<group>/<entry>#<field>`, written relative to the
agent group, for example `kp://apis/example-service-api-key`.

1. **Never ask for the master password in chat, and never accept it if it is typed there.**
   `kp.py` asks for it outside the conversation and caches it for a limited time. If it appears in
   the conversation, tell the user once that it is now in the transcript and should be changed.
   This applies to the master password only; other secrets may arrive pasted (see below).
2. **A secret is never printed.** By default `kp.py get <entry>` puts it on the clipboard, or
   `--pipe '<command>'` hands it to another process on stdin
   (`kp.py get apis/example-service-api-key --pipe 'python3 script.py'`). `--show` writes it into
   the conversation: only if the user asks for exactly that, and warn.
3. **When creating, generate.** `kp.py put <group/entry> -u <user> --url <url>` generates the
   password inside KeePassXC, so the secret never passes through you. Never put a secret on the
   command line yourself: `ps` and the shell history would see it.
4. **A payload never shares stdin with `--pipe`.** `--pipe` spends the child's stdin on the secret.
   A script that then reads its own request from stdin gets nothing, and the failure looks like a
   real negative result. Pass the payload in a file.
5. **Writing stops when the database is in use.** While KeePassXC has the database open, reads
   keep working and a `put` exits with code 5. That is correct; do not force it. Ask the user to
   save and close KeePassXC, then retry. `kp.py locks` shows the lock evidence. `kp.py locks --clear`
   removes a lock and can lose another client's unsaved changes: only with the user's explicit
   permission, in those words.
6. Every write makes a backup first and checks the database still opens afterwards.

## The normal path: the user files it, you only read

The best route, because **the secret never passes through the conversation**: the user adds the
entry in KeePassXC inside the agent group and tells you its name.

```
kp.py news                     what appeared in the agent group since last time (paths only)
kp.py ls -R                    explore the database (no secrets)
kp.py get <name>               use it; a bare name resolves on its own
kp.py get <name> --pipe 'cmd'  hand it to a process without printing it
```

If the name also exists outside the agent group, the one inside the group wins. If it does not show
up, `kp.py news` tells you what is new; most often the user forgot to save in KeePassXC.

**Tidy the group when it needs it.** When the user says something new is there, check it sits in the
right category and sort it then, without asking each time:

```
kp.py mv <source> <target>     move or rename (rewrites the kp:// references in the vault's notes)
kp.py rmdir <group>            remove a group left empty
```

Layout and criteria: `~/Brain/30-Knowledge/2026-08-20-convention-claude-kdbx-group-layout.md`
(`apis/`, `infra/`, `webs/`, `db/`, `certs/`, `misc/`; kebab-case names that say the service and
which credential). If it is already in the right place, leave it. Afterwards, tell the user what
moved and where.

**Only inside the agent group.** The rest of the database is the user's own hierarchy and is never
touched, not even to tidy it.

## If a secret does get pasted into the chat

It happens, and it is the user's call. Do not lecture. In this order:

1. **File it immediately**, from a heredoc, so it goes through neither argv nor the shell history:

   ```
   python3 ~/Brain/_bin/kp.py put <group/entry> --stdin --exposed -u <user> <<'EOF'
   <the secret>
   EOF
   ```

   `--exposed` records in the entry that it needs rotating, and `kp.py audit` lists every entry in
   that state.
2. **Never repeat it.** Not in a reply, a working file or a command line. From then on it is
   `kp://<group>/<entry>`.
3. **Say once, without insisting**, that the value is in the conversation history and should be
   rotated. If the service has an API for it, offer to rotate it.
4. **Record it in the vault** as a `type: reference` note with the `kp://` reference and what it is
   for, if it will be needed again.

Identifiers that are public by design (an OAuth client id, a public app id) can be filed without
`--exposed`: there is nothing to rotate. Say so in the entry's notes.

## Commands

```
kp.py status                       database path, lock, master cache
kp.py ls -R  /  kp.py search <t>   explore (no secrets)
kp.py get <entry>                  to the clipboard (accepts a bare name)
kp.py get <entry> --info           entry summary, no secret
kp.py get <entry> --pipe 'cmd'     the secret into cmd's stdin
kp.py put <group/entry> -u user    create with a generated password
kp.py put <entry> --stdin          file an existing secret (stdin, never argv)
kp.py put <entry> --exposed        mark it as needing rotation
kp.py audit                        entries marked as exposed
kp.py news                         what appeared in the agent group since last time
kp.py set <entry> -g               rotate the password
kp.py set <entry> -u new           change metadata without touching the password
kp.py ref <entry>                  the kp:// reference to paste into a note
kp.py mv <src> <dst>  /  rmdir     reorganize inside the agent group
kp.py locks [--clear]              lock diagnosis, and clearing with permission
kp.py unlock [--ttl 30m]           arm the master password cache
kp.py lock                         forget the master password
```

`kp.py --help` is authoritative for flags on your copy.

## Where it cannot work

- **Exit code 4**: no master password available and nobody at the machine to type it (a remote or
  unattended session). Ask the user to run `kp.py unlock` at the machine. Never ask for the master
  in the chat.
- **Exit code 6**: no database at the configured path (a cloud sandbox, an unmounted drive, a first
  run not done). Say so; do not improvise another store. The first run sets the path:
  `integrations/first-run/setup.sh`.

Exit codes: `4` master password missing · `5` database open in another client · `6` no database ·
`1` everything else.

## Language

- **Everything written into the vault goes in English**: `title:`, `tags:`, the prose. A verbatim
  quote keeps the language it was said in, with the English alongside. Answer the user in their
  language; the note goes in English, because retrieval is lexical and a note in another language is
  unreachable by search:
  `~/Brain/30-Knowledge/2026-09-08-convention-vault-is-written-in-english.md`.
