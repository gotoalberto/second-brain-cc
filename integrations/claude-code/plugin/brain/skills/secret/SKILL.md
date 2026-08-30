---
name: secret
description: Read and store credentials with the 1Password CLI. Use whenever a task needs a secret (API key, token, password) or a secret shows up and must be filed instead of left in plain text.
---

Credentials for the brain live in **1Password**, read through its CLI (`op`). The vault stores
**no secrets** — a note carries only a reference:

```
op://<vault>/<item>/<field>        e.g.  op://Private/GitHub/token
```

Helper: `python3 ~/Brain/_bin/secret.py`.

## Rules

1. **A secret is never printed.** By default it goes to the clipboard, or by stdin into another
   process. `--show` writes it into the conversation: use it only if the user asks, and warn.
2. **Never write a secret into a note.** The note gets the `op://...` reference; the value stays
   in 1Password.
3. **When a secret is pasted into the chat**, file it at once and treat it as exposed: it should
   be rotated because it is now in the transcript.

## Commands

```
secret.py check                                  is op installed and signed in?
secret.py get op://Vault/Item/field              use it (to the clipboard by default)
secret.py get op://Vault/Item/field --pipe 'cmd' hand it to a process without printing it
secret.py get op://Vault/Item/field --show       print it (only if asked; warns)
secret.py put Vault/Item -f token=... -f user=…  create/overwrite an item
secret.py ref Vault/Item/field                   the op:// reference to paste into a note
```

## Setup (once)

Install the 1Password CLI (https://developer.1password.com/docs/cli/) and either run
`op signin` or turn on the desktop-app integration. Then `secret.py check` should pass.

Exit codes: `4` not signed in · `6` op not installed · `1` everything else.
