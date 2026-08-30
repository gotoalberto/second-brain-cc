---
id: 50-sessions-readme
title: 50-Sessions — per-session summaries
type: meta
area: []
projects: []
tags: [folder-guide, sessions, archival]
status: active
source: agent
provenance: "folder guide, written once to explain what lands here"
updated: 2026-08-30
supersedes: []
---

# 50-Sessions

An archival log of what each agent session did. **Machine-written** — you almost
never create or edit a note here by hand. The folder starts empty and fills up on
its own as sessions run.

Think of it as the vault's flight recorder: a cheap, deterministic trace you can
search after the fact, not a place for the durable knowledge a session produced.
Decisions, conventions and how-tos belong in `30-Knowledge/` (write them with
`/save`); project state lives in `10-Projects/`. This folder just remembers that a
session happened and roughly what it touched.

## Layout

One note per session, filed under a dated subfolder:

```
50-Sessions/
  2026-08-27/
    a1b2c3d4.md        # one session, named by its short id
  2026-08-28/
    e5f6a7b8.md
    9c0d1e2f.md
```

- The subfolder is the day the session ran (`YYYY-MM-DD`).
- The filename is the session's short id (a few hex characters).

## What a note looks like

Standard vault frontmatter with `type: session`, `source: agent`, then a running
trace the session appends to as it works:

```markdown
---
id: 2026-08-28-session-e5f6a7b8
title: Session e5f6a7b8
type: session
projects: [my-project]
status: active
source: agent
provenance: hook
updated: 2026-08-28
---

## Trace
- 14:02 · subagent `context-scout` finished
- 14:19 · subagent `librarian` finished
```

Entries are written by hooks at zero model cost — nothing here calls a model to
summarise, so it never guesses and never invents. If a session spawns no subagents
and saves nothing worth recording, it may leave no note at all. That is fine.

## Finding things

These notes are **indexed but archival**: they are never injected into a session
automatically and won't surface in an ordinary search. Reach them explicitly:

```bash
python3 _bin/query.py "some terms" --all      # includes 50-Sessions (and context packs, inbox…)
```

The `/recall --all` command does the same from inside Claude. Use it to answer
"when did we last touch this?" or "which session ran that migration?".

## Housekeeping

- **Don't hand-write notes here.** If you have something durable to record, `/save`
  it into `30-Knowledge/` instead — writes to this folder deliberately do *not*
  count as a session having "saved memory".
- **Safe to prune.** Old dated subfolders are pure history; deleting them loses only
  the trace, never a decision. Reindex afterwards with
  `python3 _bin/index_vault.py`.
- Committed and pushed by the sync daemon like the rest of the vault, so keep it
  free of anything secret — traces are terse by design, but the usual rule still
  applies.
