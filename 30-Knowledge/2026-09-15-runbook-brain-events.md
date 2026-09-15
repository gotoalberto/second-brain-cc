---
id: 2026-09-15-runbook-brain-events
title: Runbook for the event layer
type: howto
area: [harness]
projects: []
tags: [events, registry, file-watch, git-hooks, mcp, cli, agent-adapter, heartbeat, runbook]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## What this covers

The vault's events belong to the vault. An AI agent carries **generated wiring** that triggers
them (Claude Code's hooks are the first adapter), and several triggers fire with no agent at all.
The guardian repairs generated wiring when it drifts: [[2026-09-15-runbook-brain-guardian]].

Commands below are the shape of the tools; `--help` on each script is authoritative.

## The registry

`90-Meta/events.json` names every event, the `_bin` module that implements it and every trigger
wired to it. `_bin/events_core/domain.py` validates it: unknown trigger kinds, handlers outside an
explicit allowlist and incomplete triggers are rejected, so a typo fails loudly. Everything else is
generated from the registry, so nothing names the mapping twice:

| generated | by | from |
|---|---|---|
| Claude Code `hooks.json` in the plugin | `brain_watch.py generate` | `claude-hook` triggers |
| `githooks/pre-commit`, `githooks/post-commit` | `brain_watch.py generate` | `git-hook` triggers |
| `AGENTS.md`, `CLAUDE.md` at the vault root | `gen_instructions.py` | the registry and `90-Meta/PROTOCOL-COMPACT.md` |
| `90-Meta/HOOKS-WITHOUT-CLAUDE.md` | `gen_instructions.py` (`--check` for drift) | the registry |
| what each file-watch tick runs | `brain_watch.py tick` | `file-watch` triggers |

Generators write only when content changes, so a generated file's mtime settles.

Every event with a `claude-hook` trigger declares a `liveness` class: `session` (expected in every
session that finished a turn), `regular` (expected within a week of normal use) or `conditional`
(only when its situation arises). The guardian's hook liveness check reads it.

Every hook handler records a heartbeat: one JSON line per run in `<brain state>/logs/heartbeat.jsonl`
with the event id, status, exception class, exit code and duration. It is written even when the hook
fails, and never changes the hook's behaviour if the log cannot be written.

**To add an event:** add it to `events.json` with an approved handler (extend the allowlist in
`events_core/domain.py` if the module is new), run `brain_watch.py generate` and
`gen_instructions.py`, give the handler its heartbeat decorator, and run the `events_core` tests. An
event with a `claude-hook` trigger and no other equivalent gets a `cli` trigger, `brain hook <id>`.

## Triggers that need no agent

- **File watch.** A scheduled job runs `brain_watch.py tick` every minute. Each tick compares mtimes
  under the watched folders with the previous tick: a changed note reindexes, an added or removed
  note relinks, and any change restarts a debounce after which `vault_sync.py --hook` commits. It
  never watches `80-Private/`, `60-Context-Packs/` or `_index/`. The same tick checks that the agent's
  hook wiring is still present and triggers a hooks-only repair when it is not (at most every few
  minutes), and runs a cheap hook liveness pass.
- **Git hooks.** `githooks/` is versioned. `brain_watch.py install` points a clone's
  `core.hooksPath` at it, once per clone; the guardian checks and restores that one key.
  - `pre-commit` **blocks** only when staged content looks like a credential. It **warns** when a
    staged change to `10-Projects/` or `70-Entities/` did not go through `vw.py`.
  - `post-commit` marks the index dirty.
  - `git commit --no-verify` skips the secret scan too, and a credential committed that way reaches
    the remote. Use it only when the scan is wrong.
- **MCP server.** `integrations/mcp/server.py`, for any MCP client.
- **CLI.** `integrations/cli/brain`, for any shell. `brain hook <event-id>` runs an event's handler
  with the payload a Claude Code hook would get.

## Sessions without an agent

Every trigger resolves one session identity: `BRAIN_SESSION_ID` when a wrapper exported it (the CLI
and the MCP server each export their own), else the agent's session process, else `system`. Writes no
session owns are credited to `system` rather than to an invented session.

## What is lost with no agent adapter

`AGENTS.md` carries this table for the agent reading it. The decisions behind it:

- **Stop memory gate.** Nothing can block a session from ending unsaved. The file watch compensates by
  detection and alert, never by blocking: files changed for hours with no note saved, or vault changes
  left unsynced, raise an alert through the guardian's channels and clear once resolved.
- **Per-session attribution** degrades to `system`.
- **Pre-write gate.** A raw write is caught at commit time, not when it happens. A write that is never
  committed is not caught.
- **Subagent log and worktree seeding** are agent concepts with no generic equivalent.

## Skills and agents

The vault copy under `integrations/claude-code/plugin/brain/` is canonical and `~/.claude/` holds
installed copies. `_bin/install_plugin.py` keeps them in step three way, backing up everything it
replaces. [[2026-09-12-convention-back-up-a-skill-before-rewriting-it]]

## State outside the agent's directory

Brain state (logs, the task runner's state, caches, the guardian's queue and alerts) lives in the
Brain state directory, never under `~/.claude`. `BRAIN_STATE` overrides it and
`python3 ~/Brain/_bin/brain_paths.py` prints it. A machine that still has older state under
`~/.claude/state/brain` keeps working; `_bin/migrate_state.py` moves it (status, dry run, migrate,
rollback), with a backup first.

## Smoke checks after install

Run them with a scratch `HOME`, `BRAIN_VAULT` and `BRAIN_STATE` wherever possible.
[[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]

1. `brain_watch.py tick` twice: the second tick runs nothing.
2. Touch a note and tick: the index moves; after the debounce a tick commits.
3. `brain_watch.py install` in a scratch clone: `core.hooksPath` is `githooks`.
4. In that clone, commit a file containing a fake key: rejected with the explanation.
5. In that clone, edit a `10-Projects/` note by hand and commit: the warning shows, the commit lands.
6. Drive the MCP server with the handshake in its README, read-only tools.
7. `gen_instructions.py --check` exits 0; `brain hook session-start` prints the startup context and
   adds a heartbeat line.
8. `install_plugin.py status` before the first `sync`: review every back-port and conflict.

## Links

- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
