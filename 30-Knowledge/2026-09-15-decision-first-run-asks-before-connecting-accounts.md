---
id: 2026-09-15-decision-first-run-asks-before-connecting-accounts
title: First run asks before connecting any account
type: decision
area: [onboarding, harness]
projects: []
tags: [first-run, onboarding, consent, kdbx, google, s3, mcp, scheduler, routines, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## What was decided

A fresh clone works with no accounts at all: notes, search and the write path need only Python and
git. Everything that connects to something outside the machine is optional, and nothing is
connected without the user saying yes.

On the **first session in a new vault** (no first-run state recorded yet), the agent asks the user
whether they want to connect accounts now. Only with consent does it run the first-run flow,
`integrations/first-run/setup.sh`. `bootstrap.sh` offers the same flow at the end of its run.

## The flow

Each step is an explicit yes or no and can be skipped, except the files directory, which only asks
where. Every step records its outcome so a later run resumes where the previous one stopped:

1. **KeePass database.** Point at an existing `.kdbx` or create one, then test an unlock.
   [[2026-08-20-decision-credentials-in-keepass]]
2. **Google accounts.** How many to connect and a name for each; one OAuth client and refresh token
   per account, stored in the kdbx, through `_bin/google.py`.
3. **Files directory.** Where `files.py` keeps files, proposed as `~/BrainFiles`, created and proven
   writable before it is recorded. This step is required and cannot be declined.
   [[2026-09-15-decision-file-vault-in-a-local-directory]]
4. **Alert email.** Where the guardian sends its alerts, and through which connected account.
5. **MCP server.** Print the configuration block for the user's agent, or append it only when asked.
   Nothing is written into an agent's configuration uninvited.
6. **Scheduled jobs.** Detect launchd, systemd or cron, show the units that would be installed, and
   install only on a yes.
7. **CLI agent routines.** The agent command and the token pool for unattended runs.
   [[2026-09-15-runbook-brain-routine-auth]]

`integrations/first-run/README.md` says how to re-run it, how to skip steps and how to run it in a
non-interactive context.

## Why

- Connecting accounts touches credentials, mail and the user's scheduler. That needs consent every
  time, and a clear record of what was and was not set up.
- An agent that silently skipped setup would leave a vault that looks installed while its routines,
  alerts and storage do nothing.
- An agent that set everything up without asking would write into places the user never agreed to.

## Links

- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
- [[2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms]]
