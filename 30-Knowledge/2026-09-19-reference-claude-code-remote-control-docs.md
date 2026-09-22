---
id: 2026-09-19-reference-claude-code-remote-control-docs
title: Claude Code Remote Control and desktop SSH connections
type: reference
area: [harness, claude-code]
projects: []
tags: [claude-code, remote-control, ssh, server-mode, docs, reference]
status: active
confidence: high
source: agent
provenance: "read from the public Claude Code documentation on 2026-09-19"
updated: 2026-09-19
supersedes: []
---

## Source

The public Claude Code documentation pages on Remote Control
(`https://code.claude.com/docs/en/remote-control.md`) and on the desktop app
(`https://code.claude.com/docs/en/desktop.md`), read on 2026-09-19. Facts that can change with a
release are dated to that reading; check the pages again before relying on one that matters.

## Server mode

- Server mode serves new sessions on demand, up to `--capacity` (default 32). A subagent had claimed
  it could not start new sessions; the docs say it can.
- With `--spawn worktree` each session gets its own git worktree. Do not use it on this vault: its
  `WorktreeCreate` hook seeds a worktree and returns no path, and every session dies at birth. See
  [[2026-09-18-gotcha-enterworktree-name-creation-fails-in-brain]] and
  [[2026-09-21-runbook-install-on-a-new-machine]].
- After roughly ten minutes without network the server process exits, so it needs a supervisor that
  restarts it (a systemd user unit, a launchd agent), not a tmux pane.
- A session that crashed in server mode is served again by sending it a message from a device, with
  no server restart (from CLI 2.1.238).
- `-c` or `--session-id` can resume a session for about four hours after the server process stopped.

## Requirements

- A claude.ai subscription login through `/login` or `claude auth login`. API keys are not
  supported.
- `claude setup-token` and `CLAUDE_CODE_OAUTH_TOKEN` are not enough either: those tokens can make
  model requests but cannot drive Remote Control.
- None of `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or
  `DISABLE_GROWTHBOOK` may be set: each one turns off the feature flag evaluation Remote Control
  depends on.
- Workspace trust must be accepted once, interactively, for the directory the server runs in. Trust
  is recorded per directory, so accept it in that exact directory.

## Desktop app SSH connections

Code tab, environment menu, "Add SSH connection": a name, the host (from `~/.ssh/config`), port and
identity file. Claude Code installs itself on the remote host on first connect. SSH sessions cannot
use `@` file mentions, and "Continue in" cannot send an SSH session to the web.

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-18-gotcha-enterworktree-name-creation-fails-in-brain]]
