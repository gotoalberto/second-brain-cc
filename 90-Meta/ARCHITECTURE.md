---
id: ARCHITECTURE
title: Architecture of the Brain system
type: howto
area: [personal-infra]
projects: [brain]
tags: [architecture, hooks, agentes, sqlite, worktree]
status: active
confidence: high
source: agent
provenance: "implementation session 2026-08-20"
updated: 2026-09-15
supersedes: []
---

## The flow of a session

1. **SessionStart** → `compass.py` injects the protocol, active projects and a warning
   if another session is on the same project. The cap (`MAX_TOKENS`, 1600) only warns,
   it never trims. See [[2026-09-10-decision-startup-budget-warns-never-trims]].
2. **UserPromptSubmit** → `retrieve.py` injects ≤250 tokens of pointers (title + path).
   Cap of 4,000 per session, dedupe by note, silence on trivial or continuation
   prompts: pointers, not context. Every prompt also checks
   the link graph and launches `linkfix.py` when a link can be repaired; what it cannot
   repair is shown to the agent. See [[2026-09-10-decision-every-search-finds-and-fixes-broken-links]].
3. **/task** → `context-scout` writes a Context Pack into `60-Context-Packs/` and returns
   only its path; the executor reads it in one go and starts with a clean window.
4. Work happens in an **isolated worktree**; `seed_worktree.py` copies `.env`, assigns a
   port of its own and seeds the pack.
5. **Stop** → `gate_memory.py` blocks closing without saving (it blocks exactly once).
6. **SessionEnd** → releases claims and marks `.dirty`. **No session touches git.**
7. **The scheduler** (launchd, systemd or cron) every 10 min → `vault_sync.py`: reindexes, scans for
   secrets, commits, pushes. Other jobs run the guardian, the file watch and the routines, with no
   agent involved. See [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]].

## Structural decisions

- **All shared state in one SQLite with WAL** (`_index/vault.db`): FTS5 notes,
  sessions, claims, injected, metrics. One concurrency mechanism instead of
  several JSON files with homemade locks.
- **python3 stdlib only**: `rg` does not exist on this machine (it is a shell function
  in the Claude Code sandbox, not a binary), and launchd starts with a minimal PATH.
- **Fail-open**: every hook exits 0 on any error. A failure of the system degrades the
  session to "plain Claude", it never breaks it. Kill switch: `BRAIN_OFF=1`.
- **Prompts are sanitized before they touch FTS5**: raw, 4 out of 5 real prompts
  throw OperationalError (question marks, parentheses, quotes, a bare AND).
- **A session's life is measured by its Claude Code process, with the heartbeat as a
  backstop**: the PID a hook sees is the hook's own and dies in milliseconds, so
  `brainlib.claude_session_pid()` climbs the process tree to the long-lived Claude Code
  process and stores that. A finished session is purged at once; rows with no PID fall
  back to the heartbeat window. The same PID identifies which session is running a
  command (`current_sid`), and when it cannot be known, `claim.py --release` refuses
  rather than guess.
- **The secrets gate excludes files from the commit, it does not move them**: moving is
  destructive; blocking the whole vault over one file is worse.

## File map

| File | Role |
|---|---|
| `_bin/brainlib.py` | core: DB, FTS sanitizing, secret redaction, locks, atomic writes |
| `_bin/compass.py` `retrieve.py` | the two read hooks (T0, T1) |
| `_bin/gate_write.py` `gate_memory.py` | the two deliberate gates (the only ones that exit with code 2) |
| `_bin/vw.py` | the only write path to shared notes |
| `_bin/query.py` `claim.py` | CLI for the agents |
| `_bin/linkfix.py` | finds and repairs broken `[[links]]`; runs on every search |
| `_bin/vault_sync.py` | daemon: the only process that touches git; refreshes the plugin before committing |
| `_bin/protocol_budget.py` | ceiling on the startup context: single source of the budget |
| `_bin/protocol_guard.py` | hook: warns as the protocol grows, not sessions later |
| `_bin/build_plugin.py` | refreshes the vault's Claude Code plugin before a commit |
| `_bin/install_plugin.py` | three-way sync of skills and agents between the vault (canonical) and `~/.claude`, with backups |
| `_bin/kp.py` | credentials: a wrapper over `keepassxc-cli` for a local `.kdbx` |
| `_bin/google.py` | named Google accounts, each with its OAuth client and refresh token in the kdbx |
| `_bin/guardian.py` | repairs generated wiring and scheduler jobs, proves hooks fire, alerts |
| `_bin/brain_watch.py` | file watch, git hooks and generation of agent wiring from `90-Meta/events.json` |
| `_bin/tasks.py` | scheduled tasks and agent routines with a token pool |
| `_bin/doctor.py` | health report (`/vault-doctor`) |
| `bootstrap.sh` | installer for a new machine (see `README.md`) |

## Links
- [[2026-09-10-decision-every-search-finds-and-fixes-broken-links]]
- [[2026-09-10-decision-startup-budget-warns-never-trims]]
- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
- [[2026-09-15-runbook-brain-events]]
- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-08-20-decision-credentials-in-keepass]]
