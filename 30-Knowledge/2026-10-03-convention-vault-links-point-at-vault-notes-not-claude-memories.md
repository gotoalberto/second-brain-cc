---
id: 2026-10-03-convention-vault-links-point-at-vault-notes-not-claude-memories
title: Vault links point at vault notes, never at the assistant's memory names
type: convention
area: [vault]
projects: []
tags: [links, memory, wikilinks, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-03
supersedes: []
---

A `[[link]]` in a vault note must be the id of another vault note. The names of Claude Code's own
auto-memory entries are not vault notes: they live outside the vault, resolve to nothing, and become
broken links that every search then reports
([[2026-09-10-decision-every-search-finds-and-fixes-broken-links]]).

To cite a fact that also sits in an auto-memory, link the vault note that holds the same fact, or
write the idea in prose. If no vault note holds it and it is durable, write one first
([[2026-09-09-convention-memory-must-not-assert-mutable-state]]).
