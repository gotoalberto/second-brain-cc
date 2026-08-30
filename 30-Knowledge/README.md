# 30-Knowledge — durable notes

This is where the memory actually lives. Everything else in the vault points here.

A note belongs in `30-Knowledge/` when it is **durable and reusable**: a decision worth
remembering, a convention the team follows, a how-to you'd otherwise re-derive, or a
reference you'll look up again. If it only mattered for one session, or it already lives
in the code and in git, it doesn't belong here.

## What goes here

- **Decisions** — what was decided, the alternatives, and *why*. The "why" is the point;
  it's what git history won't tell you six months later.
- **Conventions** — how we do a thing here: naming, layout, the shape of a commit message.
- **How-tos** — a repeatable procedure someone will follow again.
- **References** — a distilled summary of something external (never a verbatim copy).

## File naming

Dated, kebab-case, describing the note — not the date alone:

```
30-Knowledge/2026-01-14-decision-postgres-over-sqlite.md
30-Knowledge/2026-02-03-convention-branch-naming.md
30-Knowledge/2026-02-20-howto-rotate-api-keys.md
```

The date prefix orders the folder chronologically and keeps filenames unique. A dateless
wikilink like `[[decision-postgres-over-sqlite]]` still resolves to the dated file.

## Frontmatter is mandatory

No frontmatter, no index — the note won't be found. Every note opens with the YAML
contract (see `90-Meta/templates/`):

```yaml
---
id: 2026-01-14-decision-postgres-over-sqlite
title: Use Postgres instead of SQLite for the API
type: decision            # decision | convention | howto | reference | analysis
area: [backend]
projects: [my-project]
tags: [database, storage]
status: active            # active | superseded
source: agent             # user | agent | external
provenance: "session 2026-01-14 — chose Postgres when concurrency became the bottleneck"
updated: 2026-01-14
---
```

Then a short body. For decisions, the useful shape is: **What was decided → Alternatives
considered → Why → What to revisit if it changes.**

## How to write and link

- New notes here are plain `Write` — this folder is *not* protected, unlike
  `10-Projects/` and `70-Entities/` (those go through `_bin/vw.py`).
- Weave the note into the graph with `[[wikilinks]]` — link the entities, projects and
  decisions it touches, e.g. `[[entity-acme]]`, `[[my-project]]`.
- **Never delete.** When a note is wrong or outdated, set `status: superseded` and link
  to the note replacing it. History is part of the memory.
- **Never paste external content verbatim.** Summarize it and mark `source: external`.

## After writing

Reindex so the note is searchable, then find it again:

```sh
python3 _bin/index_vault.py           # rebuild the FTS5 index
python3 _bin/query.py "postgres"      # search across the vault
```

That's it — write it clearly enough that a stranger (or you, next quarter) can act on it
without re-asking.
