---
id: 2026-08-20-convention-claude-kdbx-group-layout
title: Layout of the agent group in the KeePass database
type: convention
area: [security, credentials]
projects: []
tags: [credentials, keepass, kdbx, layout, naming, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Everything an agent writes into the KeePass database lands inside one group reserved for
agents. A path that names its own group hangs off that group and never replaces it. What the
user saved by hand, in the rest of the database, is their own hierarchy and is never touched,
not even to tidy it. `kp.py mv` refuses to move anything from outside the agent group and
redirects a destination that points outside back in.

Keeping agent writes in one group means they can be audited, moved or removed as a whole
without risk to anything else.

References in notes are written relative to the agent group: `kp://apis/<service>-api-key`.

## The scheme

```
<agent group>/
  apis/     tokens and API keys for services
  infra/    machines, routers, VPN, SSH
  webs/     site accounts and admin panels
  db/       databases and connection strings
  certs/    certificates and private keys
  misc/     whatever does not fit anywhere yet
```

Entry names are lowercase kebab-case with no spaces or accents, and they say the service and
which credential it is: `example-service-api-key`, `router-admin`, `dns-provider-api-token`.
One entry per credential. The entry's notes say what it is for and who uses it, never another
entry's secret.

## When to reorganize

When the user says they added something to the agent group, check it is in the right place
and sort it then, without asking each time:

- a loose entry at the root of the group goes into its category;
- a name that says nothing (`new`, `token`, `temp`, `test`) is renamed;
- a service with several loose credentials is grouped by name prefix, not by subgroup, until
  there are more than three;
- `misc/` with more than six entries is a reason to propose a new category;
- a group left empty after a move is removed with `kp.py rmdir <group>`.

If a name is already clear and in the right place, leave it. Every move changes the path the
user remembers.

## What to remember when moving

A moved entry orphans the `kp://` references in the notes. `kp.py mv` rewrites them itself and
says which notes it touched. An entry moved outside `kp.py` (from KeePassXC, say) needs its
references fixed by hand.

After reorganizing, tell the user what moved and where.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
