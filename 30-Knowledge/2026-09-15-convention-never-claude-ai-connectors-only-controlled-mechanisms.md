---
id: 2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms
title: Integrations use mechanisms the vault controls
type: convention
area: [integrations, security]
projects: []
tags: [connectors, mcp, oauth, kdbx, google, independence, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Vendor account connectors (the integrations an AI chat app attaches to one account, such as a
mail or drive connector enabled in a web app's settings) are never used. External services are
reached only through mechanisms the vault controls:

- a script in `_bin/` or inside a skill that reads its credential from the KeePass database;
- a generic or self-hosted MCP server configured in the agent;
- anything else where the credential, its scopes and its revocation belong to the user and work
  the same from any agent, account or unattended routine.

If a connector happens to be attached to the account a session runs under, its presence is not a
reason to use it. A capability that exists only through a connector counts as unavailable.

## Routes that ship with this repo

- **Google (Gmail, Calendar, Drive, Contacts):** `_bin/google.py`, one named account per Google
  identity, each with its own OAuth client and refresh token in the kdbx. Accounts are added
  during the first run.
- **Object storage:** `_bin/s3v.py`, key in the kdbx. [[2026-08-26-decision-file-vault-in-s3]]
- **The vault itself, for any MCP client:** `integrations/mcp/server.py`.

## Why

The machinery has to work the same from any agent, any account and any headless routine. A
connector belongs to one app and one account, its scopes are not the user's to set, and it
disappears when either changes. A routine that silently depended on one would stop the day the
account changed, with no error.

## Links

- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
- [[2026-08-20-decision-credentials-in-keepass]]
- [[2026-09-15-decision-first-run-asks-before-connecting-accounts]]
