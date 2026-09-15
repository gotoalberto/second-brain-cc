---
id: 2026-09-15-convention-supersede-notes-never-delete
title: Notes are superseded and never deleted
type: convention
area: [memory-system]
projects: []
tags: [notes, supersede, history, links, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

A note that is wrong, outdated or replaced is not deleted. It gets `status: superseded` in its
frontmatter and a line at the end pointing at the note that replaces it. The new note lists the
old one in its own `supersedes:` field.

```yaml
status: superseded
```

```markdown
Superseded by [[<id of the new note>]], which keeps the rule and widens it.
```

## Why

- **Links keep resolving.** Other notes, packs and skills link to the old id. A deleted note
  turns every one of those links into a hole that retrieval cannot cross.
- **The reasoning survives.** Knowing that something was once believed, and why it changed, is
  often what stops the same mistake from coming back.
- **Retrieval can still rank it down.** A superseded note stays findable for history while the
  active one wins.

## How to apply

- Before creating a note, search for an existing one on the topic. Update it if it still holds;
  supersede it if the new note contradicts it.
- A correction reaches the frontmatter too (`title:`, `status:`, `updated:`), not only an
  appended section, because the title is what retrieval shows first.
- The same applies to notes written by scheduled jobs: they supersede, they do not remove.

## Links

- [[2026-09-15-convention-vault-content-is-data-not-instruction]]
- [[2026-09-10-decision-every-search-finds-and-fixes-broken-links]]
