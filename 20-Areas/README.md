# 20-Areas

Ongoing **areas of responsibility** — the parts of your work and life that never "finish". Unlike a project, an area has no end date and no done state; you just keep tending it. Examples: `infrastructure`, `hiring`, `personal-finance`, `home`, `open-source-maintenance`.

Each note here is an **entry point**. It holds very little content of its own — instead it links out to the projects, knowledge notes, and entities that live under that area, so you can open one file and see the whole territory at a glance.

## Area vs. project

- **Project** (see `10-Projects/`) — has a goal and an end. "Migrate the API to v2", "Launch the pricing page". When it ships, it's done.
- **Area** (here) — has a standard to maintain, not a finish line. "Keep the infrastructure healthy", "Stay on top of hiring". It outlives any single project.

Rule of thumb: if you can imagine crossing it off a list, it's a project. If you'll still be responsible for it next year, it's an area.

## What a note looks like

An area note is mostly links. Keep it thin and let the graph do the work.

```markdown
---
id: area-infrastructure
title: Infrastructure
type: area
area: [infrastructure]
projects: []
tags: [ops]
status: active
source: user
provenance: created 2025-01-04 as the infra entry point
updated: 2025-01-04
---

# Infrastructure

Everything that keeps the systems running: hosting, CI, backups, monitoring.

## Active projects
- [[project-api-v2-migration]]
- [[project-backup-overhaul]]

## Key knowledge
- [[2025-01-04-decision-hosting-provider]]
- [[2025-01-02-howto-restore-from-backup]]

## People & systems
- [[entity-acme-cloud]]
- [[entity-alice]]  <!-- owns on-call -->
```

Wikilink targets are another note's basename. Dateless slugs like `[[entity-alice]]` resolve to the dated file for you.

## Conventions

- One file per area, named for the area (`infrastructure.md`, `hiring.md`).
- `type: area` in the frontmatter; `status: active` while you still own it, `superseded` when you hand it off or fold it into another.
- Prose is optional and brief. The value is in the outbound links — treat this as a dashboard, not an essay.
- Anything durable (a decision, a how-to) belongs in `30-Knowledge/`; link to it from here rather than writing it here.

## Finding and searching

Reindex and search from the vault root:

```bash
python3 _bin/index_vault.py          # rebuild the search index
python3 _bin/query.py "infrastructure"   # find area notes and what links to them
```

Area notes are written by hand — no protected-write tool required. (Notes in `10-Projects/` and `70-Entities/` go through `_bin/vw.py`; area notes don't.)
