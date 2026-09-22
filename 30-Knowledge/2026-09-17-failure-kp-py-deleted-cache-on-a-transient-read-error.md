---
id: 2026-09-17-failure-kp-py-deleted-cache-on-a-transient-read-error
title: kp.py deleted the cached master on any open failure, not only on a rejected key
type: failure
area: [security, credentials]
projects: []
tags: [kp, keepass, caching, reliability, failure]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## What happened

Three scripts opened the kdbx within a minute of a `kp.py unlock` armed for a year. The first
succeeded; the other two failed with "I do not have the master", which reads exactly like an
expired or rejected cache. Neither was the case.

## Why

`kp.py` deleted the cached master on any failure to open the database and then fell back to asking
for it. When the database sits on a network or synced drive, a read can fail for a moment for
reasons unrelated to the password. Deleting the cache over one such blip turns it into a prompt for
every later session, and headless sessions exit 4.

What proved it was the timestamp on the cache entry: it had been armed a few minutes after the
failures, not at the `unlock`. The failure path had deleted the user's entry and a later prompt had
re-created it.

The obvious suspects were measured and ruled out first: the cache had not expired, the drive
answered in milliseconds, and concurrent keyring reads did not fail.

## The fix

`_BAD_KEY` (`invalid credentials|wrong key|could not be decrypted`) already existed to tell a
rejected key from every other error, but this path never consulted it. Now only a match deletes the
cache; any other failure keeps it and retries once with the same master. `kp_test.py` checks both
branches.

## The lesson

A cache invalidated by "the operation failed" instead of "the credential was rejected" erases
itself on any unrelated hiccup. Tell the two failure classes apart explicitly, above all when the
protected resource lives where transient errors are routine.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
- [[2026-09-16-runbook-kp-backends]]
