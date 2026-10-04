---
id: 2026-08-29-howto-scheduled-task-sessions-cannot-preview-uis
title: Visual verification from unattended scheduled sessions
type: howto
area: [harness, frontend]
projects: []
tags: [harness, scheduled-tasks, frontend, sessions, verification, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-29
supersedes: []
---

## The limit

A session that began as a scheduled task is treated as unattended, and the harness blocks it from starting
dev servers or using preview and browser tools. There is no workaround from inside that session: it is a
property of how the session started, and no permission requested mid-task changes it.

## What follows

Frontend work done in such a session can only be verified by non-visual means: a production build, type
checks, unit and integration tests. That verifies correctness, not appearance, and the two do not
substitute for each other: layout breaks and anything CSS-related are invisible to a build or a test
suite.

- Say so plainly instead of presenting the work as done.
- Hand the user the exact command to run it (`cd <repo>/apps/site && npm run dev`, or the project's local
  fake data mode, [[2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed]]).
- The next session that touches the same UI treats "seen rendered" as a separate open checkbox from
  "builds and tests pass", and closes it before calling the work finished.
- A temporary anonymous deployment, where the hosting CLI offers one, can give the user a URL to look at.
  It still does not let the agent see it, it expires, and it is not a substitute for a proper deploy.

## Links

- [[2026-08-23-verify-frontend-findings-against-production]]
- [[2026-09-01-convention-web-development-skill-stack]]
