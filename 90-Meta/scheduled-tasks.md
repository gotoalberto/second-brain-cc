---
id: scheduled-tasks
title: Periodic task registry
type: reference
area: [harness]
tags: [tasks, cron, launchd, systemd, harness, machines]
status: active
confidence: high
source: agent
provenance: shipped with the harness as a template; edit the table for your own tasks
updated: 2026-09-15
supersedes: []
---

# Periodic task registry

The single inventory of everything that runs on a schedule across every machine running this
harness. The registry lives in the vault so every machine sees the same list, but each task
declares which machine owns it: a task pinned to one host never fires on the others.

`_bin/tasks.py` reads this table every 10 minutes, keeps only the rows matching this host, and
runs whatever is due. It is started by the scheduler you accepted at first run
(`integrations/first-run/setup.sh`): launchd on macOS (`com.secondbrain.tasks`), a systemd user
timer on Linux (`second-brain-tasks`), or a cron line where systemd is absent. Nothing is scheduled
until you accept it there. A row runs when its machine matches, today matches `days`, its time has
passed, and it has not already run today, which is what makes a 10-minute poll fire a 07:30 task
once.

## The table

<!-- Edit this table to add or change a task. Columns are positional; keep all eight. -->

| id | machine | time | days | type | command | enabled | notes |
|----|---------|------|------|------|---------|---------|-------|
| vault-doctor-weekly | * | 09:00 | 1 | shell | python3 _bin/doctor.py | no | Monday health check of the vault |
| example-digest-agent | * | 07:30 | * | agent | 90-Meta/routines/example-routine.md | no | Example routine: emails a digest of the day's notes. Enable after connecting a Google account and adding a routine token |

### Columns

- **id**: unique, kebab-case. Names the log file: `<brain state>/logs/tasks/<id>.log`
- **machine**: `hostname -s` of the host that owns it, or `*` for every machine
- **time**: `HH:MM`, 24h, local time of that machine
- **days**: ISO weekdays, `1`=Mon … `7`=Sun. Accepts `*`, `1-5`, `1,3,5`
- **type**: `shell` (the runner executes `command`), `agent` (the runner hands the routine file
  named in `command` to the CLI agent configured in `90-Meta/agent-command.txt`) or `claude-app`
  (recorded here for inventory, run by the Claude app's own scheduler; the runner never touches it)
- **command**: for `shell`, the shell command, run with the vault as working directory; for
  `agent`, the routine file's path relative to the vault
- **enabled**: `yes` / `no`. `no` pauses it without deleting the row
- **notes**: free text

## Agent routines

An `agent` row runs a routine file from `90-Meta/routines/` through a CLI agent, with no desktop
app open and no chat session. Each run:

- takes a token from the pool in `90-Meta/routine-tokens.json` (references to KeePass entries,
  never values; the file is machine-local and ignored by git), read headless through `_bin/kp.py`,
  and fails over to the next token when one is refused or limited
- gets a run id and a private scratch directory under `<brain state>/routine-scratch/`
- receives a prompt that frames the routine body as an order to run it now, unattended
- succeeds only if its `success_contract` is met: a required send is proved by the send log
  `google.py send` writes, not by what the model says at the end

A failed run raises an alert through the guardian (desktop notification, email if a mailer was
configured at first run, log); the next successful run clears it. A routine whose `needs_bridge`
names a tool the agent does not have fails and alerts rather than running half blind. If the same
routine also exists as a Claude app scheduled task, never leave both enabled: it would run twice.
Runbooks: `30-Knowledge/2026-09-15-runbook-brain-routine-auth.md`,
`30-Knowledge/2026-09-15-runbook-brain-guardian.md`.

## Running a task on demand

```bash
python3 ~/Brain/_bin/tasks.py --list          # the registry as THIS machine sees it
python3 ~/Brain/_bin/tasks.py --dry-run       # what would run right now
python3 ~/Brain/_bin/tasks.py --force <id>    # run one now, ignoring the schedule
python3 ~/Brain/_bin/guardian.py run-routine <id>
```

One definition of the work, several triggers: keep the routine's steps in one place (its routine
file or a skill) and point the scheduled row and any manual trigger at it, so a change is made once.

## Logs

- Per task: `<brain state>/logs/tasks/<id>.log`, with START/END lines, exit code, duration and every
  line of output
- The runner itself: `<brain state>/logs/tasks/_runner.log`
- Rotation at 1 MB, keeping 3 generations
- Last-run state: `<brain state>/tasks-state.json`, local to each machine and written under a lock,
  so two runs that finish together merge their results instead of losing one

`<brain state>` is `BRAIN_STATE` when set, else the per-platform directory `_bin/brain_paths.py`
resolves.

## Adding a machine

Nothing to configure in the vault: the registry is already shared. On the new machine run the first
run, accept the tasks job for its scheduler, use its `hostname -s` in the `machine` column of the rows
it should own, and check with `tasks.py --list`.

## Design notes

- A missed run is executed late, not skipped. A machine that was asleep at the scheduled time runs
  the task when it wakes.
- A failing task never kills the runner. Each command is wrapped; a non-zero exit or a timeout
  (30 min) is logged and the next task still runs.
- A task's exit code reflects a crash, not its findings: a health check that finds problems still
  exits 0 and reports them through its log and alerts.
