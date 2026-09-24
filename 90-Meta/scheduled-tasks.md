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
updated: 2026-09-21
supersedes: []
---

# Periodic task registry

The single inventory of everything that runs on a schedule across every machine running this
harness. The registry lives in the vault so every machine sees the same list, but each task
declares which machine owns it: a task pinned to one host never fires on the others.

`_bin/tasks.py` reads this table every 10 minutes, keeps only the rows matching this machine, and
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
- **machine**: `*` for every machine, or the machine that owns it: its label (`hostname -s`), its
  key (`python3 _bin/machine_identity.py` prints it) or a key it had before a rename. A row written
  with a bare hostname keeps working
- **time**: `HH:MM`, 24h, local time of that machine; `--` for manual only; or `every Nh`
  (`every 1h`, `every 6h`) for a row that repeats through the day instead of firing once. An
  interval row ignores the once-a-day mark and goes by the gap since its last run, so the same
  10-minute poll gives it its cadence: never a second scheduler of its own. An interval missed
  while the machine slept is not caught up; the next poll runs it and the clock restarts
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

Two optional front matter keys shape how a run is held:

- `single_instance: true` makes the runner hold a lock on `<brain state>/task-locks/<id>.lock` for
  the whole run. A tick that finds it still running skips it and leaves its state alone, and
  `tasks.py --force <id>` on a running one is refused with exit 75. Opt in only for a routine where
  two overlapping runs would do the same work twice (an hourly routine that may overrun its hour).
- `timeout_minutes: <n>` raises the 30-minute limit for a routine whose job has no fixed size. Pair
  it with `single_instance: true` so an overrun never overlaps the next tick.

Before any of that, the runner checks that this machine has what the routine needs
(`_bin/routine_requires.py`). What its `agent_args` already name is checked on its own: every
`--add-dir` directory, the program of every allowed `Bash(...)` command, and any script path or
`--cwd` directory inside one. Anything else goes in an optional `requires:` frontmatter line, a JSON
object next to `agent_args:`:

```yaml
requires: {"repos": [{"path": "~/code/tool", "url": "<clone url>"}], "programs": ["jq"], "paths": ["~/data"]}
```

A repo is a git checkout (a plain path, or `{"path", "url"}` so it can be cloned for you), a program
must be on PATH, a path must exist. A relative path is relative to the vault. No `requires:` line
means nothing beyond `agent_args` (the behaviour before this existed). A gap, or a `requires:` line
that does not parse, refuses the run with exit 2 before any token is read, and the alert names each
gap and its fix.

A failed run raises an alert through the guardian (desktop notification, email if a mailer was
configured at first run, log); the next successful run clears it. The runner does not refuse a
routine for its `needs_bridge`: a routine that needs a tool the agent does not have must say so in
its body and fail, and its `success_contract` turns a run that did not deliver into a failed run,
which alerts. If the same
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

Nothing to configure in the vault: the registry is already shared. On the new machine:

1. Run the first run and accept the tasks job for its scheduler.
2. Take the stable machine id for the `machine` column, not `hostname -s`. Two machines can report
   the same hostname, and a hostname can change. `tasks.py --list` prints on its second line what
   this host matches as: its hostname and its stable key (`python3 ~/Brain/_bin/machine_identity.py`
   prints the key alone). The hostname still works in the column and is easier to read, but it is
   the one that can change under you.
3. Check with `tasks.py --list` that the machine sees only its own rows as its own.

Pin an agent task to it only once `python3 ~/Brain/_bin/routine_requires.py here --fix` shows that
task ✓ there: `--fix` clones a missing repo that has a url, and a missing program is yours to install.

`tasks.py --force <id>` runs a task now but still respects the `machine` column: a task pinned to
another machine is refused (exit 3) unless `--anywhere` is passed, so a manual run cannot make a task
that posts somewhere post twice.

## Design notes

- A missed run is executed late, not skipped. A machine that was asleep at the scheduled time runs
  the task when it wakes.
- A failing task never kills the runner. Each command is wrapped; a non-zero exit or a timeout
  (30 min) is logged and the next task still runs.
- A task's exit code reflects a crash, not its findings: a health check that finds problems still
  exits 0 and reports them through its log and alerts.
