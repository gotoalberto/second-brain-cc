---
id: 2026-09-02-howto-vercel-env-vars-empty-not-undefined-build-stamp
title: Empty hosting variables and a build-time commit stamp
type: howto
area: [frontend, deploy]
projects: []
tags: [vercel, nextjs, deploy, env, observability, version-endpoint, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The symptom

A `/api/version` route existed to answer "is what I pushed actually deployed?". After CLI deploys it
answered `{"commit": ""}`: it answered nothing while looking like it answered.

## Two chained causes

1. **Vercel leaves a variable it does not know empty, not undefined.**
   `process.env.VERCEL_GIT_COMMIT_SHA ?? "local"` never falls back, because `??` covers only `undefined`
   and `null`, and `""` passes through. For environment variables, write the fallback against "empty"
   (`value || fallback`, or an explicit `trim() === ""` check). The failure is silent because an empty
   string serializes as a valid value.
2. **A CLI deploy has no commit to ask for at runtime.** The code is uploaded without `.git`, so the git
   variables are empty by design. The last moment anyone knows the commit is before the upload, on the
   deploying machine.

## The fix

- Resolve the stamp in `next.config.ts` and bake it into the build (Next's `env`), in order of
  reliability: the platform's git variable, then a value the deploy script injects
  (`--build-env DEPLOY_COMMIT=$(git rev-parse HEAD)`), then the machine's git, then `unknown`.
- Add a `source` field (`git`, `cli`, `local`, `none`). A bare "unknown" cannot tell "deployed without the
  script" from "this route is broken", which is exactly the doubt the route exists to remove.
- A deploy script refuses with uncommitted changes, refuses when the branch is behind its remote (and
  only warns when the branch has no remote yet, since deploying an unpushed branch is a legitimate test),
  and injects the commit.

## The open path next to the script

Nothing forces anyone to use the script: a bare `vercel --prod` the same day left production answering
`{"commit": "unknown", "source": "none"}`. That honest answer is what saved the investigation: "I do not
know, and I know why". The recipe then was to confirm the commits were ancestors of the remote branch
(`git merge-base --is-ancestor`) and grep the served chunks for a new string.

A guardrail script is worth little while the shorter path next to it stays open. When you cannot close the
bad path, make its result recognisable.

## Stale deployment variables and new code defaults

Whenever a default with an environment override changes in the code (an API base URL, an address, any
config constant), check the variable in the deployment too. A value left there from an old release
silently wins over the new default, and the fix looks like it "did not take". Updating `.env.example`
documents intent; it does not change the deployment. When production still shows old behaviour after a
fix, grep the served bundle for the literal value before assuming the deploy or the code failed.

## Why it generalises

The failure mode of a diagnostic is answering something that looks like data. A fallback `""` or `0` is
worse than an error because whoever asked believes it. If you do not know, say so, and say where the value
should have come from. And if a value only exists on the deploying machine, it travels with the build or
not at all.

## Links

- [[2026-09-02-convention-deploy-to-prod-on-every-change]]
- [[2026-09-01-howto-vercel-monorepo-deploy-from-root-wrong-project]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
