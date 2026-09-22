---
id: 2026-09-21-convention-agents-must-not-run-scripts-needing-human-typed-secrets
title: Agents never run a script that needs a secret typed by the human
type: convention
area: [security]
projects: []
tags: [security, secrets, agent-boundaries, private-keys, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## The rule

When a tool needs a secret that only the human should ever hold (a wallet private key, a master
password, a signing secret), the agent writes the tool so that the human types the secret into
their own terminal, in person, and the agent never runs that final step. Not on a trusted machine,
and not when handing the finished tool to another agent session on the user's own computer. The
hand off says: write the files, install the dependencies, then stop; never run the final command.

## Alternatives rejected

- **Pasting the secret into the chat**, even when the user offers to. Anything written in a
  conversation with a model is kept in transcripts and logs and sent to the model provider. There is
  no safe way to paste a raw secret into a conversation, however much the model is trusted.
- **Passing it as a command line argument** for a one line command. Arguments land in shell history
  and are visible to every process on the machine through `ps` while the command runs. That is worse
  than an environment variable.
- **Letting an agent run the script on the user's own machine.** The interactive prompt
  (`read -rsp`) either hangs waiting for keyboard input the automation cannot give, or invites the
  agent to "fix" the hang by piping the secret through some channel that lands in its own context
  or logs, which defeats the prompt.

## Why

An interactive prompt that does not echo, is not logged and is not a process argument only protects
the secret if a person is at the keyboard when it runs. An agent running that step brings back
exactly the exposure the design removed, however trusted the machine or the session.

## What would change it

A mechanism that lets an agent use a secret without ever seeing it (an OS keychain that grants use
without revealing the value, a hardware signer) could move this line. "The user trusts this agent"
is not enough on its own.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
- [[2026-08-21-convention-guides-with-secrets-to-keepass]]
