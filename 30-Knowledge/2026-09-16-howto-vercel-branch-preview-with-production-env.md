---
id: 2026-09-16-howto-vercel-branch-preview-with-production-env
title: Show a branch build with production environment values without moving the production domain
type: howto
area: [frontend, deploy]
projects: []
tags: [vercel, deploy, preview, environment, review, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The problem

A project's Preview environment was configured as a test bench (test flags, test backends) and lacked
several production-only variables, so every branch preview built in test mode and never showed real
data. Misleading for reviewing a feature branch.

## Building a branch with production variables

Deploy by hand from a clean worktree of the branch, at the repo root:

```sh
npx vercel deploy --prod --skip-domain --yes --scope <team> \
  --build-env DEPLOY_COMMIT=$(git rev-parse HEAD) --build-env DEPLOY_BRANCH=<branch>
```

- `deploy --prod` builds with the Production environment's variables.
- `--skip-domain` stops the production domain from moving to this build; it gets its own deployment URL.
  It needs the explicit `deploy` subcommand; the bare `--prod` shorthand does not do it.
- `--scope` is required when the account has more than one team.
- Check the project's deployment protection before handing the URL to someone: with protection off it is
  public.
- The git push still creates its normal test-mode preview; ignore it for visual review.
- Verify on the returned URL that the version endpoint shows the branch commit and the production
  environment ([[2026-09-02-howto-vercel-env-vars-empty-not-undefined-build-stamp]]). The CLI's exit code is
  not proof.

## Often cheaper: inject the change into production

For a purely visual check, load production in a headless browser and inject the new CSS
(`page.addStyleTag`) and markup (`page.evaluate`), or swap the stylesheet `<link>` hrefs for the preview's
built CSS chunks, then screenshot. Real data with the exact CSS that will ship, no deploy at all
([[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).

For design critique, neither replaces the local fake data mode, which shows every state
([[2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed]]).
