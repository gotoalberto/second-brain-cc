---
id: 2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account
title: Brain machinery runs independently of any agent app, account or model
type: decision
area: [harness]
projects: []
tags: [independence, scheduler, hooks, guardian, credentials, routines, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## What was decided

Scheduling, credentials, health checks and repair live outside any AI chat app. They run from
the operating system's scheduler and the vault's own scripts, and keep working when the agent
app is closed, when the user logs into another account, or when the model or the agent changes.

- **Scheduling** runs from launchd on macOS, systemd user units on Linux, or cron where systemd is
  absent. The jobs call vault scripts with a minimal environment and no reference to any agent.
- **Credentials** live in the local KeePass database and are read by scripts. No integration goes
  through a vendor connector. [[2026-09-15-convention-never-claude-ai-connectors-only-controlled-mechanisms]]
- **Events belong to the vault.** A registry in `90-Meta/events.json` names every event and its
  triggers. Agent hooks (Claude Code's are the first adapter) are generated wiring, and agent-free
  triggers carry the rest: a file watcher, versioned git hooks, an MCP server and a CLI.
  [[2026-09-15-runbook-brain-events]]
- **A guardian** restores the generated wiring when it drifts, proves the hooks actually fire, and
  alerts through a desktop notification, email and a local log.
  [[2026-09-15-runbook-brain-guardian]]
- **AI routines** run through a configurable agent command with a dedicated long-lived token from a
  pool in the kdbx, never with whatever account an app happens to be logged into.
  [[2026-09-15-runbook-brain-routine-auth]]

## Why

Agent apps lose hook wiring on login changes and settings resets, and their own scheduled tasks
live per account. When any of that silently breaks, memory stops being queried and saved and
routines stop running, with no error anywhere. Tying the machinery to the operating system and to
files the user owns removes that single point of failure, and makes the same vault usable from a
different agent.

## Consequences

- A routine that needs a capability only an app provides (a browser bridge, a connector) reports a
  failure through the alert channel instead of silently not running.
- Smoke checks of this machinery must isolate every state path they touch.
  [[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]

## Links

- [[2026-09-15-decision-first-run-asks-before-connecting-accounts]]
- [[2026-09-15-convention-scheduled-job-exit-code-should-reflect-crash-not-findings]]
