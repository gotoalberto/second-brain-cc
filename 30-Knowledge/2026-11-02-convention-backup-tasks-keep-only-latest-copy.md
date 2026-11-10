---
id: 2026-11-02-convention-backup-tasks-keep-only-latest-copy
title: "Backup tasks keep only the latest copy, old versions included"
type: convention
area: [harness]
projects: []
tags: [backup, storage, versioning, cost]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-02
supersedes: []
---

## Rule

A task that backs something up keeps only the latest copy, with no history. In a versioned bucket that
includes the old copies kept as noncurrent versions: deleting an object there only leaves a delete
marker, and the bytes stay billed.

## How to apply when creating or changing a backup task

1. Upload the new copy first and verify it against the local file (size and a hash).
2. Only after it passes, delete the previous copy.
3. Erase what the delete left behind (noncurrent versions and delete markers under the backup's
   prefix), refusing unless the new copy is live under that prefix and never touching a live object.
4. If any step fails, keep the previous copy and raise an alert.

**Exception, incremental backups.** When each object holds data no other object has (shards of a chat
history, media files), never delete those objects: that would lose data. Only overwritten bookkeeping,
such as a state file, is limited to its latest version.

**Exception, the credential store's own backups.** Their versions are how the store is recovered after
a bad write; leave them alone.

## Why

Backups that keep every copy grow without anyone deciding they should, and a versioned bucket hides the
growth behind objects that look deleted.
