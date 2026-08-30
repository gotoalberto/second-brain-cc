# 70-Entities

One note per **person, company, or system** you keep coming back to. These are the
nodes of the graph: the stable targets that projects, decisions and session notes point
at with `[[wikilinks]]`. A project links to `[[entity-acme]]` instead of spelling out
who Acme is every time, and the entity note is the one place that answers "who/what is
this, and what do we know about it".

Keep one note per real thing — a teammate, a vendor, a client, an internal service, an
external API. When five notes mention the same system, they should all link to the same
entity note, not restate it.

## What a note here holds

- **Who or what it is** — a person, an organization, or a system/service.
- **Role / relationship** — how it connects to your work (collaborator, dependency,
  provider, downstream consumer).
- **Durable facts** — the things that stay true across projects; not today's status.
- **Links out** — to the projects and knowledge notes that touch this entity.

Frontmatter uses `type: entity`. Example skeleton:

```yaml
---
id: entity-acme
title: Acme (vendor)
type: entity
area: [partners]
projects: [my-project]
tags: [vendor, api]
status: active
source: agent
provenance: "first mentioned while wiring up the my-project integration"
updated: 2026-01-15
---
```

## Naming and linking

Give each note a **dateless slug** basename so links stay short and predictable:
`entity-alice`, `entity-acme`, `entity-billing-service`. Other notes then link with
`[[entity-alice]]`, and that wikilink resolves to the file regardless of any date the
index adds. Prefer a stable slug over the display name — the title can read
`Alice (design lead)`, but the link target stays `entity-alice`.

## Written only via `_bin/vw.py`

Like `10-Projects/`, entity notes are **protected**: create and update them through the
vault-writer, never with a raw editor.

```bash
python3 _bin/vw.py new 70-Entities/entity-acme.md --title "Acme (vendor)" --type entity
echo "Now handles our outbound webhooks." | python3 _bin/vw.py append 70-Entities/entity-acme.md
```

`vw.py` redacts anything that looks like a credential, locks per file so parallel
sessions don't collide, and writes atomically. On a shared setup these notes are also
leased, so a second machine appends into a linked note rather than fighting a merge
conflict.

## Finding them

```bash
python3 _bin/query.py "acme webhook"     # search across the vault
python3 _bin/index_vault.py              # reindex after bulk edits
```

## Keep it generic and clean

This folder holds relationship notes, not a contact dump. **No secrets, no credentials,
no private personal data** — a password or token belongs in 1Password (referenced as a
`op://` pointer), never in the body of an entity note. Record what helps you work with
the entity, and let the durable facts accumulate over time.
