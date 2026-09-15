---
id: 2026-08-26-decision-file-vault-in-s3
title: Files go to private object storage and the vault keeps pointers
type: decision
area: [memory-system, storage]
projects: []
tags: [s3, object-storage, files, deliverables, memory, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The decision

**The git vault holds memory. Files live in object storage.**

- **Memory** is notes, decisions, relationships and pointers: text, diffable, light.
- **Files** are deliverables, intermediate steps and source material: heavy, opaque to diff,
  often in many versions.

Every file a project produces, intermediates included, is uploaded and cited from the note
that explains it. The bucket is optional: a vault with no heavy files does not need one.

## Why

The vault is committed and pushed at every session close. Binaries in it force you, sooner or
later, to prune or summarize the memory so the repository stays manageable, and summarizing
loses information. With the two separated, memory never has to shrink: it grows as small
linked notes and the weight goes somewhere without that limit.

## The bucket

Private, and locked down after creating it: public access blocked, versioning on, encryption
at rest, a policy that denies requests without TLS, and a lifecycle rule for old versions and
broken uploads. The bucket name comes from `BRAIN_S3_BUCKET`; the access key lives in the
KeePass database and never in the code or the environment.

## How it is used

```sh
python3 ~/Brain/_bin/s3v.py put <file...> --to <note> --project <slug> \
        --kind entregable|intermedio|material --caption "what it is"
python3 ~/Brain/_bin/s3v.py ls [--project <slug>]
python3 ~/Brain/_bin/s3v.py get <key> [--out <dir>]
python3 ~/Brain/_bin/s3v.py url <key> [--min 60]     # temporary signed link
python3 ~/Brain/_bin/s3v.py check                    # broken references and orphans
```

`s3v.py` never takes the secret through argv or leaves it in the environment: it relaunches
itself through `kp.py get ... --pipe`, so the key arrives on the child's stdin.

The `--kind` values (`entregable` for a deliverable, `intermedio` for an intermediate step, `material`
for source material) and the key prefixes stay in Spanish in the code on purpose, so existing keys keep
resolving. They are identifiers, not prose.

## How keys are organized

```
proyectos/<slug>/<YYYY-MM-DD>/<kind>/<file>
proyectos/<slug>/manifest.json
material/<slug>/<file>
```

The key encodes project, date and kind, so the store can be browsed without opening anything.
Each object carries its sha256 and the note that cites it in its metadata, and each project has
a `manifest.json` in the bucket, so the relationships can be rebuilt without the vault.

## What goes where

| layer | what | where |
|---|---|---|
| memory | notes, decisions, relationships | git |
| note images | small screenshots that render in the editor | git, only if small |
| files | deliverables, intermediates, material | object storage |

## A check with false positives

`check` once reported folder prefixes cited in notes (`material/<slug>/`) as broken
references. With several false positives on top, the report stopped being read, and two
genuinely broken references were hidden among them. `check` now ignores keys ending in `/`.
A check with false positives is worse than no check, because it teaches you to ignore it.

## What not to do

- Never upload secrets, and never a config file with a key inside.
- Never cite an object without uploading it, or upload one without citing it.
- Never use the bucket as a scratch disk: upload what was delivered or what is needed to
  rebuild it.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
