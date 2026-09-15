---
id: 2026-08-20-decision-credentials-in-keepass
title: Credentials live in a local KeePass database and notes keep kp:// references
type: decision
area: [security, credentials]
projects: []
tags: [credentials, keepass, kdbx, kp, security, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## What was decided

The memory system stores no secrets of its own. The only home of a credential is a local
KeePass database (a `.kdbx` file), handled only through `_bin/kp.py`, a wrapper around
`keepassxc-cli`. A note keeps a reference and never the value:

```
kp://<group>/<entry>#<field>        e.g.  kp://apis/example-service-api-key#password
```

The field defaults to `password`. The database path is chosen during the first run and can
be changed later; nothing in the repository names it.

Before this, the system only knew how to redact. A credential that reached a note was blanked
and the commit aborted, but nothing said where the secret should go, so it was lost. The
redaction message now points at `kp.py put`.

## Why a local kdbx

- It is a single encrypted file the user owns, readable by KeePassXC on macOS, Linux and
  Windows, and by `keepassxc-cli` from any agent that can run a shell.
- It works offline and with no vendor account, so the machinery keeps working when an agent
  app, an account or a subscription changes.
- Backups are file copies.

## How the agent uses it

- **Read.** `kp.py get <entry>` puts the value on the clipboard, not in the chat.
  `kp.py get <entry> --pipe '<command>'` hands it to another process on stdin. `--show`
  prints it into the conversation and is used only when the user asks for exactly that.
- **Write.** `kp.py put <group/entry> -u <user>` generates the password inside KeePassXC, so
  no secret passes through the conversation. A secret that already exists (a token someone
  gives you) is filed with `--stdin` from a heredoc, never on the command line, where `ps`
  and the shell history would see it.
- **The reference for a note.** `kp.py ref <entry>` prints the `kp://` string to paste.
- **The preferred route for a new secret.** The user adds it in KeePassXC and tells the agent
  its name. The secret never touches the transcript. `kp.py news` lists entries that appeared
  since last time, by path only.

## The master password

It is never typed into the chat, never passed through argv and never written to disk in the
clear. `kp.py` asks for it outside the conversation and caches it for a limited time. If it
does appear in a conversation, say once that it is now in the transcript and should be
rotated.

## Secrets pasted into the chat

There is no safe way to paste a secret: it stays in the history. So the rule accepts it and
leaves a trail:

- file it at once with `kp.py put <entry> --stdin --exposed`;
- `--exposed` marks the entry as needing rotation and `kp.py audit` lists everything marked;
- never repeat the value in a reply, a file or a command line; from then on it is `kp://...`;
- say once, without insisting, that it should be rotated.

## Database integrity

- A write while another client has the database open can lose one side's changes, so `kp.py`
  takes a lock while writing and refuses (exit 5) when the database is locked by a client it
  cannot prove dead.
- Every write makes a backup first and checks afterwards that the database still opens.
- `set` without `-g` never touches the password: changing a username must not rotate a secret.

Exit codes an agent can act on: `4` master password not available, `5` database open in
another client, `6` database not found. `kp.py --help` has the full command list.

## Links

- [[2026-08-20-convention-claude-kdbx-group-layout]]
- [[2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms]]
- [[2026-09-15-decision-first-run-asks-before-connecting-accounts]]
