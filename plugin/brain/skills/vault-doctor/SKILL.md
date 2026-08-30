---
name: vault-doctor
description: Diagnoses the health of the Brain vault and the memory system — retrieval metrics, orphaned or duplicated notes, sync state and the test harness result. Use it when the context system behaves oddly, or to check whether it is earning its keep.
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
4. **Does the harness pass?** If `selftest` fails, that comes first: the system may be
   silently degraded across every session.

Finish with **three concrete actions**, ordered by impact. If everything is fine, say so
in one line rather than inventing problems.
