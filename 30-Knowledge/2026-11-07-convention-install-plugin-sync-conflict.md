---
id: 2026-11-07-convention-install-plugin-sync-conflict
title: "install_plugin.py sync reports a conflict when the vault and live copies both changed"
type: convention
area: [harness]
projects: []
tags: [plugin, install_plugin, sync, how-to]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-07
supersedes: []
---

`python3 _bin/install_plugin.py sync` reports `conflict` when the vault copy and the live copy in
`~/.claude` of a plugin file have both changed since the last sync (for example a data file a skill
reads, edited by hand in one place and by a session in the other). It leaves both alone.

Fix: look at the backup and diff the sync wrote under the state directory's `plugin-backups`, decide
which side is right, copy that version over the other (normally the vault's over the live one) and run
`sync` again until it reports `same`.

Never resolve it by deleting the live copy: the next sync would treat the vault side as new and lose
whatever only the live side had.
