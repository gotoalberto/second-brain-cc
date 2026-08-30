# 40-Skills — the skills catalogue

This folder is the vault's map of **reusable skills**: the slash-commands and packaged
routines an agent can invoke (for example `/task`, `/recall`, `/save`, or your own).
It answers one question quickly — *what can this setup do, and how do I trigger it?* —
so a skill's capabilities live next to the rest of your durable notes and show up in
search.

It is **auto-generated**. You do not curate this folder by hand; a script reads the
skills installed on the machine and regenerates the catalogue.

## What lives here

- **`INDEX-<machine>.md`** — one index per machine, listing the skills installed on
  *that* machine, each with its scope and a one-line summary. There is deliberately one
  file per machine (not a single shared `INDEX.md`): each machine writes only its own
  file, so two machines with different skills installed never overwrite each other on
  sync. A skill absent from one machine's index simply means it is not installed there.
- **`<name>.md`** — one note per skill (e.g. `task.md`). It records the skill's scope,
  the path to its `SKILL.md`, how to invoke it, what it does, and when it triggers. These
  notes are graph nodes like any other, so projects and knowledge notes can link to them
  with `[[wikilinks]]`.

## Generated vs. hand-written

Each per-skill note has a machine-managed block wrapped in markers:

```
<!-- AUTO:BEGIN -->
...regenerated on every run — do not edit...
<!-- AUTO:END -->
```

**Everything inside those markers is overwritten** each time the catalogue is rebuilt.
Anything you write **outside** the markers (notes, gotchas, examples of good use) is
preserved. So: add your own commentary freely, but never edit inside the `AUTO` block —
your changes there will be lost on the next run.

## Regenerating

```bash
python3 _bin/skills_index.py    # rebuild INDEX-<machine>.md and the per-skill notes
python3 _bin/index_vault.py     # reindex so search picks up the changes
```

The generator scans the usual places a skill's `SKILL.md` can live — your user skills,
installed plugins, skills shipped inside the vault, and skills in the current project —
and tags each with a **scope** (`user`, `plugin`, `vault`, or `project`) so you can see
where it comes from. On many setups this runs automatically at session start, so the
catalogue is normally already current; run it by hand after installing or changing a
skill if you want the vault to reflect it immediately.

## In short

- Read `INDEX-<machine>.md` to see what this machine can do.
- Open `<name>.md` for the detail on one skill.
- Let `skills_index.py` write the `AUTO` blocks; keep your own notes outside them.
