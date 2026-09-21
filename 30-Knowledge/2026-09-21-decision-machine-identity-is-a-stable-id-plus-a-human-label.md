---
id: 2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label
title: Machine identity is a stable hardware id plus a changeable human label
type: decision
area: [harness]
projects: []
tags: [machines, identity, tasks, locks, claims, presence, macos, linux, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## What was decided

A machine's identity is **two values, not one**:

- **A stable id** derived from the hardware: `IOPlatformUUID` on macOS, `/etc/machine-id` (or
  the DMI product UUID) on Linux. This is the identity, and it survives a hostname change.
- **A human label**, the short hostname, which may change freely and exists to be read.

The file-safe key written into claims, presence and state is `<label>-<first 8 hex of the id>`
(`_bin/machine_identity.py`). Only that short fragment is ever written; the full id is read,
reduced and discarded.

**A scheduled task's `machine` cell matches either the id or the label**, case-insensitively,
plus `*` for every machine. People write labels by hand; code that recorded an id keeps
working. The task runner and the guardian's due-ness rule both ask
`machine_identity.machine_is_mine()` (`guardian_core/domain.py`, `machine_matches`), so they
cannot disagree about who owns a row.

## Alternatives considered

- **Hostname only.** Readable, but it moves. One laptop renamed twice shows up as three
  machines, and the inventory can no longer answer "how many machines is this installed on".
- **Hardware id only.** Stable, but nobody can read it or type it into a table they maintain.
- **Two separate implementations** (one in the task runner, one in the shared library). They
  disagree on the same machine, and on Linux they only agree by accident when both fall back
  to the hostname. There is one implementation.

## Consequences

- **"Is this mine?" accepts every form a machine has used.** The current key, the raw id, the
  bare label and the keys it wrote under earlier hostnames. Locks, leases and claims written
  before a rename carry the old form; a machine that stops recognising its own lock either
  blocks itself for ever or clears somebody else's, silently in both directions.
- **Any change to identity is checked against every consumer**: the write gate, the task runner
  and the guardian's due-ness rule, the credential store lock, leases, presence and claims. Two
  components reaching different answers about who owns a task is the failure to avoid.
- **Forcing a task is not checked against its owner.** `tasks.py --force <id>` runs the row on
  this machine whatever its `machine` cell says, so check `tasks.py --list` first; the list
  marks the rows this machine owns.
- **The machine registry (`_bin/machines.py`) records the Claude account** each machine is signed
  into, and collapses aliases of the same machine when listing. Every machine registers itself:
  the first run at its end, and the guardian's scheduled repair once a day. Duplicate entries are reported,
  never merged automatically: an agent does not quietly rewrite the machine inventory.
- A bare hostname still matches, for artefacts written by older code. The exposure is two
  machines sharing a hostname, which the 8 hex suffix exists to separate.
- Commit messages and other pushed text never carry a machine key.

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-21-decision-supported-environments-macos-and-linux]]
- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
