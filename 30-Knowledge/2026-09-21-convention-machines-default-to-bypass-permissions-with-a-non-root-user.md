---
id: 2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user
title: Your own machines default to bypassPermissions, run by a non-root user with passwordless sudo
type: convention
area: [harness, security]
projects: []
tags: [claude-code, permissions, remote-control, sudo, root, machines, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-21
supersedes: []
---

## The convention

On machines that are your own and that you drive yourself, Claude Code sessions run with
`bypassPermissions` as the default mode. The account that runs the harness is a **normal user
with passwordless sudo**, never root.

In that user's `~/.claude/settings.json`:

```json
{
  "permissions": { "defaultMode": "bypassPermissions" },
  "skipDangerousModePermissionPrompt": true
}
```

Create the user with `NOPASSWD:ALL` in `/etc/sudoers.d/<user>`, and set `User=` in any system
unit to that user, never to root.

## Every session, not just yours

Bypass has to reach every way a session starts, or one of them stops at a prompt nobody answers:

| Session | Where it gets bypass |
| --- | --- |
| Yours, in a terminal | `permissions.defaultMode` above, merged by `_bin/claude_settings.py merge` |
| Remote Control, from the app | `_bin/remote_control.py` passes `--permission-mode bypassPermissions`, and sets `CLAUDE_CODE_PROCESS_WRAPPER` to `_bin/claude_session_wrapper.sh`, which adds `--allow-dangerously-skip-permissions` to each session so bypass stays in the app's mode picker after the app switches a session to another mode |
| Scheduled routines | `90-Meta/agent-command.txt` ends in `--permission-mode bypassPermissions --allow-dangerously-skip-permissions`; a routine's own `agent_args` come after it and win, so they say bypassPermissions too |

## Claude in Chrome asks anyway, unless two things are set

Bypass alone does not cover the browser. A server-side "Chrome classifier floor" makes every
Claude in Chrome action ask, even in bypass and on allowed sites. Two settings turn that into the
same no-prompt behaviour as every other tool:

- `env.CLAUDE_CHROME_CLASSIFIER_FLOOR = "0"` in `~/.claude/settings.json`. The guardian keeps it
  there on every machine (`REQUIRED_ENV`). The CLI reads it at start, so new sessions pick it up
  with no restart; a session already running keeps asking.
- One `ClaudeInChromeDomain(<host>)` allow rule per site the agent works on. Exact host, `www.`
  dropped, port kept (`localhost:3000`), no wildcards. Whole-tool rules such as
  `mcp__claude-in-chrome__navigate` do not cover a site. The recommended settings carry the sites
  the shipped skills use; add yours with `python3 _bin/claude_settings.py chrome-allow <host>...`.

And `/chrome` set to "Enabled by default", so plain `claude` sessions get the browser too. That
setting lives in `~/.claude.json`, written by the CLI: change it from `/chrome`, never by hand
while a session runs. Remote Control and routines get the browser from `--chrome`, not from it.

## Why permissive

These sessions are driven from a phone through Remote Control. Answering permission prompts one
at a time on a phone is what makes remote sessions not worth using. The cost has to be said
plainly and accepted by the owner: permissive mode plus passwordless sudo means the agent can do
anything on that machine without asking, including destroy things.

## Why not root

Claude Code refuses outright to skip permission prompts under root
(`--dangerously-skip-permissions cannot be used with root/sudo privileges`). Running as root
would permanently block the mode that makes the phone workflow usable. A normal user with
`NOPASSWD:ALL` administers the machine just as completely (packages, services, firewall), keeps
that mode available, and makes escalation a deliberate, visible `sudo` instead of the default
state of everything.

Unattended jobs still do not escalate on their own. A supervised job that would need root to
repair something reports it instead of calling `sudo`.

## Where it does not apply

Work machines, anything under an organization's policy, and any box where untrusted code could
land. There the reasoning above does not hold, and prompts stay on.

Scheduled routines read untrusted text (mail, web pages, posts). In bypass, a prompt injection
there can run any command as this user. That is the cost of routines that never stall; the
narrower alternative is in `90-Meta/agent-command.txt` and [[2026-09-15-runbook-brain-routine-auth]].
A bare `Bash` in a routine's `--allowedTools` is refused either way.

## How to check a machine

```bash
python3 _bin/claude_settings.py show           # nothing to add, and no "kept as you have it" line
python3 _bin/remote_control.py show            # command has --permission-mode bypassPermissions
ps -eo args | grep -- '--sdk-url' | grep -c -- --allow-dangerously-skip-permissions   # one per live app session
```

In a new session, a Chrome action on an allowed site runs without asking.

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]]
