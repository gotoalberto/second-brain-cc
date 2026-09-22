---
id: 2026-09-12-reference-tool-and-service-catalogue
title: Tool and service catalogue, per machine
type: reference
area: [meta, infra]
projects: []
tags: [catalogue, tools, apis, credentials, mcp, machines, reference]
status: active
confidence: medium
source: agent
provenance: "template generalized from a working vault; every row below is a placeholder to replace with your own"
updated: 2026-09-22
supersedes: []
---

## Why this note exists

A capability gets treated as missing when it was already there: an API assumed not to cover a
chain it covers, a plan upgrade assumed necessary when the current key already answers. Each of
those costs a detour, or a purchase nobody needed. **Read this note before saying a capability
is missing, or before asking the user to buy or grant one.**

This is the register. Per service notes carry the detail (limits, dead endpoints, traps); this
note carries the routing: which tool answers which question, on which machine.

The rows below are placeholders. Replace them with what you actually have, one row per verified
capability, with the date it was verified.

## Per machine

What each machine can reach. Machine identities live in `90-Meta/machines/` (written by
`machines.py`, never by hand); the `## This machine` block at session start is the live part
(tools on PATH, Chrome, Remote Control, CLI login). This section is the static side.

### workstation-0f0f0f0f (macOS)

| Capability | State | Verified |
|---|---|---|
| Chrome with the Claude extension, paired | the user's logged-in sessions live here | YYYY-MM-DD |
| `<tool>` on PATH | present | YYYY-MM-DD |
| `<tool>` on PATH | absent, install with `<command>` | YYYY-MM-DD |

### server-0a1b2c3d (Linux)

| Capability | State | Verified |
|---|---|---|
| Chrome under the X desktop unit | `vnc-desktop` enabled at boot | YYYY-MM-DD |
| `<tool>` on PATH | present | YYYY-MM-DD |

## APIs and keys

Every key is in the local kdbx (`kp.py`, see [[2026-08-20-convention-claude-kdbx-group-layout]]).
This table names the entry by reference; the secret itself never appears in a note.

| Question it answers | Service | kdbx entry | Reference note | Verified |
|---|---|---|---|---|
| `<a class of question>` | `<service>` | `apis/<service>-api-key` | `<note id>` | YYYY-MM-DD |
| `<a class of question>` | `<service>` | `apis/<service>-api-key` | `<note id>` | YYYY-MM-DD |

A key is used through stdin, never on `argv`, where it would sit in `ps` and the shell history:

```
python3 ~/Brain/_bin/kp.py get apis/<service>-api-key --pipe '/path/to/script.sh <args>'
```

## MCP servers

| Server | Scope and auth | What it is for | Machines | Verified |
|---|---|---|---|---|
| `<server>` | user scope, `<auth>` | `<what it answers>` | `<machines>` | YYYY-MM-DD |

Only mechanisms you control: scripts with keys in the kdbx, generic or self-hosted MCP servers
([[2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms]]).

## Keeping this current

**When the user grants a new tool, key, connector or MCP server, verify it with a real call,
then revise this note in the same session.** Not later, not in a tidy-up.

1. **Verify it works** with the smallest real call that proves the capability, not only that
   the key authenticates. A key that answers a health check and fails on every useful endpoint
   is worth less than no key.
2. **Add it to the right section above**, and to the routing if it answers a class of question
   better than what is already listed.
3. **Write or update its own reference note** with the traps: plan limits, quota errors, dead
   endpoints, how the key is passed without touching `argv`.

The same applies in reverse: a key that dies, a limit that bites, or a capability found to exist
after it was assumed missing goes in here on the day it is found. A register that is only right on
the day it was written is worse than none, because it will be believed.

## Links

- [[2026-09-21-reference-where-claude-in-chrome-is-available]]
- [[2026-08-20-decision-credentials-in-keepass]]
- [[2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label]]
