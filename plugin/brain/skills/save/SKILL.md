---
name: save
description: Saves what this session learned into the Brain vault — decisions, conventions, project state. Use it before closing any session that changed code or made decisions, and whenever the user asks you to save or remember something.
argument-hint: [what to save, optional]
---

Invoke the `librarian` subagent so it writes to the vault whatever deserves to outlive
this session.

Pass it, in the delegation message:
- **What was done**: actual changes, with file paths.
- **What was decided and why**: above all, the alternatives that were discarded and the
  reason. That is what the code does not hold, and what is worth most three months from
  now.
- **What was learned**: conventions discovered, traps found, commands that work in this
  project.
- **What is still open** and what is blocking it.
- The user's specific instruction, if any: «$ARGUMENTS».

Rules:
- Do not invent content as filler. If there genuinely is nothing memorable, have the
  librarian say so and write nothing.
- No credentials in notes.
- When done, say in two lines which notes were created or updated, with their paths.

If the librarian wrote anything, sync the vault instead of waiting for the daemon:

```bash
python3 ~/Brain/_bin/vault_sync.py
```

The daemon runs every 10 minutes, so without this whatever was just saved lives only on
disk for that long. It is the same script the daemon runs — serialised with flock and
with `pull --rebase` — so calling it by hand causes no races and no duplicate commits.
Do not call it if the librarian wrote nothing: there is nothing to commit and it only
adds noise to the log.
