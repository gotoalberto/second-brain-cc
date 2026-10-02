---
id: 2026-09-26-failure-session-start-hook-timed-out-on-machine-probes
title: Session start hook timed out while probing the machine
type: failure
area: [harness, hooks]
projects: []
tags: [compass, machine_caps, hooks, session-start, timeout, cache, guardian, load]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-26
supersedes: []
---

# Session start hook timed out while probing the machine

## What happened

The guardian's hook probe reported that the session start hook (`compass.py`) went over its time
budget when run the way Claude Code runs it. It reproduced both in the probe's scratch sandbox and on
the real path. The machine was busy with a long background job at the time, so every process fork
cost several times its usual price, and this hook forked a lot.

Most of the budget went to the machine block: a handful of local probes (which machine this is,
whether the browser is running, which tools are installed, which services are up) run one after
another, each one a subprocess, on every single session start. Those facts barely change between two
sessions a few minutes apart.

A hook that is killed at its deadline gives the session nothing: no protocol summary, no active
projects, no health warnings, no machine block. Nothing tells the session it is missing them.

Two quieter defects showed up next to the timeout, and both are worse than it:

- **A probe that timed out was reported as an answer.** The browser check treated any non-zero exit
  as "not running". When `pgrep` was simply too slow under load, the startup block told the session
  that the browser was unavailable while it was running the whole time.
- **A timeout that did not bound the call.** `maybe_pull()` in `_bin/brainlib.py` promised that the
  caller never waits beyond `timeout`, yet only the `git pull` itself was bounded. The lock wait, the
  `rev-parse` and the `diff` around it were charged on top, so a caller that asked for a few seconds
  measured nearly twice that.

## Lessons

- **A hook path reads cached state; it never computes.** The rule already held for the health block,
  whose docstring said that the start hook runs no checks. The machine block simply did not follow
  it. Anything a hook shows that costs a fork belongs in a cache refreshed behind the session.
- **Stale beats missing.** A machine block probed ten minutes ago costs the session nothing worth
  having; a killed hook costs it the whole startup context.
- **A probe that did not answer is unknown.** Exit status 0 means yes, 1 means no, and anything else
  (a timeout, a missing binary, an unreadable process list) means the question went unanswered and
  is printed that way. An answer that admits it does not know something is never cached, and an
  older complete answer is preferred over a fresh partial one.
- **A function's timeout bounds the whole call.** One deadline is shared by every step, with small
  fixed caps for the local steps. The network step still keeps a floor: a `pull --rebase --autostash`
  killed between stashing and re-applying leaves the repository mid-rebase, which is worse than a
  slow start, so a caller that cannot afford the floor gets no pull at all.
- **Daemon threads when the deadline must bound the process.** `concurrent.futures` joins its
  worker threads when the interpreter exits, so a probe still running at the deadline kept the hook
  alive after it had printed its answer. The deadline bounded the output and left the process
  running. Plain daemon threads end with the process.
- **One slow machine looks like several slow hooks.** When several hooks miss their budget at the
  same moment, measure them again on a quiet machine before touching any of them. A deliberately
  overloaded machine pushes every hook past any reasonable budget, so no amount of optimizing will
  make the probe green under that load.

## What changed

Each mechanism is described by behaviour; the code is the reference.

- `_bin/machine_caps.py`: `cached_section()` serves the machine block from a small JSON cache in the
  state directory. A fresh cache is returned as is; a stale one is returned at once and refreshed by
  a detached `--refresh` process (throttled, never under `BRAIN_OFFLINE`); with no cache at all it
  probes for about a second on daemon threads and returns whatever answered. `--fresh` probes with a
  long budget for a person at a terminal.
- `_bin/compass.py`: the start hook calls the cached path, and the working tree fingerprint it takes
  for its baseline runs `git status` with a short per-call timeout, so a repository with many
  worktrees cannot eat the budget. A worktree that does not answer only reads as changed, which is
  the safe side.
- `_bin/brainlib.py`: `maybe_pull()` shares one deadline across every git call it makes and skips
  the pull when the caller cannot afford its floor.
- `_bin/guardian_core`: the hook probe runs a timed-out case a second time before believing it, and
  records the load average per CPU. A case that timed out twice on a heavily loaded machine is a
  warning ("probably the machine, not the hook") and does not page anyone; a timeout on a quiet
  machine, or where no load figure is available, is still a failure.

## Links

- [[2026-09-16-decision-guardian-hook-probe-timeout-not-reproducible-debounce-added]]: the earlier
  investigation that found nothing because it timed the hooks on a quiet machine.
- [[2026-09-10-decision-startup-budget-warns-never-trims]]: the same startup block failing from the
  other side, losing context to save tokens.
- [[2026-09-15-runbook-brain-guardian]]
