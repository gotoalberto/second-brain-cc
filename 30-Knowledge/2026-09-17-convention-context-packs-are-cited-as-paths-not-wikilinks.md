---
id: 2026-09-17-convention-context-packs-are-cited-as-paths-not-wikilinks
title: Context packs are cited as paths, never as wikilinks
type: convention
area: [harness]
projects: []
tags: [context-packs, links, linkfix, wikilinks, gitignore, retention, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

## The rule

A context pack is not a note. Citing one as a wikilink (the pack's name in double square brackets) creates a link that can never resolve,
and `linkfix.py` reports it as broken forever. Write it as a plain path instead:

```
`60-Context-Packs/2026-01-04-some-task.md`
```

That keeps the trace of which pack seeded a note without claiming that a note exists.

## Why a pack can never be a link target

Two reasons, both by design:

- `60-Context-Packs/` is in `.gitignore`, so a pack never reaches the remote and no other machine
  can resolve it.
- `vault_sync.prune_packs()` deletes any pack older than `PACK_TTL_DAYS` (14) unless its first 400
  bytes carry `keep: true`.

The target is local, short lived and specific to one machine. `linkfix.py` can neither repair it
nor ever see it appear.

## What it cost

A handful of such links sat in the "broken, need a hand" list of every session's startup, all
pointing at packs already pruned. A list that is supposed to mean something became one the eye
learned to skip. Rewriting them as paths brought the count to zero.

The wrong fix would have been to create notes with the missing names. That invents memory that
never existed, for material that was meant to be thrown away.

## If a pack's content is worth keeping

Do not link it, promote it: write what matters into a real note in `30-Knowledge/` or the project
note, and cite that. A pack is scaffolding. For the rare pack worth keeping on disk past the TTL,
add `keep: true` to its frontmatter; it still is not a link target.

## Links

- [[2026-09-10-decision-every-search-finds-and-fixes-broken-links]]
