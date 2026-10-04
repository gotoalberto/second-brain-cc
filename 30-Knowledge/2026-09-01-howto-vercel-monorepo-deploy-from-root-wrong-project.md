---
id: 2026-09-01-howto-vercel-monorepo-deploy-from-root-wrong-project
title: Vercel CLI working directory and root directory in a monorepo
type: howto
area: [frontend, deploy]
projects: []
tags: [vercel, monorepo, deploy, worktree, cli, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The trap

In a monorepo whose app lives in `apps/site`, the Vercel project has `rootDirectory: apps/site` set on
Vercel's side. Two opposite mistakes follow from that one setting:

- **Running the CLI from the repo root without a link file** there makes it offer to create a new project,
  and accepting creates a second, orphaned project instead of deploying to the existing one. The link
  (`.vercel/project.json`) lived in `apps/site/.vercel/`, where the root invocation does not read it.
- **Running the CLI from `apps/site` once the link is right** fails with "The specified Root Directory
  "apps/site" does not exist": `rootDirectory` is resolved relative to the invocation directory, so the CLI
  looks for `apps/site/apps/site`.

## What works

1. Put the correct `.vercel/project.json` at the **repo root** (copy it from the app folder if that is
   where it was created).
2. Always invoke the CLI from the repo root, never from the app subfolder, even though that is where the
   app lives.
3. Before any deploy, check the `projectId` in `.vercel/project.json` (or `vercel project ls`) against the
   project you mean. Proximity to the app's source is not proof.
4. A fresh git worktree has no `.vercel/` at all: copy the link file into the worktree's root first.
5. Delete any orphaned project the mistake created, after backing it up
   ([[2026-09-07-convention-backup-vercel-project-before-deleting]]).

## Confirming the deploy

The CLI returning is not confirmation. Read the deployment from the API (or `vercel inspect`) and check
`target: production` and `state: READY` on that specific deployment: a failed deploy and a good one can land
in the same minute. Then check the live site
([[2026-09-02-convention-deploy-to-prod-on-every-change]]).

- When a CLI release breaks its own install (it has happened with a self-updating `npx vercel`), pin the
  last working version explicitly (`npx vercel@<version>`).
- Check which branch production is really built from in the deployments list. A project whose dashboard
  says one production branch can in practice be promoted from another; a push alone may not reach
  production.
- A custom domain that resolves is not necessarily serving the app (it can still show a parking page);
  verify on a domain that is known to serve it.

## Links

- [[2026-09-02-howto-vercel-env-vars-empty-not-undefined-build-stamp]]
- [[2026-09-30-howto-web-css-and-build-traps]]
