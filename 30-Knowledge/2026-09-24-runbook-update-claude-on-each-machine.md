---
id: 2026-09-24-runbook-update-claude-on-each-machine
title: Updating Claude on each machine with the machine-update skill
type: howto
area: [harness]
projects: []
tags: [claude-code, update, remote-control, launchd, systemd, skill, models]
status: active
confidence: high
source: agent
provenance: "generalized from a real update on a macOS laptop in a working vault; the Linux branch follows the Linux server runbook and is less exercised"
updated: 2026-09-24
supersedes: []
---

## Context

A new model was available in local desktop sessions on a laptop but not in the sessions opened
from the Claude app through Remote Control. The desktop app bundles and updates its own Claude
Code, while the Remote Control server ran `~/.local/bin/claude`, frozen at an older version
because `autoUpdates` was off. A Linux server had hit the same trap the day before
([[2026-09-23-runbook-claude-code-update-on-a-linux-server]]). One procedure now knows, per
machine, what to update and how.

## Content

**Entry point:** the `machine-update` skill, backed by `_bin/machine_update.py` (tests in
`_bin/machine_update_test.py`).

- `machine_update.py` reports; `machine_update.py apply` updates; `--json` for scripts.
- Components: `cli` (the native `~/.local/bin/claude`), `rc` (the Remote Control server:
  launchd `com.secondbrain.remote-control` on macOS, the systemd user unit
  `second-brain-remote-control` on Linux), `app` (the desktop app's bundled Claude Code on
  macOS, self updating, reported only), `brew` (a leftover `claude-code` cask on macOS, unused,
  reported only).
- It lists the newest model id per family the CLI binary knows, which answers "why don't I see
  model X" directly.
- The release channel comes from `autoUpdatesChannel` (default `latest`), read from the native
  installer's public release files.

**What apply does by itself:** `claude update`, always. On macOS it restarts the server with
`launchctl kickstart -k` only when the server has no child session and the calling process is
not its descendant. On Linux it never restarts: the restart stops the unit's whole cgroup and
must come from a shell outside the service; the report prints the commands for a person.

**The idle signal:** a Remote Control session is a child process of the server, so "no
children" means idle on macOS. The server's running version comes from `lsof` (macOS) or
`/proc/<pid>/exe` (Linux), both of which point into `versions/<v>`.

**After any update:** a session already open keeps its model; pick the new one with `/model`.

**Not done:** nothing runs this on a schedule. Turning `autoUpdates` on alone would not keep
remote sessions current, since the server still needs a restart to pick up the new binary.

**Traps found writing the checker:**

- Homebrew can hold two casks on macOS: `claude` (the desktop app) and `claude-code` (an older
  CLI, unused when the native install exists). Report both, so a stale `brew` version does not
  look like the active one.
- Release channels are separate rollouts. On the day this was written `latest` and `stable` were
  eight patch versions apart. Do not assume `stable` trails `latest` by a fixed amount; read both.
- The model id scan must cut dated snapshot ids (`claude-<family>-4-20250514`) at the family and
  version, or a stale dated alias sorts after the real newest id and looks like the current model.

## Links

- [[2026-09-23-runbook-claude-code-update-on-a-linux-server]]
- [[2026-09-19-reference-claude-code-remote-control-docs]]
- [[2026-09-21-runbook-install-on-a-new-machine]]
