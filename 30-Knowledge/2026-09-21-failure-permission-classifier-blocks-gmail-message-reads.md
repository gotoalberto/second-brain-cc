---
id: 2026-09-21-failure-permission-classifier-blocks-gmail-message-reads
title: Auto mode permission classifier blocks Gmail message reads through google.py
type: failure
area: [harness, integrations]
projects: []
tags: [google, gmail, permissions, auto-mode, classifier, failure]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## What happens

In Claude Code's auto mode, the permission classifier lets a Gmail list or search call through
`google.py` pass (`python3 ~/Brain/_bin/google.py api --account <name> ".../messages?q=..."`) but
blocks reading one message's metadata or body (`.../messages/<id>?format=metadata`), denying it as
personal data handling. It blocked twice in one run, including right after the user had explicitly
asked for the read: auto mode did not take the request as consent.

The effect is quiet. A skill that reads newsletters from Gmail loses that source while every other
source keeps working, and the output just looks thinner.

## What to do

- Say so, and ask the user to allow it. Do not try to get around the classifier by another route
  (a different script, an encoded URL, a subprocess): that is routing around a gate, see
  [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]].
- The user can allow it for good with a permission rule in their Claude Code settings, for example
  `Bash(python3 /absolute/path/to/Brain/_bin/google.py:*)`. Use the absolute path: a rule written with
  `~` or `$HOME` does not match the command as run. Adding that rule is the user's decision, not the
  agent's.
- Or run that step in an interactive session, where the prompt can be approved by hand instead of
  being denied automatically.
- A skill that depends on reading mail should say in its report when the mail source was blocked,
  instead of presenting a result built from the other sources alone.

## Links

- [[2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms]]
- [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]]
- [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]]
