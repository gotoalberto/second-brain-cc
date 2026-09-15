---
id: 2026-08-21-convention-guides-with-secrets-to-keepass
title: Guides and runbooks keep credentials in the KeePass database
type: convention
area: [security, credentials]
projects: []
tags: [credentials, keepass, guides, runbooks, documentation, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Whenever you write a guide, a runbook or a setup document and a credential, token or secret
configuration value comes up:

1. File the value in the KeePass database with `kp.py put`, in the agent group and the category it
   belongs to. [[2026-08-20-convention-claude-kdbx-group-layout]]
2. Leave only the `kp://` reference in the document, never the value.
3. List in the document what is still missing, and say that it should be filed and referenced the
   same way once obtained.

The user does not have to ask for this each time.

## Why

A setup guide is the document most tempting to paste values into "so it works first time", and it is
the one that travels furthest: shared with colleagues, pasted into tickets, committed to a repository.
Keeping guide and credential apart makes the document safe to share, and rotating a secret does not
mean chasing copies of the text.

## Not everything filed is exposed

`--exposed` means "this must be rotated" and feeds `kp.py audit`. Use it only for real secrets that
went through the chat.

Identifiers that are public by design (an OAuth client id, a public app id embedded in a client
bundle) can be filed for convenience, but marking them exposed fills the audit with false positives.
Say in the entry's notes that the value is public. Hostnames and internal URLs are not secrets and can
stay in the guide.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
