---
id: 2026-01-17-howto-example-add-a-skill
title: How to add a new skill to 40-Skills
type: howto
area: [meta, tooling]
projects: [my-project]
tags: [skills, catalogue, workflow, example]
status: active
source: agent
provenance: "session 2026-01-17 — example how-to written while documenting the skills-catalogue workflow"
updated: 2026-01-17
---

# How to add a new skill to 40-Skills

> **Example note.** This is a neutral, illustrative procedure. The skill name
> (`greet`) and paths below are placeholders — swap in your own.

A *skill* is a packaged routine an agent can invoke (a slash-command like `/task`,
or a plugin action). The `40-Skills/` folder is the vault's **catalogue** of them:
it answers "what can this setup do, and how do I trigger it?" The catalogue is
**auto-generated** — you add a skill by installing it where the generator can find
it, then rebuilding the index. You do not hand-write the catalogue notes.

## Before you start

- Decide the skill's **scope**: `user` (your personal skills), `plugin` (shipped by
  an installed plugin), `vault` (lives inside this repo), or `project` (scoped to
  the current project). The scope decides *where the `SKILL.md` goes*.
- Have a one-line summary of what the skill does and when it should trigger.

## Steps

### 1. Create the skill's `SKILL.md`

Put a folder named after the skill in the location for its scope, containing a
`SKILL.md`. For a **vault-scoped** example skill called `greet`:

```
40-Skills/greet/SKILL.md
```

A minimal `SKILL.md` carries its own frontmatter (name, description, trigger) and a
body describing the procedure. Keep the description tight — it is what an agent
reads to decide whether to invoke the skill:

```yaml
---
name: greet
description: >
  Prints a friendly greeting for a named person. Use when the user asks to greet
  someone or to draft an opening line.
---
```

Then the body: what the skill does, step by step, and any inputs it expects.

### 2. Regenerate the catalogue

The generator scans the usual places a `SKILL.md` can live and rewrites the
catalogue. Run it, then reindex so search picks up the new note:

```sh
python3 _bin/skills_index.py    # rebuild INDEX-<machine>.md and per-skill notes
python3 _bin/index_vault.py     # rebuild the FTS5 search index
```

This produces two things:

- an entry in `40-Skills/INDEX-<machine>.md` (the per-machine list), and
- a per-skill note `40-Skills/greet.md` whose machine-managed section sits inside
  `<!-- AUTO:BEGIN -->` … `<!-- AUTO:END -->` markers.

> One index **per machine** is deliberate: each machine writes only its own
> `INDEX-<machine>.md`, so two machines with different skills installed never
> clobber each other on sync.

### 3. Verify it landed

```sh
python3 _bin/query.py "greet"   # the skill should now surface in search
```

Open `40-Skills/greet.md` and confirm the `AUTO` block lists the scope, the path to
the `SKILL.md`, and how to invoke it.

### 4. (Optional) Add your own commentary

Everything **inside** the `AUTO:BEGIN`/`AUTO:END` markers is overwritten on every
rebuild — never edit there. Anything you write **outside** the markers (gotchas,
examples of good use, links) is preserved. Weave the note into the graph with
`[[wikilinks]]`, e.g. link the project that uses it, `[[my-project]]`, or a related
convention.

## Gotchas

- **Don't hand-edit the catalogue notes** inside the `AUTO` block — your changes are
  lost on the next `skills_index.py` run. Put durable commentary outside the markers.
- **A skill missing from one machine's index** just means it isn't installed there;
  it is not an error.
- **Removing a skill:** delete its `SKILL.md` and rerun `skills_index.py`. Prefer
  marking the per-skill note `status: superseded` over deleting it — history is part
  of the memory.
- On many setups `skills_index.py` runs at session start, so the catalogue is often
  already current; run it by hand when you want the change reflected immediately.

## See also

- `40-Skills/README.md` — how the catalogue is structured.
- `30-Knowledge/README.md` — the note contract and how durable notes are written.
