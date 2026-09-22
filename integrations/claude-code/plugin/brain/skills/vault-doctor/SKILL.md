---
name: vault-doctor
description: Diagnoses the health of the Brain vault and the memory system: retrieval metrics, orphaned or duplicated notes, sync state and the test harness result. Use it when the context system behaves oddly, or to check whether it is earning its keep.
---

## Diagnosis

!`/usr/bin/python3 __VAULT__/_bin/doctor.py`

## Instructions

Interpret the report above for the user:

1. **Is recall useful?** Look at the injection rate against prompts, and the token spend.
   If it almost never injects, either the terms or the vault content are failing. If it
   injects every time and nobody reads the notes, it is burning window for nothing.
2. **Is there debt in the vault?** Notes with no links, duplicates, stale `confidence:
   low`, notes untouched for months. Propose consolidating with `consolidate-memory`.
3. **Is it in sync?** If changes have been uncommitted for a long time or the push is
   failing, say so with the exact command to fix it.
4. **Is the link graph healthy?** Broken links that `linkfix.py` could not fix come first:
   retrieval expands across links, so a hole there degrades every session silently.
5. **Is the machinery alive?** If the guardian is installed, run
   `python3 ~/Brain/_bin/guardian.py status` and read its hook liveness and hook probe lines:
   hooks that do not fire mean memory is not being queried or saved, with no error anywhere.
6. **Does retrieval work in the user's language?** When the user writes in Spanish and the
   report shows words no Spanish question can reach, run
   `python3 __VAULT__/_bin/bilingual_eval.py --held-out` and read `--from-misses` before
   proposing any glossary entry: a missed proper noun needs nothing, a missing subject needs
   a note. Never extend the glossary just to make the held-out set pass.
7. **Does context reach the code?** To verify the whole agent pipeline end to end, point the
   user at `python3 __VAULT__/_bin/pipeline_acceptance.py setup`; it runs in a fresh session
   and is never part of the test suite.

Finish with **three concrete actions**, ordered by impact. If everything is fine, say so
in one line rather than inventing problems.

## Language

- **Everything written into the vault goes in English**: `title:`, `tags:`, the prose.
  A verbatim quote keeps the language it was said in, with the English alongside. Answer
  the user in their language; the note goes in English, because retrieval is lexical and a
  note in another language is unreachable by search:
  `~/Brain/30-Knowledge/2026-09-08-convention-vault-is-written-in-english.md`.
