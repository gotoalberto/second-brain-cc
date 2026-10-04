---
id: 2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed
title: Every web under development runs locally with injected fake data, and every page is reviewed there
type: convention
area: [frontend, design]
projects: []
tags: [web, local, fake-data, demo-mode, login, design-review, critique, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-03
supersedes: []
---

## The rule

Whenever a web is developed, new or an existing one being edited, it must be possible to bring it
up **locally, and only locally**, and see every page, including the ones behind a login, with fake
data injected by the app itself. Every one of those pages is looked at before the design is judged.

The trigger was a hosted preview that asked for a login to the hosting platform: its pages could not
be judged at all, and production data would have hidden the empty, huge and error states anyway.

## What it means

- **Every web task, new or existing.** Before judging a design, the web runs on this machine. A
  production URL or a hosted preview is not a substitute.
- **Fake data enters through the app's own boundary.** In a hexagonal app that is a fake adapter
  behind the same port the real one implements (repository, API client, search, auth), chosen in
  the composition root. No page should need a database, a remote API, a third-party sign-in or a real account
  to render.
- **Login-protected pages too.** Auth is faked locally (a fake session, a fake identity provider), so every
  gated page renders as a signed-in user, and as each role when roles change what a page shows.
- **Only locally.** The fake mode cannot be turned on in a deployed build: it is gated on the dev
  server (`NODE_ENV !== "production"`) or on a flag that only `.env.local` sets, and the fake
  adapters are never wired into a production build. A test pins that the production composition
  never picks a fake.
- **Fully offline.** The fake mode needs no secrets, no `.env`, no network, no database and no
  third-party API, so it runs on any machine. No fork of a real backend, no copy of a production
  database, no proxy to production.
- **Every state can be switched on.** Through a dev-only control or a URL parameter, the fake world
  exposes every state a page can be in: signed in and signed out, each role, loading, empty, error,
  success, pending, worst-case data (the `break-ui` set) and any feature-specific state. A state that
  cannot be switched on locally cannot be critiqued, and closing that gap is part of the same task.
- **Every page is looked at.** List the routes from the router (`app/**/page.tsx` in Next.js, the
  route table elsewhere) and screenshot each one at phone, tablet and desktop widths, every tab or
  state that changes the layout included. The design is judged on that full set, including pages
  the change did not touch.
- **Critique runs on the fake pages.** Every critique round, the blind critic rounds included,
  judges screenshots taken from the local fake mode. Production URLs and hosted previews are not used
  for critique.
- If an existing web has no fake mode yet, building it is part of the task, not optional
  scaffolding. It stays in the repo for the next change.

## Example

A small invented app with a dashboard behind a login:

```ts
// composition root
const adapters = process.env.NEXT_PUBLIC_FAKE === "on" && process.env.NODE_ENV !== "production"
  ? fakeAdapters(scenarioFrom(url))      // ?scenario=empty | huge | error | signed-out
  : realAdapters(env);
```

with a test asserting that `realAdapters` is what a production build composes.

## Where it applies

The `dev` skill's design gates carry this rule. The worst-case pass of `break-ui` reuses the same fake
data boundary. Related: [[2026-09-18-convention-anti-ai-slop-design-techniques]],
[[2026-09-01-convention-web-development-skill-stack]].
