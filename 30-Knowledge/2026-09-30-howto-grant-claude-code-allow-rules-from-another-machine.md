---
id: 2026-09-30-howto-grant-claude-code-allow-rules-from-another-machine
title: Granting Claude Code allow rules on a remote machine from another machine
type: howto
area: [harness]
projects: []
tags: [permissions, auto-mode, allow-list, settings, ssh, jq]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-30
supersedes: []
---

# Granting Claude Code allow rules on a remote machine from another machine

## When to use it

Auto mode's classifier refuses some actions even after the user has said yes in chat: reading a
secret from a cloud secret store, using a production key, writing a `.env`, a production deploy.
The agent cannot fix its own permissions, because reading or editing its settings file is itself
refused. An explicit allow rule in the user's settings skips the classifier for the commands that
match it, so the person adds the rule, with one command pasted on the machine they are sitting at.

## The command

Run on the person's own machine; it reaches the agent's machine over ssh:

```sh
ssh agent-box 'f=/home/agent/.claude/settings.json; cp -p "$f" "$f.bak-$(date +%s)" && jq ".permissions.allow = ((.permissions.allow // []) + [\"RULE1\", \"RULE2\"] | unique)" "$f" > /tmp/settings.json && cat /tmp/settings.json > "$f" && rm /tmp/settings.json && ls -l "$f" && jq ".permissions.allow | length" "$f"'
```

Replace `RULE1`, `RULE2` with the rules, each one inside `\"...\"`. `agent-box` and `/home/agent`
stand for the remote host and the home of the user the agent runs as.

- **Use the agent user's absolute path.** ssh may land as another user (often root), where `~` points
  at a different home and the file is not there.
- **`cp -p` keeps a timestamped backup.** To undo: `cp -p "$f.bak-<ts>" "$f"`.
- **`cat tmp > "$f"` instead of `mv`** writes into the existing file, so it stays owned by the agent's
  user. `ls -l` at the end shows the owner and `jq length` the rule count.
- **`unique`** makes it safe to run twice.
- On the agent's own machine, drop the ssh and use `~/.claude/settings.json`.
- The running session picked the new rules up without a restart.

## Writing commands that match the rules

A Bash rule matches by prefix: `Bash(<command prefix>:*)`. Write the commands the agent will run so
they start with exactly that prefix.

- **Flags instead of environment variable prefixes**: `tool --account staging read-config ...`
  matches `Bash(tool --account staging read-config:*)`; `ACCOUNT=staging tool ...` does not.
- **The tool's absolute path** when it is not on PATH, in the rule and in the command alike.
- **`cd <dir> && <cmd>` is fine**: compounds are judged part by part, and `cd` passes.
- **A `.env` file the tool loads needs its own rule**, `Write(<absolute path>/.env)`.
- **Prefer read-only subcommands** (get, list, describe, status). A rule for a write verb
  hands over more than the step needs.

## Limit

A matching rule does not guarantee the step goes through: using a production key was still
refused once the `.env` named the key. When that happens the person runs the step.

## Links

- [[2026-09-23-constraint-auto-mode-classifier-blocks-credential-access-and-its-own-fix]]
- [[2026-09-27-convention-user-handoffs-as-one-pasteable-command]]
- [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]]
