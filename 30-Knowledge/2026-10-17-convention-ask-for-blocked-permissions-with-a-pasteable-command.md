---
id: 2026-10-17-convention-ask-for-blocked-permissions-with-a-pasteable-command
title: When a permission the user can grant blocks a task, ask for it with a ready to paste command
type: convention
area: [harness, permissions]
projects: []
tags: [permissions, classifier, auto-mode, allow-list, handoff, convention]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-17
supersedes: []
---

## The rule

In any task, on any machine: when the auto mode classifier or a missing allow rule blocks an action
the user could permit, do not stop at "I could not do it". Say what was blocked and why, and hand the
user one line, pasted on the machine they are sitting at, that grants exactly that permission. Then,
once they have run it, finish the blocked work in the same session.

## Why

A blocked step reported as a dead end leaves the user to work out which rule is missing, where the
settings file is on which machine, and how to write the rule so it matches. They can grant it in
seconds if the command is in front of them; they usually cannot, or will not, reconstruct it. The
agent cannot grant it itself: editing its own permissions is refused, and should be.

## How

- **Narrowest rule that unblocks the work.** A path glob for `Edit` and `Write`
  (`Edit(~/.claude/skills/**)`), a command prefix for `Bash` (`Bash(sudo -n docker inspect web-cache:*)`).
  Never a blanket mode change unless the user asks for one.
- **Write the rule for the command exactly as it will run.** A prefix rule matches the start of the
  command. If the tool only answers through `sudo -n`, the rule starts with `sudo -n`; if the command
  will run with an absolute path, so does the rule. A rule written for `docker inspect` does nothing
  for `sudo -n docker inspect`.
- **Use the right tool afterwards.** An `Edit(...)` rule covers the Edit tool. Writing the same file
  through a python one liner is a different action, still blocked, and a way around the rule the user
  meant to grant.
- **The command itself** follows the pasteable command convention
  ([[2026-09-27-convention-user-handoffs-as-one-pasteable-command]]): one line, absolute remote
  paths, a backup of the settings file, idempotent, and a check printed at the end. The shape for a
  settings file on another machine is in
  [[2026-09-30-howto-grant-claude-code-allow-rules-from-another-machine]].
- **Mind which user ssh lands as.** When ssh logs in as another user (often root), `~` and
  `os.path.expanduser` point at that user's home, where the agent's settings file is not. Use the
  agent user's absolute path, and rewrite the file in place so it keeps its owner.
- A new allow rule took effect in the running session without a restart.

## Example

An invented case: an agent on a build server needs to read a container's state to finish a debugging
task, and `docker` there only works through `sudo -n`. The reply names the blocked call and gives

```sh
ssh build-box 'f=/home/agent/.claude/settings.json; cp -p "$f" "$f.bak-$(date +%s)" && jq ".permissions.allow = ((.permissions.allow // []) + [\"Bash(sudo -n docker inspect web-cache:*)\"] | unique)" "$f" > /tmp/s.json && cat /tmp/s.json > "$f" && rm /tmp/s.json && jq ".permissions.allow | length" "$f"'
```

then runs `sudo -n docker inspect web-cache` once the user says it is done.

## Links

- [[2026-09-23-constraint-auto-mode-classifier-blocks-credential-access-and-its-own-fix]]
- [[2026-09-30-howto-grant-claude-code-allow-rules-from-another-machine]]
- [[2026-09-27-convention-user-handoffs-as-one-pasteable-command]]
