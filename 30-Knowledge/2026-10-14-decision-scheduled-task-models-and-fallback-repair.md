---
id: 2026-10-14-decision-scheduled-task-models-and-fallback-repair
title: Scheduled tasks pick their model per routine, with a repair attempt on a stronger model
type: decision
area: [harness]
projects: []
tags: [routines, scheduled-tasks, model, fallback, repair, tasks-py, model-fallback, cost]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-14
supersedes: []
---

# Model per routine and the repair attempt

## What was decided

**Every agent routine names its model.** Its front matter in `90-Meta/routines/` says

```yaml
model: <model name>              # the model of the first attempt
fallback_model: <model name>     # the model of the repair attempt, or none
```

with the model names the agent CLI accepts for `--model` (the list lives in `_bin/model_fallback.py`,
`MODELS`). The cheapest model that does the job well is the one to pick; the strongest one is kept for
routines where judgment or writing quality is the point. Without `model:` the run stays on the
default of the agent command template. `fallback_model:` defaults to the strongest model, `none`
switches the repair off, and a routine already on the strongest model has no fallback.

**A failed first attempt gets one repair attempt.** `_bin/tasks.py` (`run_agent`) hands the run to
`_bin/model_fallback.py`. The first attempt appends `--model <model>` to the routine's arguments. When
it fails for a reason a better model can help with (a non zero exit the classifier cannot name, a
timeout, a broken success contract), the runner makes exactly one more attempt on the fallback model.
The alert is raised only when both attempts fail.

**Failures a better model cannot fix never fall back**: a refused or malformed credential, a usage or
credit limit, the network, a pool or allowlist configuration error, a missing CLI, a locked or
missing credential store, an account mismatch (`NOT_A_MODEL_PROBLEM`). A second attempt there would
spend tokens to fail the same way.

## The repair prompt

The repair attempt runs the same routine with a prompt put in front of its body. In this order:

1. **Never repeat a side effect the failed attempt already produced.** Check the logs, the accounts
   and the send log first: a message already sent, a post already published or a file already
   uploaded stays done.
2. **Find the cause.** The failed attempt's scratch directory is kept and the repair attempt gets read
   access to it, with the failure kind and the redacted output.
3. **Fix the cause where it lives.** When the cause is the procedure or the model's handling of it,
   fix the skill in the vault's plugin, or the routine file, and run `install_plugin.py sync`.
4. **Log the fix** in the vault's fallback log (`90-Meta/routine-model-fallback-log.md`), one entry
   per repair: routine, failure, what was changed.
5. **Then finish the job.**

On top of the routine's own allowlist, the repair attempt gets `Edit`, `Write`,
`install_plugin.py sync` and `vw.py append`, and nothing else.

## Why

Running every routine on the strongest model costs several times what most of them need: a
mechanical audit or a fixed format digest runs as well on a cheap model. Running them all on a cheap
model saves that, but a cheap model fails more often on the odd case, and a plain retry on the same
model fails the same way. The repair attempt pays for the strong model only when it is needed, and
it fixes the procedure so the cheap model stops tripping over the same case. A run that failed for
an outside reason (credentials, quota, network) gets no second attempt, because no model fixes that.

## Example

An invented routine that summarises a gym's class bookings each morning runs on a cheap model with
the default fallback. One day the booking export adds a column and the summary breaks its success
contract. The repair attempt on the strongest model reads the kept scratch directory, sees the
summary was never sent, adds a line on the new column to the skill, syncs the plugin, logs the fix
and sends the summary. The next morning the cheap model handles the new column on its own.

## Alternatives considered

- **One model for everything.** Simple, but either expensive or brittle.
- **Retry on the same model.** Cheap, but a procedure the model misreads stays misread.
- **Fallback without the fix.** Every odd case would cost a strong model run, every time.

## Links

- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-12-convention-back-up-a-skill-before-rewriting-it]]
- [[2026-09-15-convention-scheduled-job-exit-code-should-reflect-crash-not-findings]]
