---
id: 2026-09-16-convention-push-vault-changes-immediately
title: Push vault changes to origin immediately
type: convention
area: [git, sync]
projects: []
tags: [git, push, vault, multi-machine, sync, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-24
supersedes: []
---

## The rule

A change to the vault is not done when it is committed, and not done when it is merged into the
main branch. It is done when it is pushed to `origin`. Push right away, in the same session, as
part of the merge step, by running the sync daemon's own pass:

```sh
/usr/bin/python3 ~/Brain/_bin/vault_sync.py
```

It commits whatever is pending and pushes every commit the remote does not have yet, under the
same lock its scheduled runs take. Do not leave it for the next scheduled pass.

A hand `git commit` or `git push` in the vault's checkout is denied by the pre-write gate since
2026-09-22: it races the daemon and loses its own commit message
([[2026-09-22-failure-session-git-commit-in-the-vault-races-vault-sync]]). A fast-forward merge of
a branch finished in a worktree is still allowed.

## Why

Every other machine and every other session reads the vault from the remote. A fix to a script, a
new convention or a corrected scheduled task row that sits in one local clone leaves every other
machine running the old logic until something else happens to push it. For machine scoping of
scheduled tasks, for example, that gap is exactly the window in which a task runs twice or not at
all.

It is the same principle as [[2026-09-02-convention-deploy-to-prod-on-every-change]]: a change is
not done until it is live where it needs to be seen. For the vault, live means on the remote.

## How to apply

- After a clean rebase and merge into the main branch (the integration step of `/task`), push in
  the same step. It is not a separate, deferrable action, and there is no need to ask "should I
  push" for a vault change made inside a task the user already asked for.
- Ordinary git care still applies: no force push, no history rewrite. This rule is about not
  delaying an ordinary push, not about skipping care.
- If the push cannot happen (offline, the remote moved and the rebase conflicts), say so plainly
  instead of silently leaving it for the sync job.

This is about the vault's own repository. For code repositories, the merge target and push habits
are set per repository; see [[2026-09-17-convention-solo-repos-merge-to-main-no-pr]].

## Links

- [[2026-09-02-convention-deploy-to-prod-on-every-change]]
- [[2026-09-17-convention-solo-repos-merge-to-main-no-pr]]
