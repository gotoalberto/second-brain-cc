---
name: machine-update
description: Updates Claude on this machine (macOS or Linux) and tells what is stale and how to fix it. Covers the native Claude Code CLI, the Remote Control server that serves the sessions opened from the Claude app, the desktop app's bundled Claude Code and a leftover Homebrew cask. Use it whenever the user asks to update Claude or Claude Code on a machine, when a new model shows up in local sessions but not in remote ones, or when versions differ between local and remote sessions.
argument-hint: [status | apply]
allowed-tools: Bash(python3 __VAULT__/_bin/machine_update.py:*), Bash(/usr/bin/python3 __VAULT__/_bin/machine_update.py:*), Read
---

## Current state of this machine

!`/usr/bin/python3 __VAULT__/_bin/machine_update.py 2>&1 || true`

## What each line means

| component | what it is | who updates it |
|---|---|---|
| `cli` | the native Claude Code, `~/.local/bin/claude`, a symlink into `~/.local/share/claude/versions/<v>`. With `autoUpdates` off it drifts. | `apply` runs `claude update` |
| `rc` | the Remote Control server: launchd `com.secondbrain.remote-control` on macOS, the systemd user unit `second-brain-remote-control` on Linux. It resolves the CLI symlink **once, at startup**, so every session it hands out keeps the old binary (and its model list) until the server restarts. | macOS: `apply` restarts it only when idle. Linux: a person, from a shell outside the service |
| `app` | the Claude Code bundled inside the desktop app (macOS). Local desktop sessions use it, which is why local can have a model that remote does not. | the app itself; restart the app |
| `brew` | a Homebrew `claude-code` cask (macOS). Unused while the native install exists. | only reported; `brew uninstall --cask claude-code` if the user wants |

`models known to the CLI` is the newest model id per family inside the CLI binary. If the user
expects a model and it is not listed there, the CLI is too old, whatever the account allows.

## Procedure

1. Read the report above. If it says `up to date`, say so in one line and stop.
2. Tell the user what is stale, then run `python3 __VAULT__/_bin/machine_update.py apply`. It
   updates the CLI, reads everything again, and on macOS restarts the Remote Control server only
   when it has no open session and this session is not running under it.
3. If `rc` is still `stale` after apply, do not restart it yourself:
   * **macOS, sessions open**: restarting ends them. Ask the user; on a clear yes run the `run:`
     command the report shows.
   * **macOS, this session runs under it**: the restart would kill this session. Tell the user
     to run it from a terminal or a session the server did not start.
   * **Linux**: never from a session on that machine. `systemctl --user restart` stops the
     unit's whole cgroup: every session and everything any session started there, even after
     that session ended. Give the user the commands from the report to run from a terminal or a
     plain SSH login, and remind them to finish or move anything running inside a session first.
     Detail: `30-Knowledge/2026-09-23-runbook-claude-code-update-on-a-linux-server.md`.
4. Remind the user that a session already open keeps its model: pick the new one with `/model`
   in each session.
5. For another machine, run the same script there (for example
   `ssh <host> python3 ~/Brain/_bin/machine_update.py`); never infer its state from this one.
   Touch another machine only when the user asked for it.
