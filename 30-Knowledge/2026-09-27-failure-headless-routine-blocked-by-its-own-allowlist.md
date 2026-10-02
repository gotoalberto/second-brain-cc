---
id: 2026-09-27-failure-headless-routine-blocked-by-its-own-allowlist
title: Headless routine blocked by its own allowlist
type: failure
area: [harness]
projects: []
tags: [routine, headless, allowlist, agent_args, gate_memory, success-contract, timeout, retry]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-27
supersedes: []
---

# Headless routine blocked by its own allowlist

## What happened

A weekly routine that publishes a handful of reports produced nothing. Diagnosing it turned up four
separate faults that all end the same way, with an unattended run that does not deliver.

**The prompt ordered commands the allowlist did not grant.** The routine body told the agent to run
the style checker and a PDF renderer on every report before publishing it. Its `agent_args`
allowlist only named the script that builds the reports. Headless, both commands came back with
"This command requires approval", and the agent did the right thing: it refused to publish text it
had not been able to check. Nobody was there to approve anything, so the run ended with nothing sent.

**A Stop hook replaced the run's final answer.** The memory gate (`_bin/gate_memory.py`) also fired
in scheduled runs and forced one more turn. The one-line answer of that extra turn became the
`result` of `--output-format json`, which is the text a success contract with a `required` marker
reads. A good run would still have been judged a failure, because its marker had been overwritten.

**The runner's default timeout cut a long run.** A forced rerun the same day published part of its
work and then hit the default 30-minute limit. The rest rolled to the next week.

**A dropped connection killed a run before it could record a failed step.** In another routine the
same morning, a network reset while reading the mailbox escaped the API helper as an exception. The
step died before it stamped itself as failed, and the report that depended on that stamp was then
refused.

## Rules

- **Every command a routine prompt orders is in that routine's `agent_args`.** Read the prompt's code
  blocks against the allowlist whenever either one changes. `routine_requires.py` checks that what
  `agent_args` names exists on the machine; it cannot know what the prose asks for.
- **A Stop hook that can force a turn stays silent when `BRAIN_HEADLESS=1`.** The runner exports it
  for every scheduled run. A scheduled run is told not to save to memory anyway, and the extra turn
  would replace the final answer the contract reads. `gate_memory.py` exits at once under that
  variable.
- **A routine whose work has no fixed size sets its own `timeout_minutes`**, paired with
  `single_instance: true` so an overrun never overlaps the next tick.
- **Network reads retry; writes do not.** An idempotent read (a GET) is retried a few times with a
  growing backoff when the connection drops. A write is never retried, since a write that reached the
  server and lost its answer would run twice. After the last attempt the failure is returned to the
  caller as data, so the step can still record that it failed.

## Links

- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-15-convention-success-contracts-must-check-the-log-not-the-models-final-words]]
- [[2026-09-15-convention-headless-agent-prompt-must-be-framed-as-an-order]]
- [[2026-09-24-decision-single-instance-flag-for-routines]]
- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
