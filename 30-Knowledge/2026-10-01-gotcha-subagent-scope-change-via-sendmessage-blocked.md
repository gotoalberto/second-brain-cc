---
id: 2026-10-01-gotcha-subagent-scope-change-via-sendmessage-blocked
title: Scope change sent to a running subagent with SendMessage
type: gotcha
area: [harness, agents]
projects: []
tags: [subagents, sendmessage, auto-mode, classifier, orchestration]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-01
supersedes: []
---

# Scope change sent to a running subagent with SendMessage

## What happened

The main session launched an implementer to build one component. While it worked, the user asked for
more: a second operation on the same component, and a new name to match. The main session relayed
that to the running agent with SendMessage. The auto mode classifier then refused the agent's next
writes (its spec edit and a new test file) as injected instructions. Seen from inside the subagent, a
change of scope that arrives in the middle of a task looks like text injected into its context, since
the user's own request never reached it.

## How to handle it

- **Do not resend the change, and do not ask the subagent to work around the refusal.** The
  classifier is doing its job.
- **The main session, which holds the user's words, updates the spec itself**, then launches a fresh
  agent whose first prompt carries the full scope and quotes the user's request, and which continues
  from whatever the first agent committed or drafted.
- Small clarifications sent with SendMessage seem to pass (a file name, which of two options was
  meant). Messages that widen what the agent builds are the ones refused.

## Links

- [[2026-09-15-convention-agent-orchestration-per-task]]
- [[2026-09-16-convention-orchestrator-does-the-step-that-kills-agents]]
