---
id: 2026-08-30-convention-dry-run-output-goes-to-stderr
title: Dry-run output goes to stderr
type: convention
area: [engineering, shell]
projects: []
tags: [dry-run, shell, deploy, stderr, approval, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

A deploy script implemented `--dry-run` by putting `DRY="echo [dry-run]"` in front of every command.
Several of those commands ended in `>/dev/null`, so their dry-run lines were swallowed too. The list
meant for the user to approve silently left out the creation of nearly every resource that costs
money.

## The rule

A simulation mode's output (`--dry-run`, `--plan`, `--what-if`) goes to **stderr**. A real command's
stdout redirection (to `/dev/null`, a file or a pipe) must not be able to swallow the "this is what I
would do" notice. Implement the prefix as a function that prints the command to stderr before
deciding whether to run it:

```sh
run() { echo "[dry-run] $*" >&2; [ -n "$DRY_RUN" ] || "$@"; }
```

## Corollary

Review a dry run against independent knowledge of what the script should touch, not against itself.
The bug above was caught because the list looked too short for what the script was known to do, not
because anything failed.

## Why it matters

A silent dry run does not read as "this does nothing"; it reads as "there is nothing to approve".
That turns an informed confirmation into a blank signature.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
