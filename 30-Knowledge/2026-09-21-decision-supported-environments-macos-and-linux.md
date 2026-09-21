---
id: 2026-09-21-decision-supported-environments-macos-and-linux
title: Supported environments are macOS and Linux, and every session is told which machine it is on
type: decision
area: [harness]
projects: []
tags: [machines, portability, macos, linux, session-start, capabilities, skills, scheduled-tasks, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## What was decided

The harness has two supported environments: **macOS** and **Linux**. Skills, scheduled tasks and
injected prompts are written for both, and name the environment ("on a Linux machine"), never a
particular host. The only place a host is named is where a row really is pinned to one: the
`machine` column of `90-Meta/scheduled-tasks.md`.

Each machine can have its own Chrome with the Claude extension, on Linux under a desktop that is
always on ([[2026-09-21-runbook-install-on-a-new-machine]], browser step).

## Capabilities are probed, never inferred from the OS

**Never decide what a machine can do from its OS or its hostname.** "This is Linux, so there is
no browser" is exactly the wrong inference: a Linux server can have its own Chrome, and a Mac can
have its Chrome closed. Probe the machine instead, or read what the session was told about it.

`_bin/machine_caps.py` builds a `## This machine` block that the startup context carries at the
top of every session: the machine key, OS and user; which tools are on `PATH`; whether a local
Chrome is installed and running; local services that answer. Local probes only, each bounded by a
short timeout, so it costs almost nothing. A skill or agent that needs a capability reads that
block, and at run time confirms with a real call (for a browser, see
[[2026-09-21-reference-where-claude-in-chrome-is-available]]).

## Consequences

- A skill or scheduled task must work in both environments, or say in its own description that it
  is bound to one, so it is skipped rather than failing confusingly on the other.
- Code never hardcodes a platform path: `shutil.which` instead of `/opt/homebrew/bin/...`,
  `~/...` instead of an absolute home. Flags that differ per platform are chosen per platform
  (`ping -W` is milliseconds on macOS and seconds on Linux).
- Scheduler templates exist for both: launchd plists and systemd user units, and the guardian
  ignores the scheduler a machine does not have instead of failing on it every pass.
- A "does this exist" check probes the environment (a binary on `PATH`, a real call that
  answers), never a file shipped inside the repository, which always exists.
- Moving a scheduled task to another machine checks its resources there first:
  [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]].

## Links

- [[2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label]]
- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
