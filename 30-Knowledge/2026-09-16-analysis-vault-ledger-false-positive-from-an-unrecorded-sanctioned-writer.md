---
id: 2026-09-16-analysis-vault-ledger-false-positive-from-an-unrecorded-sanctioned-writer
title: Vault ledger false positive from a sanctioned writer that did not record its write
type: analysis
area: [harness]
projects: []
tags: [vault_ledger, vw.py, linkfix, gate_write, false-positive, instrumentation]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-16
supersedes: []
---

## Context

`vault_ledger.py` reported a shared note in `10-Projects/` as changed without `vw.py`, so unlocked and
unredacted. The note had been written correctly, through `vw.py append`. Two wrong diagnoses came
first, and both show how this kind of bug hides:

- "subagents are exempt from the write gate": the exemption in `gate_write.py`'s docstring covers the
  Context Pack gate only; the shared-note check runs for everyone;
- "the subagent used a shell redirect": its transcript showed a correct `vw.py append` call.

## The cause

`vw.py` wrote the note and recorded the write. Half a minute later `linkfix.py`, which runs on every
prompt, repaired a wiki link in the same note and rewrote it with `atomic_write`. Its restore of the
original mtime is best-effort and did not take, so the file's mtime landed well past the ledger's two
second window after `vw.py`'s record. The ledger then reported a sanctioned write as a raw one.

This false positive is worse than most: it accuses the one path that behaved, and teaches whoever
reads the alarm to ignore it. It has the shape of
[[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]: the ledger
watched one writer's record and reported as if it watched every sanctioned writer.

## The fix

Every sanctioned writer records its own write. `linkfix.py` now calls `B.note_vw_write(path)` after
rewriting a note, exactly as `vw.py` does. Deliberately not done: widening the ledger's window. A
wider window lets a real raw write minutes after a `vw.py` write pass as sanctioned; the fix is always
"the writer records itself", never "loosen the window until the symptom goes away".

## A second hole in the same code

`gate_write_core.bash_touches_protected()` waived a whole shell command as soon as a sanctioned tool
name (`vw.py`, `git` and the rest) appeared anywhere in it, so a raw copy into a protected folder
chained with a `git add` passed. It now judges each segment split on `&&`, `||`, `;` and newline, so a
sanctioned call exempts only its own segment. A plain `|` is not a separator: it chains one data flow,
and the gate keeps denying when a protected path and a writer share a pipeline.

## Links

- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
- [[2026-09-15-convention-write-shared-notes-through-vw-py]]
