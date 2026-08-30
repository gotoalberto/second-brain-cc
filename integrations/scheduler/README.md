# Scheduler — periodic tasks, any model

Run recurring tasks against the vault **unattended** — a daily digest, a weekly review, an
inbox triage — driven by **any** agent or model. This is the agent-agnostic equivalent of a
cron of AI jobs: each task is a Markdown file with a cron schedule and a prompt, and the
model that executes it is a swappable command.

Zero dependencies (stdlib Python only). Nothing here stores secrets or state in the repo.

## How it works

```
one OS timer (cron / launchd / systemd)  ──►  run.py --tick  ──►  finds due tasks
                                                                  ──► hands each prompt
                                                                      to your agent command
                                                                      on STDIN
```

- A **task** is `tasks/<name>.md`: cron schedule + options in the frontmatter, the prompt in
  the body.
- One OS timer ticks `run.py --tick` every few minutes. `run.py` — not the OS — decides which
  tasks are due, using its own cron matcher with **catch-up** (a task missed while the machine
  slept runs once on wake, never N times) and **no double-fire** within a slot.
- Each due task's prompt is delivered on **stdin** to your *agent command*. That command is
  the only model-specific piece — swap it and the same tasks run on a different model.
- State (last-run per task) and per-task logs live outside the repo, in
  `~/.second-brain/scheduler/` (override with `BRAIN_SCHEDULER_STATE`).

## The agent command (this is what makes it model-agnostic)

The contract: **the task prompt arrives on stdin; run it and print any result to stdout.**
Bundled runners in [`agent-runners/`](agent-runners/) adapt each tool to that contract:

| Runner | Uses | Notes |
|---|---|---|
| `claude.sh` | Claude Code headless (`claude -p`) | Full agent: can read/write the vault. Uses your Claude Code auth. |
| `opencode.sh` | OpenCode (`opencode run`) | Full agent, any provider. Set `OPENCODE_MODEL=provider/model`. |
| `llm.sh` | [`llm`](https://llm.datasette.io) (any model) | **Bare model call, no tools** — good for pure text tasks, not for vault read/write. Set `LLM_MODEL`. |
| `generic.sh.example` | your own | Copy to `generic.sh`, wire your agent, point `BRAIN_AGENT_CMD` at it. |

Resolution order for the agent command: `--agent` flag → `$BRAIN_AGENT_CMD` → the task's own
`agent:` field → auto-detect (`claude`, then `opencode`, then `llm` on `PATH`).

```bash
export BRAIN_AGENT_CMD=$PWD/integrations/scheduler/agent-runners/claude.sh
# or opencode.sh, llm.sh, or your own generic.sh
```

`BRAIN_VAULT` is exported to the agent, so a task can locate the vault and use the
[`brain`](../cli/) CLI or the [MCP](../mcp/) tools to read and write notes.

## A task file

`tasks/example-daily-digest.md`:

```markdown
---
name: daily-digest
schedule: "0 8 * * *"     # 5-field cron, or a @macro (@daily @weekly @hourly @monthly @yearly)
enabled: false            # flip to true when you're ready to run it
timeout: 600              # seconds
# agent: /path/to/a/runner.sh   # optional: force a specific model for this task
---
Produce a short daily digest of the vault and save it as a note.
1. `brain recent 20` to see what changed.
2. Summarize it in 5–10 bullets.
3. Save it: brain new 00-Inbox/$(date +%F)-daily-digest.md --title "Daily digest" --type note --tag digest
```

The two bundled examples ship **disabled** so nothing runs (or costs tokens) until you opt in.

## Install the tick

```bash
bash integrations/scheduler/install-cron.sh            # crontab entry, every 5 min
bash integrations/scheduler/install-cron.sh --every 1  # every minute
bash integrations/scheduler/install-cron.sh --uninstall
```

Cron works on macOS and Linux. On Windows, point Task Scheduler at
`python3 …\run.py --tick`. On macOS you can use launchd instead of cron if you prefer.

## Drive it by hand

```bash
python3 integrations/scheduler/run.py --list          # tasks, schedules, last run, next due
python3 integrations/scheduler/run.py --due           # what is due right now (nothing runs)
python3 integrations/scheduler/run.py --run <name>    # run one task now, ignore schedule
python3 integrations/scheduler/run.py --tick --dry-run  # what --tick would run, no agent call
```

## Safety

- Tasks are **user-authored** — the scheduler only delivers their text to your agent. Vault
  content stays DATA, not instructions (the preamble says so to the agent).
- First sight of a task **registers** it and starts firing at its *next* occurrence, so
  installing never triggers a stampede of catch-up runs.
- A file lock means overlapping ticks never double-run a task.
- Failures are logged (`~/.second-brain/scheduler/logs/<task>.log`) and the run is recorded,
  so a broken task doesn't retry every tick — it waits for its next slot.

## Notes

- Requires Python 3.8+. The cron matcher supports `* , - /` and `@macros`; day-of-month and
  day-of-week use Vixie semantics (if both are restricted, either match fires).
- This is the generic engine. The reference implementation's private variant used
  Claude Code's own task MCP; here the same idea is reduced to files + cron + a stdin
  contract so it runs on anything.
