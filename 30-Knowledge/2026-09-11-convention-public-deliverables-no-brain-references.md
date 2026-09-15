---
id: 2026-09-11-convention-public-deliverables-no-brain-references
title: Public deliverables carry no references to the private vault
type: convention
area: [publishing, security]
projects: []
tags: [publishing, privacy, deliverables, paths, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

A deliverable meant to be public or shared with someone who does not run this setup (a repository, a
document, a published page) must not contain:

- vault paths such as `~/Brain/_bin/kp.py`, or `~/.claude/skills/...` paths;
- vault commands: `/recall`, `/save`, `vw.py`, `s3v.py`, `skills_index.py`;
- links to `30-Knowledge/` or `40-Skills/` notes;
- credential entry names from the user's database.

Replace each with a tool-agnostic equivalent that names no local system, for example
`your-secret-tool get <key> | python3 script.py` instead of a `kp.py` call.

## Why

Those paths and commands reveal the layout of a private memory system, and they mean nothing to
anyone reading the deliverable without it. A methodology document once shipped with a secret-handling
example that named the local credential wrapper and a real entry name.

## How to apply

Before publishing, grep the deliverable for
`brain|~/\.claude|kp\.py|vw\.py|s3v|skills_index|/recall|/save|30-Knowledge|40-Skills` and fix every
real hit. Watch for false positives: a domain term like "vault" in another product's documentation has nothing to do
with this system.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
