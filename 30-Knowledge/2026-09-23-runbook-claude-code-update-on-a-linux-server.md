---
id: 2026-09-23-runbook-claude-code-update-on-a-linux-server
title: Updating Claude Code on a Linux server, and the Remote Control cgroup trap
type: howto
area: [harness]
projects: []
tags: [claude-code, linux, remote-control, systemd, cgroup, update]
status: active
confidence: high
source: agent
provenance: "generalized from a live upgrade on a Linux server in a working vault, done to get a new model into app sessions; names and versions are illustrative"
updated: 2026-09-24
supersedes: []
---

## Context

`claude update` alone does not update the Claude Code sessions opened from the Claude app on a
Linux server, and restarting the piece that would fix it is destructive well beyond Claude Code.
Worked out end to end while upgrading to get a new model. How Remote Control serves sessions in
general: [[2026-09-19-reference-claude-code-remote-control-docs]]. The same procedure for every
machine, as a skill: [[2026-09-24-runbook-update-claude-on-each-machine]].

## Content

**The binary and the app session path are two different things.** `claude update` (native
install) rewrites the symlink `~/.local/bin/claude` to point at a new
`~/.local/share/claude/versions/<version>`. A session started from the CLI on the machine picks
that up at once. A session started from the **Claude app** does not: the Remote Control service
(`second-brain-remote-control`, a systemd user unit that runs `claude remote-control --chrome
--name <name>`) resolves the symlink once, at its own startup, and spawns every app session with
that **absolute versioned path baked in** (`~/.local/share/claude/versions/<old> --print
--sdk-url ... --resume=...`). So app sessions keep running the old binary until the service
itself restarts, however current the symlink is.

**Restarting that service stops its entire cgroup, not just Claude.** A restart tears down every
process the service's sessions ever spawned: live app sessions, scripts in flight (an OAuth flow
listening on a local port, for example), and any dev server or long running process a session
launched inside its own process tree (`next dev`, `python3 -m http.server`). Those processes stay
in the cgroup after the session that started them ends, so a server with no child session is not
necessarily idle. Chrome, its keepalive and the VNC desktop are separate units and are not in
that cgroup, so they survive. Inspect before restarting: `systemctl --user status
second-brain-remote-control --no-pager` lists the cgroup tree, or read `/proc/<pid>/cgroup` for
one process.

Corollary: **a long running server started from inside a Claude session on this machine dies on
the next restart.** To make one outlive it, start it from a plain SSH shell (`setsid` or `tmux`),
never from inside a session.

**Do not issue the restart from a Claude app session on the same machine.** That session is
inside the cgroup being stopped, so the command kills its own shell mid flight and cannot report
success. Run it from a plain SSH login, which lives in its own cgroup.

**App sessions also pin an explicit `--model`**, independent of the binary version. After the
upgrade and the restart, pick the new model by hand with `/model` inside each session.

**The procedure, in order:**

1. `claude update` (or reinstall) to move the symlink. Check what a version supports before
   picking it, do not guess: the model ids a binary knows with
   `strings ~/.local/share/claude/versions/<v> | grep -oE "claude-[a-z]+-[0-9][a-z0-9-]*" | sort -u`,
   the channels in the native installer's release files (`stable`, `latest`), the version history
   with `npm view @anthropic-ai/claude-code time`, and the changelog in the public
   `anthropics/claude-code` repository. `python3 ~/Brain/_bin/machine_update.py` does the first
   two for you.
2. Check the cgroup for anything that would be lost (`systemctl --user status
   second-brain-remote-control --no-pager`). Finish or park anything in flight first, an OAuth
   consent waiting on a local redirect for instance
   ([[2026-09-23-reference-google-oauth-testing-mode-7-day-refresh-token-expiry]]). Anything that
   must survive (a dev server, a long job) has to be relaunched from an SSH shell.
3. From a plain SSH login, never from a Claude app session on the same host:
   `systemctl --user restart second-brain-remote-control`.
4. Reopen the app sessions. They resume against their cloud session, so history survives; only
   work in flight inside the stopped cgroup is lost. Set the model with `/model`.

With `autoUpdates` false in `~/.claude.json` the binary drifts days behind `latest` without
anyone noticing. Turning it on is worth weighing against the same cgroup risk landing at an
unplanned moment, and it would still need the restart above to reach app sessions.

**The same trap on macOS.** Local desktop app sessions offered the new model while Remote
Control sessions did not: the desktop app bundles its own Claude Code
(`~/Library/Application Support/Claude/claude-code/<version>/`) and updates it by itself, while
the launchd job `com.secondbrain.remote-control` runs `~/.local/bin/claude`, frozen because
`autoUpdates` was off. The fix there was `~/.local/bin/claude update`, then
`launchctl kickstart -k gui/$(id -u)/com.secondbrain.remote-control` while the server had no
open session. Check the running binary with
`lsof -p $(pgrep -f "claude remote-control") | grep versions`.

## Links

- [[2026-09-24-runbook-update-claude-on-each-machine]]
- [[2026-09-19-reference-claude-code-remote-control-docs]]
- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-23-reference-google-oauth-testing-mode-7-day-refresh-token-expiry]]
