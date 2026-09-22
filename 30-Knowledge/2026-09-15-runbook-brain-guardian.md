---
id: 2026-09-15-runbook-brain-guardian
title: Runbook for the guardian
type: howto
area: [harness]
projects: []
tags: [guardian, scheduler, hooks, hook-liveness, heartbeat, alerting, repair, runbook]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## What the guardian does

The guardian keeps the vault's machinery wired and speaks up when it is not. It runs with no AI agent
at all: the scheduler (launchd, systemd or cron) starts `guardian.py repair` every 15 minutes,
whether or not any agent app is open and whichever account is logged in.

Commands below are the shape of the tool; `guardian.py --help` is authoritative.

## What it watches

| section | a problem | repairable |
|---|---|---|
| agents | an installed agent's wiring differs from the vault's (a hook missing, broken, duplicated, under the wrong matcher, or pointing at a vault script that no longer exists; a skill or agent to install or back-port) | wiring yes; a missing canonical script or an unparseable config no |
| scheduler | a job from the vault's templates not installed, not loaded, drifted from its template, or whose last run failed | install, load, reinstall |
| interpreter | the python3 the hooks run on does not start | no |
| vault | commits unpushed for hours, no upstream, index not rewritten for a day | no |
| githooks | the vault's `core.hooksPath` is not `githooks`, or a hook file is missing or not executable | the key and execute bits yes |
| token pool | an agent routine's token refused, malformed, resting after a limit, near expiry or expired | no |
| permissions | a routine whose arguments would give an unattended run unrestricted permissions | no |
| app tasks | a Claude app scheduled task enabled on this machine with no registry row (warn), with a row naming another machine (fail: it runs twice), or whose row disagrees about `enabled` (warn) | no: the app's tasks are changed by hand |
| hook liveness | hooks that do not fire or keep failing (see below) | no |
| hook probe | a canonical hook, run in a scratch state, exits wrong, times out or prints broken output | no |
| raised | alerts other processes raised: a failed routine, the file watcher's detections | no |
| mail | email alerts stuck in the outbox for hours | no |

## Commands

```sh
python3 ~/Brain/_bin/guardian.py status             # everything it watches; changes nothing
python3 ~/Brain/_bin/guardian.py check              # look and alert; exit 0 ok, 1 warn, 2 fail
python3 ~/Brain/_bin/guardian.py repair             # rewire, install jobs, check, alert, notify changes
python3 ~/Brain/_bin/guardian.py repair --hooks-only --settings ~/.claude/settings.json
python3 ~/Brain/_bin/guardian.py run-routine <id>   # run one routine now
```

## Exit codes

- `check` is for a person or a script asking "is anything wrong?": 0 ok, 1 warn, 2 fail.
- `repair` is what the scheduler runs. It exits 0 when the run completed, whatever it found, and
  non-zero only when its own repair work errored. Findings reach you through `status`, the
  notification, the email (only for what needs a person) and the log, never through the job's exit
  status. The probe for failed
  job runs never reports the guardian's own job.
  [[2026-09-15-convention-scheduled-job-exit-code-should-reflect-crash-not-findings]]

Logs live under `<brain state>/logs/`. Nothing the guardian writes goes under `~/.claude` except the
settings file it repairs, which it backs up first.

## How repair decides what to touch

- **Agents are adapters.** The Claude Code adapter is the only guardian module that knows
  `~/.claude`. It compares the hooks in `settings.json` with the vault's generated `hooks.json`.
  Another agent is another adapter.
- **Merge, never clobber.** A hook belongs to the vault when its script and arguments appear in the
  canonical file. Only those are added, fixed, moved or de-duplicated. Every other hook, event and
  key stays as it was.
- **Stale vault hooks are removed.** The one removal: a hook that runs a path under the vault's
  `_bin/`, `githooks/` or `integrations/` that does not exist and that the canonical file does not
  list. A hook outside the vault is never removed.
- **Skills and agents** go through `install_plugin.py`'s three-way sync.
- **Backup first.** The settings file is copied before any change; a file that does not parse is
  reported and left alone.
- **Scheduler units are rendered from the vault's templates** with this machine's paths. A drifted
  unit is backed up, rewritten and reloaded. The guardian does not reload its own job while running as
  that job; it asks for a repair from a terminal.
- **Git hooks: one key.** It reads and writes only `core.hooksPath`, only in the main repository's
  config, found with `git rev-parse --git-common-dir`. No other git config key is ever written.

## Hook liveness

Wired is not enough. A hook can sit in the settings and never run, or run and fail on every event,
and no agent would say so. The guardian proves the hooks fire and succeed, deterministically, with no
model in the loop.

- **Heartbeats.** Every hook handler writes one JSON line per run to `<brain state>/logs/heartbeat.jsonl`
  (event id, short session id, `ok`, `blocked`, `off` or `error`, exception class, exit code,
  duration), in a `finally`, so a failing hook still leaves its line. Only a run that received a hook
  payload writes one; a person at a terminal or a program importing the script writes nothing.
- **Sessions.** Each Claude Code session writes a transcript under `~/.claude/projects/`. The guardian
  matches recent transcripts with heartbeats. Sessions under temporary directories and the probe's own
  session are ignored. A session whose transcript records a `hook_cancelled` attachment for
  SessionStart is not held to the session-start heartbeat: an unattended SDK run can have Claude Code
  cancel SessionStart as the queued prompt starts, which kills the hook before it writes its line.
  [[2026-09-17-analysis-cancelled-session-start-hooks-in-unattended-runs]]
- **The epoch.** Liveness starts at the first `check` or `repair` after install; sessions that started
  earlier are never judged.
- **The rules.** A session active in the last 30 minutes, past a short grace period, with no heartbeat
  at all raises `hooks:not-firing` (fail). Three of an event's last five heartbeats being errors raises
  `hooks:failing:<event>` (fail). A `session` class hook missing from a session that finished a turn,
  or a `regular` hook with no heartbeat for 7 days while others fired, raises `hooks:silent:<event>`
  (warn). `conditional` hooks are never called silent. Windows can be tuned in an optional
  `90-Meta/hook-liveness.json`.
- **The probe.** Heartbeats need a session; the probe needs nothing. For every canonical hook it runs
  the exact command with the stdin that event would get, under a probe session id, in a scratch
  directory created for the run: `HOME`, `BRAIN_STATE`, `BRAIN_VAULT` and `TMPDIR` point inside it,
  network side effects are switched off, git cannot find a repository above it, and the environment is
  built from scratch. It passes on the right exit code, well-formed output, no denial of a harmless
  write, and non-empty context from the session-start hook. It catches a dead interpreter, a broken
  import or a syntax error before any session hits it.
- **The file watch** runs the same rules in a cheap mode every few minutes (active window only, no
  probe), so a dead hook is seen within minutes.
- **Session-start notice.** While the guardian holds an open problem, the startup context gets a short
  health block with the top findings and the command to see the rest. It reads cached state only.
- **What to do.** A probe failure: run the command in the finding by hand with a payload
  (`brain hook <event id>`) and fix the script or interpreter. `hooks:not-firing`: check the hooks block
  in the settings (`repair --hooks-only` rewires it) and whether that session was started with other
  settings. `hooks:failing:<event>`: the exception class is in the finding and the error log has the
  frame. `hooks:silent:<event>`: check the hook is still wired under the right matcher.

## Alerts

- A problem is announced on the desktop when it appears, when it escalates from warn to fail, and when
  it resolves. While it stays open the guardian is quiet, apart from one daily digest.
- A repair that changed something always notifies the desktop, once per run. A repair with no changes
  never does. The same breakage an hour later notifies again, because something keeps breaking it.
- Three channels, two bars. The **desktop notification** says only how many items were repaired and how
  many problems are open, because a screen may be shared or recorded. The **log** and
  `guardian.py status` keep everything, with every backup path.
- The **email** is only for a problem a person must fix: a fail still open after this run's repair was
  attempted. It is sent once when that fail first becomes mail-worthy, then at most one digest a day
  while any stays open. A repair that worked, a problem that resolved, a warn: desktop only, never mail.
  A `hooks:probe:*` fail becomes mail-worthy only when it is still open on the next run, because probe
  timeouts have been seen to clear by themselves within one cycle.
  [[2026-09-20-decision-guardian-mail-only-for-findings-a-person-must-fix]]
  [[2026-09-16-decision-guardian-hook-probe-timeout-not-reproducible-debounce-added]]
- Email goes through the account and address chosen during the first run. Every message is queued
  first and sent from the queue, so a missing token, a locked KeePass or no network only delays it. The
  queue is capped in size and age, so re-enabling mail after an outage does not send a flood.
  [[2026-09-15-decision-first-run-asks-before-connecting-accounts]]

## Routines through any agent

Routines are rows in `90-Meta/scheduled-tasks.md` with a procedure file in `90-Meta/routines/`.
`tasks.py` hands a `type: agent` routine to the command template in `90-Meta/agent-command.txt`
(`BRAIN_AGENT_CMD` overrides it). Swapping the agent, account or model is editing that line. A failed
run raises `routine:<id>` and the next success clears it. Authentication, framing and success
contracts are in [[2026-09-15-runbook-brain-routine-auth]].

**Enabling a routine:** install the agent CLI, store a routine token, disable any duplicate of the same
routine inside an agent app so it does not run twice, then set the row's `enabled` to `yes`.

**Overlapping runs:** two runs can overlap (a forced run and the scheduled tick). Each records only the
tasks it ran, under an exclusive lock on the state file, re-reading and merging before an atomic
rename. A save that cannot get the lock in time records nothing and says so in the runner log.

## Smoke checks after install

Use scratch paths for anything that writes state.
[[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]

1. `guardian.py status` prints findings and changes nothing.
2. `guardian.py check` twice: the second run does not notify again.
3. In a scratch settings file, point one vault hook at a nonexistent script: `check` reports it,
   `repair --hooks-only --settings <scratch file>` removes it and restores the canonical hook, and a
   second repair changes nothing.
4. Remove all vault hooks from a scratch settings file and repair: one notification, no email (the
   repair fixed it), and `status` lists every restored hook and the backup path; the next run is
   silent.
5. `git -C ~/Brain config --get core.hooksPath` prints `githooks`.
6. The scheduler shows the guardian job loaded with last exit 0 even while `status` shows an open
   warning.
7. With the network off, trigger a fail repair cannot fix (a dead routine token): the email waits in
   the queue and goes out once the network is back.
8. Open an agent session, send one prompt, let the turn end: the heartbeat log shows session-start,
   prompt-submit and stop lines for that session, and `status` shows the probe passing.
9. In a scratch copy of `_bin`, append a syntax error to the startup hook and run the probe against the
   copy: exactly one probe finding naming the syntax error.

## Links

- [[2026-09-15-runbook-brain-events]]
- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-08-30-convention-health-check-must-not-depend-on-own-traffic]]
- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
