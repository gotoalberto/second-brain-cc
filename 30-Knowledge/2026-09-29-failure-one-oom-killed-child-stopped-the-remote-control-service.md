---
id: 2026-09-29-failure-one-oom-killed-child-stopped-the-remote-control-service
title: One OOM-killed child stopped the Remote Control service
type: failure
area: [harness, infra]
projects: []
tags: [remote-control, systemd, oom, memory, linux, sessions]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-29
supersedes: []
---

# One OOM-killed child stopped the Remote Control service

## What happened

On a Linux machine, every Remote Control session dropped twice within a few minutes, with a message
that the container had been restarted. The machine had not rebooted. The kernel log showed a global
out-of-memory kill both times: a build tool that one agent had started inside its session had grown
to tens of gigabytes and was killed.

The kill alone should have cost one command. It cost every session because of systemd's default
`OOMPolicy=stop`: when any process of a unit is killed by the OOM killer, systemd stops the whole
unit. The Remote Control service shut down cleanly, `Restart=always` brought it back seconds later,
and every session and background agent that had been running under it was gone.

The runaway was the build tool's post-build linter on a half-written source file; the compile itself
needed a few hundred megabytes. The same linter finished normally on the main branch.

## The fix

In the unit (`_bin/systemd/second-brain-remote-control.service`, kept in step by the guardian):

- **`OOMPolicy=continue`.** The killed process is the only casualty; the service and its other
  sessions keep running.
- **`MemoryMax=` as an optional cap**, so a runaway inside the service is killed before it starves
  the rest of the machine (the desktop, the browser). It is left as a commented example because the
  right value depends on the machine. In a user unit it only takes effect when the memory controller
  is delegated to the user manager.
- **Not `MemoryHigh=`.** It throttles instead of killing, which slows every session down to protect
  one.

Verified with two throwaway units: with `OOMPolicy=continue` the unit stayed active after its child
was OOM-killed; with the default it ended with `Result=oom-kill`.

## Diagnosing it next time

When sessions "restart" and the machine did not:

- look for an OOM kill in the kernel log: `journalctl -k | grep -i oom`, or
  `sudo grep -i oom /var/log/kern.log`;
- check how often the unit came back: `systemctl --user show second-brain-remote-control -p NRestarts`.

## Avoiding the runaway

- Run unknown heavy builds under a cap of their own:
  `systemd-run --user --scope -p MemoryMax=8G <build command>`. A runaway then dies at the cap with
  exit 137 and touches nothing else.
- A linter or analyzer that runs after every build can be the culprit. Turn it off for builds and
  run it on its own when wanted.

## Links

- [[2026-09-19-reference-claude-code-remote-control-docs]]
- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-15-runbook-brain-guardian]]
