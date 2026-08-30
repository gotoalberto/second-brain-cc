---
id: 2026-01-15-entity-alice-example
title: Alice Example
type: entity
area: [team]
projects: [my-project]
tags: [entity, person, teammate, example]
status: active
source: agent
provenance: 2026-01-15 seeded as an example entity note so newcomers can see the shape of a person node
updated: 2026-01-15
---

# Alice Example

> [!note] This is an EXAMPLE note, not a real person.
> "Alice Example" is a fictional placeholder used to show what an entity note
> looks like. Every detail below is invented and generic. Delete this note (or
> replace it with a real teammate) once you understand the shape. Real entity
> notes are written only via `python3 _bin/vw.py`, never by hand.

## Who

Alice Example is a fictional **teammate** — a backend engineer on the
[[project-my-project]] project. She is the person other notes point to when they
mention "Alice", so decisions, sessions and meetings can link to a single node
instead of repeating her details.

- **Role:** Backend engineer / teammate
- **Works on:** [[project-my-project]]
- **Area:** team
- **Timezone:** placeholder (e.g. UTC+1)
- **Contact:** use a placeholder here (e.g. `alice@example.com`) — never a real
  address. Prefer storing any real contact detail outside the vault.

## Context

Alice owns the ingestion service on [[project-my-project]] and is the usual
reviewer for changes to the pipeline conventions described in
[[convention-example]]. When a session touches that service, link back here so
the graph shows who was involved.

## Links

- Project: [[project-my-project]]
- A decision she was part of: [[decision-example]]
- A convention she maintains: [[convention-example]]

## Notes

Keep entity notes short and factual: who the person is, what they work on, and
the wikilinks that connect them to projects, decisions and sessions. Put durable
knowledge in `30-Knowledge/`, not here. This file exists only to demonstrate the
format — swap in a real teammate (via `_bin/vw.py`) or remove it.
