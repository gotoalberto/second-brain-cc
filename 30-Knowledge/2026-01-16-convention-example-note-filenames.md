---
id: 2026-01-16-convention-example-note-filenames
title: "Convention: dated kebab-case note filenames"
type: convention
area: [knowledge-management]
projects: []
tags: [convention, filenames, naming, vault-structure]
status: active
source: agent
provenance: written 2026-01-16 to document the house rule for naming durable notes; example note.
updated: 2026-01-16
---

# Convention: dated kebab-case note filenames

Durable notes in this vault follow a single, boring naming pattern so files sort
chronologically, stay easy to guess, and never collide. This note is itself an
example of the rule it describes.

## The rule

```
YYYY-MM-DD-type-slug.md
```

- **`YYYY-MM-DD`** — the date the note was first created (ISO 8601). Leading
  zeros always, so `2026-01-06`, never `2026-1-6`. This makes files sort in
  time order inside any folder.
- **`type`** — one value from the frontmatter `type` vocabulary
  (`decision`, `convention`, `howto`, `reference`, `analysis`, `meeting`,
  `session`, `skill`, `meta`, …). It matches the `type` field in the note's own
  frontmatter.
- **`slug`** — a short, lowercase, kebab-case summary of the subject. Use
  hyphens between words, ASCII only, no spaces, no underscores, no accents.

Everything is lowercase except the date digits. The `.md` extension is always
present.

## Good and bad examples

Good:

- `2026-01-16-convention-example-note-filenames.md`
- `2026-02-03-decision-choose-sqlite-over-postgres.md`
- `2026-02-11-howto-reindex-the-vault.md`
- `2026-03-01-reference-backup-locations.md`

Avoid:

- `Meeting Notes.md` — no date, spaces, capitals, missing type.
- `2026-3-1-decision.md` — unpadded date, empty slug.
- `2026_03_01_decision_choose_db.md` — underscores instead of hyphens.
- `decision-choose-db-2026-03-01.md` — date must lead so files sort by time.

## Why this pattern

- **Chronological sort for free.** A plain `ls` or file-browser listing orders
  notes by creation date because the date leads the name.
- **The filename tells you the kind.** Seeing `type` in the name lets you scan a
  folder and know what each note is without opening it.
- **Stable wikilink targets.** Links use a dateless slug like
  `[[convention-example-note-filenames]]`; the resolver maps that to the dated
  file. Keeping the slug meaningful keeps links readable.
- **No collisions.** Date plus type plus slug is specific enough that two notes
  rarely clash, and when they might, the slug disambiguates.

## Scope and edge cases

- The **date never changes** after creation, even when you edit the note later.
  Record edits in the `updated` frontmatter field instead.
- If two notes would share the exact same name, extend the slug to make it
  distinct (for example add the subsystem name), rather than bumping the date.
- Protected notes (projects, entities) are written through `_bin/vw.py`, which
  applies the same convention automatically — do not hand-name those.
- Non-note assets (images, exports) live elsewhere and are out of scope for this
  rule.

## Related

- [[convention-frontmatter-contract]] — the YAML fields every note carries.
- [[howto-reindex-the-vault]] — rebuilding the search index after adding notes.
