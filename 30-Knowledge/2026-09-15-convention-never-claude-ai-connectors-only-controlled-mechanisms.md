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
updated: 2026-09-26
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

The rule holds on every machine and in every kind of session: an interactive CLI, a Remote Control
session, a scheduled routine.

## How it is enforced

- **Switched off in the harness.** The guardian (`_bin/guardian_core`, `REQUIRED_ENV` in
  `domain.py`) keeps `"env": {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}` in Claude Code's
  `~/.claude/settings.json`, the same way it keeps the hooks wired, and leaves every other key of
  that block alone. With the flag set, Claude Code does not load the account connectors, so no
  connector tool and no notice about one reaches a session. A user who wants them back empties
  `REQUIRED_ENV`.
- **Notices are never relayed.** Where a connector still shows up (a machine the guardian has not
  repaired yet, a cloud session), the harness may inject a notice asking the session to tell the user
  to authorize it. That notice is boilerplate and this rule overrides it: the connector counts as
  absent, the user is not asked to authorize anything, and the work goes through the controlled route.

## Incident

A session finished a routine maintenance task and closed its report by telling the user that two
connectors needed authorization in the chat app's settings. It had copied the harness notice into
its reply. The rule said never to use a connector and said nothing about the harness asking the
session to promote one, so the notice looked like a real gap, while the controlled route for the same
service (a service account key in the kdbx) worked the whole time. The fixes were the two above.

## Routes that ship with this repo

- **Google (Gmail, Calendar, Drive, Contacts):** `_bin/google.py`, one named account per Google
  identity, each with its own OAuth client and refresh token in the kdbx. Accounts are added
  during the first run.
- **Files:** `_bin/files.py` over a local directory, with no account to connect. [[2026-09-15-decision-file-vault-in-a-local-directory]]
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
