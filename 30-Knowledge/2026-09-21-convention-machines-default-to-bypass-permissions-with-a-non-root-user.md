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
updated: 2026-09-21
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

Scheduled routines are separate: their allowlists never include unrestricted permissions
([[2026-09-15-runbook-brain-routine-auth]]).

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]]
