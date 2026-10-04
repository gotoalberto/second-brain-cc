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
updated: 2026-10-04
supersedes: []
---

## The rule

In a project that deploys, a requested change is not done at the commit. It is done in
production, verified there: commit, push, deploy, then check the public URL shows the
change. Without being asked and without being reminded.

## Why

For most users the running site or service is the deliverable; the repository alone is not. A
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

## What counts as verified

A merged pull request, a green build and pages that answer 200 can all be true while production
still serves the old thing. Each of these was seen:

- **Production failed while the preview passed.** On a hosting platform that builds a preview and a
  production deployment for the same commit, the production one failed within a second and the
  preview of the identical commit was fine. Check the production deployment status of the merged
  commit itself (for GitHub, `gh api repos/<owner>/<repo>/commits/<sha>/status`), and read the build
  log when it failed.
- **The live page is the evidence.** Fetch the real page and look for the new asset name, hash or
  text (`curl -s https://example.org/ | grep <new-asset>`). A dashboard saying "ready" is a claim
  about the platform.
- **Configuration baked at build time.** Frameworks inline some variables into the bundle when it
  is built (`NEXT_PUBLIC_*` in Next.js, `VITE_*` in Vite and similar). A release whose variables
  were not switched before the merge ships the old values under the new commit. A version endpoint
  only proves which commit built; verify the values derived from configuration that the live build
  serves (an endpoint or page that shows them) as well.
- **After changing such variables, redeploy without the build cache.** A plain redeploy can reuse
  the old build and keep the old values.
- **A merge can never reach production at all.** One merge got no deployment of any kind (no
  deployment record for its commit) while the merge before it deployed in a minute: the push
  webhook was apparently lost. Check the version endpoint after every merge, not only after the
  ones that change configuration. The next merge deployed normally and carried the missed change
  with it; when no next merge is coming, ask the user to redeploy, since triggering a production
  deploy through the platform's API is an action to confirm first.
- **A client-rendered app's HTML shell proves nothing.** Fetch `/`, take the hashed bundle name from
  its `<script>` tag, fetch that bundle and grep it for strings that must now be present or absent; a
  changed hash between two checks is itself proof of a new deploy. Grep the string as written in the
  source, which can differ from what renders: a heading shown in capitals by `text-transform` is title case in the
  bundle. Then check the rendered page in a browser.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
- [[2026-09-30-convention-pull-requests-ready-on-main-merged-by-the-agent]]
