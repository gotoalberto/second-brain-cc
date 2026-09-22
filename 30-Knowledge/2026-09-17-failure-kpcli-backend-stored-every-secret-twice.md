---
id: 2026-09-17-failure-kpcli-backend-stored-every-secret-twice
title: The kpcli backend stored every secret twice
type: failure
area: [security, credentials]
projects: []
tags: [kp, kpcli, keepass, credentials, stdin, failure]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## What happened

On a machine using the kpcli backend, every secret `kp.py` wrote was stored as two copies of
itself: a 108-byte token came back as 217 bytes, `<token>\n<token>`. Nothing reported an error.
`kp.py` printed `updated`, took its backup and verified that the database opened. Every later read
returned a value that was silently wrong, and it surfaced only when a check that used the token
parsed garbage right after the token had been filed.

## Why

`kp.py` speaks keepassxc-cli's protocol. With `-p` it writes the new secret twice on stdin, because
keepassxc-cli asks for the password and then for its confirmation. The kpcli helper read all of
stdin as one value, so both copies became the secret.

The doubling cannot be removed where it is produced: the keepassxc-cli machines depend on it.

## The fix

`kp_backend.split_confirmation()`, applied only on the kpcli path, collapses the payload when it is
exactly two identical lines, which is what password plus confirmation means. It is not "read one
line": a secret may contain newlines (a multi-line key), and a naive fix would truncate it.
Anything that is not two identical halves passes through untouched. `kp_backend_test.py` covers
both the collapse and the cases a naive fix breaks.

## The lesson

A write path that verifies only "the database still opens" cannot catch a wrong value. When two
clients share one protocol, check how each consumes the same bytes, and read back what was written
when a backend is new.

## Links

- [[2026-09-16-runbook-kp-backends]]: the two backends and what each one covers.
- [[2026-08-20-decision-credentials-in-keepass]]: the credential model this serves.
