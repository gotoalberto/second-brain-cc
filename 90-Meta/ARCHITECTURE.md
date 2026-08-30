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
updated: 2026-08-20
supersedes: []
---

## The flow of a session

1. **SessionStart** → `compass.py` injects ≤900 tokens: protocol, active projects,
   skills catalog and a warning if another session is working on the same project.
2. **UserPromptSubmit** → `retrieve.py` injects ≤250 tokens of pointers (title + path).
   Cap of 4,000 per session, dedupe by note, silence on trivial or continuation
   prompts. See [[2026-08-20-decision-pointers-not-context]].
3. **/task** → `context-scout` writes a Context Pack into `60-Context-Packs/` and returns
   only its path; the executor reads it in one go and starts with a clean window.
4. Work happens in an **isolated worktree**; `seed_worktree.py` copies `.env`, assigns a
   port of its own and seeds the pack.
5. **Stop** → `gate_memory.py` blocks closing without saving (it blocks exactly once).
6. **SessionEnd** → releases claims and marks `.dirty`. **No session touches git.**
7. **launchd** every 10 min → `vault_sync.py`: reindexes, scans for secrets, commits, pushes.

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
- **A session's life is measured by heartbeat, never by PID**: the PID a hook sees
  is the hook's own, and it dies in milliseconds. See [[2026-08-20-decision-heartbeat-not-pid]].
- **The secrets gate excludes files from the commit, it does not move them**: moving is
  destructive; blocking the whole vault over one file is worse. See [[2026-08-20-howto-vault-secrets]].

## File map

| File | Role |
|---|---|
| `_bin/brainlib.py` | core: DB, FTS sanitizing, secret redaction, locks, atomic writes |
| `_bin/compass.py` `retrieve.py` | the two read hooks (T0, T1) |
| `_bin/gate_write.py` `gate_memory.py` | the two deliberate gates (the only ones that exit with code 2) |
| `_bin/vw.py` | the only write path to shared notes |
| `_bin/query.py` `claim.py` | CLI for the agents |
| `_bin/vault_sync.py` | daemon: the only process that touches git; refreshes the plugin before committing |
| `_bin/protocol_budget.py` | ceiling on the startup context: single source of the budget |
| `_bin/protocol_guard.py` | hook: warns as the protocol grows, not sessions later |
| `_bin/build_plugin.py` | dumps `~/.claude` (agents, whole skills, hooks) into the vault's plugin |
| `_bin/selftest.py` | regression harness; run it after touching anything under `_bin/` |
| `_bin/doctor.py` | health report (`/vault-doctor`) |
| `bootstrap.sh` | installer for a new machine (see `README.md`) |

## Links
- [[2026-08-20-project-brain-memory-system]] — project status
