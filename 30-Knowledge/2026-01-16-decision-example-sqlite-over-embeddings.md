---
id: 2026-01-16-decision-example-sqlite-over-embeddings
title: Use SQLite FTS over vector embeddings for vault search
type: decision
area: [memory-system]
projects: [my-project]
tags: [search, sqlite, embeddings, retrieval, example]
status: active
confidence: high
source: agent
provenance: "example note shipped with the vault — illustrates the shape of a decision record; not a record of a real event"
updated: 2026-01-16
supersedes: []
---

> **This is an example note.** It ships with the vault to show what a good decision
> record looks like — full frontmatter, real alternatives, and a "why" you can act on.
> The names and numbers are invented placeholders. Overwrite or delete it once you have
> your own decisions to store.

## What was decided

Search the vault with **SQLite FTS5** (a full-text keyword index over the notes) rather
than with **vector embeddings** (semantic similarity over an embedding model). The index
lives in a single local database file, is rebuilt by `_bin/index_vault.py`, and is queried
by `_bin/query.py`. See the toolchain in [[my-project]].

## Alternatives considered

- **Vector embeddings (a local model + a vector store).** Semantic recall: a query for
  "how do we authenticate" would surface a note titled "login token rotation" even with no
  shared words. The cost is a model dependency, an embedding step on every write, a heavier
  store to keep in sync, and non-determinism that makes results hard to reason about.
- **A hosted embedding/search API (e.g. a generic "Acme Search" service).** Best recall
  with the least code, but it sends note contents off the machine, adds a network hop and a
  key to manage, and breaks the offline, self-contained promise of the vault.
- **Plain `grep` over the Markdown files.** Zero dependencies and fully transparent, but no
  ranking, no stemming, and it slows down noticeably as the note count grows.

## Why

- **Stdlib only.** SQLite FTS5 ships inside Python's standard library, so the index adds no
  third-party dependency and nothing to install — the core constraint of this toolchain.
- **Deterministic and inspectable.** The same query returns the same ranked rows every
  time, and the index is a plain file you can open and inspect. Embedding results drift as
  the model or its version changes.
- **Private and offline by default.** Note contents never leave the machine; there is no
  API key, no network call, and no external service in the retrieval path.
- **Good enough at this scale.** For a personal vault (hundreds to low thousands of notes),
  keyword search with decent titles and tags retrieves what you need. The recall gap that
  embeddings would close is small here, and disciplined tags and `[[wikilinks]]` recover
  most of it.
- **Cheap to rebuild.** Reindexing the whole vault is fast and runs on every write, so the
  index is never meaningfully stale.

## Consequences / what to revisit if it changes

- Queries are **keyword-based**: a search only finds a note if it shares words (after
  stemming) with the note's text. Write descriptive titles and tags so notes are findable,
  and lean on `[[wikilinks]]` to connect ideas that don't share vocabulary.
- **Revisit if** the vault grows past roughly ten thousand notes, if "I know it's in here
  but I can't find it" becomes a recurring complaint, or if a fully local embedding model
  becomes trivial to bundle without adding a dependency. A hybrid — FTS for exact matches,
  embeddings for semantic fallback — would be the natural next step, and would supersede
  this note rather than delete it.
