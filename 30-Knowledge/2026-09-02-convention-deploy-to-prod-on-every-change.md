---
id: 2026-09-02-convention-deploy-to-prod-on-every-change
title: A change is done when it is live and verified in production
type: convention
area: [engineering]
projects: []
tags: [deploy, production, verification, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-02
supersedes: []
---

## The rule

In a project that deploys, a requested change is not done at the commit. It is done in
production, verified there: commit, push, deploy, then check the public URL shows the
change. Without being asked and without being reminded.

## Why

For most users the running site or service is the deliverable, not the repository. A
change that only sits on the main branch is not done, and a passing build is not proof that
the change is visible.

## How to apply

- Deploy after each change. Do not pile several up for one final deploy.
- Verify on the public URL before saying it is done.
- If the deploy fails or a credential is missing, say so in the reply instead of leaving
  the change only committed.
- Exceptions come from the user: a branch they want to review locally first is not deployed
  until they say so.
- Adapt this to your setup. If you do not want automatic deploys, replace this note with
  your own rule; the protocol links to it.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
