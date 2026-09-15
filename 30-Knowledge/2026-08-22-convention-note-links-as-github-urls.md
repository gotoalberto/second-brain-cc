---
id: 2026-08-22-convention-note-links-as-github-urls
title: Vault notes are cited to the user as repository URLs
type: convention
area: [communication, memory-system]
projects: []
tags: [links, notes, github, citations, sync, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

When a reply cites a vault note, the link is the note's URL on the vault's git remote, written as a
markdown link with the note's title as its text:

```
[Language per audience](https://github.com/<owner>/<vault-repo>/blob/main/30-Knowledge/2026-09-15-convention-language-per-audience.md)
```

Never a local path like `30-Knowledge/....md` or `~/Brain/...`: a local path only opens on this machine
and in this session, while a repository URL opens from a phone, another machine or a message.

## Traps

- **The note has to be pushed first.** The link points at the remote branch, so a note created or edited
  in the same session returns 404 until it syncs. Run `python3 ~/Brain/_bin/vault_sync.py` and confirm
  the push before sending the link.
- **Some folders are never on the remote**: `80-Private/`, `60-Context-Packs/` and `_index/`. For those,
  give the local path and say it is not synced.
- **Scope.** This is about links given to the user. Links between notes stay `[[wikilinks]]`.
- A vault with no remote has nothing to link to: give the path and say so.

## Links

- [[2026-08-28-convention-clickable-links-and-send-files]]
- [[2026-08-22-convention-app-urls-with-local-ip]]
