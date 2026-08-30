# 10-Projects

One note per **active project** — a piece of work with an end state you are driving toward. Each note captures the current status, the open decisions, and what is still left to do, so any session (human or agent) can pick the project back up without re-deriving context.

If a responsibility is ongoing and has no finish line (keeping the docs healthy, running the on-call rotation), it belongs in `20-Areas/`, not here. A project graduates out of this folder when it ships or is abandoned — mark it `status: superseded` and let the session summary in `50-Sessions/` carry the history.

## The one rule: never edit these by hand

Project notes are **protected**. Do not open them in an editor or write them with `Write`/`Edit`. Every change goes through the vault writer:

```bash
python3 _bin/vw.py
```

`vw.py` keeps the frontmatter contract intact, stamps `updated`, records `provenance`, and reindexes so the note stays findable. Hand-edits drift out of the schema and silently break search — that is why the tool owns this folder.

## What a project note holds

- **Status** — one line: where the work stands right now (`active`, blocked on X, waiting on review).
- **What's left** — the concrete open items, most actionable first.
- **Decisions** — what was chosen and *why*, with the alternatives that were rejected. Durable decisions can also live as their own note in `30-Knowledge/`; link to them.
- **Links** — wikilink out to the people, systems, and companies in `70-Entities/`, and to related knowledge notes, so the project sits inside the graph.

## Frontmatter

```yaml
---
id: proj-my-project
title: My Project
type: project
area: [platform]
projects: [my-project]
tags: [backend, migration]
status: active          # active | superseded
source: agent
provenance: created 2026-01-15 while scoping the migration
updated: 2026-01-15
---
```

## Example

```markdown
# Acme API Migration

Status: active — auth service cut over, billing endpoints still on the old host.

## What's left
- Point billing endpoints at the new gateway
- Delete the legacy `acme-old` credentials once traffic is drained
- Write the runbook and hand it to [[entity-alice]]

## Decisions
- Chose a gradual per-endpoint cutover over a big-bang switch — smaller blast
  radius, easier rollback. See [[2026-01-10-migration-strategy]].
```

Slugs like `[[entity-alice]]` resolve to the dated file in `70-Entities/`; you link by basename, not full path.

## Working with projects

```bash
python3 _bin/query.py "acme migration"   # find the note
python3 _bin/vw.py                        # create or update one (the only writer)
python3 _bin/index_vault.py               # reindex if search looks stale
```

Keep it to one project per note, keep the status line honest, and let `vw.py` do the writing.
