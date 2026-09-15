---
id: 2026-09-15-decision-file-vault-in-a-local-directory
title: Files go to a local directory and the vault keeps pointers
type: decision
area: [memory-system, storage]
projects: []
tags: [files, local-directory, deliverables, memory, first-run, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The decision

**The git vault holds memory. Files live in a local directory outside it.**

- **Memory** is notes, decisions, relationships and pointers: text, diffable, light.
- **Files** are deliverables, intermediate steps and source material: heavy, opaque to diff,
  often in many versions.

Every file a project produces, intermediates included, is stored with `files.py` and cited from
the note that explains it.

## Why

The vault is committed and pushed at every session close. Binaries in it force you, sooner or
later, to prune or summarize the memory so the repository stays manageable, and summarizing
loses information. With the two separated, memory never has to shrink: it grows as small
linked notes and the weight goes somewhere without that limit.

A local directory needs no account, no credentials and no network, so every install has a file
store from its first run. It can be backed up, copied to another machine or placed inside a
synced folder like any other directory.

## The directory

One module, `_bin/brain_files.py`, says where it is, in this order:

1. `BRAIN_FILES_DIR`, when set (a leading `~` is expanded);
2. the `dir` recorded in `<brain state>/files-dir.json` by the first run;
3. otherwise it is unconfigured, and `files.py` stops and says to run the first run.

The first run's `files` step is required. It proposes `~/BrainFiles` on macOS and Linux alike,
creates the directory, writes and removes a test file to prove it is writable, and only then
records the answer. It has no yes or no, so it cannot be declined, and `first_run.py skip-all`
sets up the default directory instead of skipping it.

## How it is used

```sh
python3 ~/Brain/_bin/files.py put <file...> --to <note> --project <slug> \
        --kind deliverable|intermediate|material --caption "what it is"
python3 ~/Brain/_bin/files.py ls [--project <slug>]
python3 ~/Brain/_bin/files.py get <key> [--out <dir>]
python3 ~/Brain/_bin/files.py check                  # broken references and orphans
```

`put` copies each file in, adds one line per file under the note's `## Files` section (created
the first time, never duplicated) and updates the project's manifest. The rules live in
`_bin/files_core.py`, which has no disk or process access and is tested on its own; `files.py`
only reads and writes.

## How keys are organized

```
<slug>/<YYYY-MM-DD>/<kind>/<file>
<slug>/material/<file>
<slug>/manifest.json
```

The key is the path under the files directory. It encodes project, date and kind, so the store
can be browsed without opening anything. The first 8 characters of the file's sha256 go into
its name, so two different files with the same name never replace each other and storing the
same file again changes nothing. Each project's `manifest.json` lists every file with its
digest, kind and the note that cites it, reconciled with what is really on disk on every `put`.

## What goes where

| layer | what | where |
|---|---|---|
| memory | notes, decisions, relationships | git |
| note images | small screenshots that render in the editor | git, only if small |
| files | deliverables, intermediates, material | the files directory |

## A check with false positives

`check` once reported folder prefixes cited in notes (`<slug>/material/`) as broken
references. With several false positives on top, the report stopped being read, and two
genuinely broken references were hidden among them. `check` ignores keys ending in `/` and
documentation placeholders. A check with false positives is worse than no check, because it
teaches you to ignore it.

## What not to do

- Never store secrets, and never a config file with a key inside.
- Never cite a file without storing it, or store one without citing it.
- Never use the files directory as a scratch disk: store what was delivered or what is needed
  to rebuild it.
- Never copy files into the directory by hand: the note and the manifest would not know.

## Links

- [[2026-08-25-convention-deliverables-to-the-vault]]
- [[2026-09-15-decision-first-run-asks-before-connecting-accounts]]
