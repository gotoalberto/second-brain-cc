---
id: 2026-10-05-howto-architecture-for-a-local-fake-data-mode-in-web-apps
title: "Architecture for a local fake data mode in any web app: ports, composition root, scenarios, guards"
type: howto
area: [dev, web, architecture, testing]
projects: []
tags: [howto, architecture, hexagonal, fake-data, local-dev, scenarios, composition-root, testing, dev-skill]
status: active
confidence: high
source: agent
provenance: "session 2026-10-05: the user asked that the rule 'every web can show every screen with fake data' come with architecture guides on how to achieve it; distilled from a production web app fake mode and its known gaps"
updated: 2026-10-05
supersedes: []
---

## Purpose

How to build the fake mode that
[[2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed]] requires: every
page of a web app, the ones behind a login included, renders locally with injected fake data,
fully offline, every state switchable, and the mode can never turn on in a deployed build.
Framework examples use Next.js, but the shape is the same in any stack.

## 1. Ports first

Fake data can only be injected cleanly if the app talks to the outside world through ports.

- Every outside dependency gets an interface owned by the application layer: repositories,
  external APIs, chain or RPC readers, auth and session, payments, email, analytics, feature
  flags, the clock and randomness.
- Pages, components and use cases import the port, never the SDK. `fetch`, database clients,
  wallet libraries and `Date.now()` appear only inside adapters.
- An existing app without ports: introduce them one dependency at a time, starting with the
  ones the pages read. Extracting a port is the first commit of the fake mode task.

## 2. One composition root decides real or fake

- A single module builds the adapters (`src/composition/container.ts` or equivalent). It is the
  only place that knows whether the fake mode is on, and the only place that imports fake code.
- Real and fake adapters implement the same port type, so the compiler checks that the fake
  stays complete when the port grows.
- Server side (API routes, server components, loaders) and client side (hooks, providers) each
  get their seam from the same root. Never branch on the fake flag inside a page or component.
- Things that cannot be faked usefully (crons, webhooks, raw proxy routes) answer 503 in fake
  mode instead of reaching the network.

## 3. Two locks keep it local

The fake mode turns on only when both hold:

1. An explicit flag that only a local file sets (`NEXT_PUBLIC_FAKE_DATA=on` in `.env.local`, or
   a `dev:fake` script that exports it).
2. The runtime is a dev build (`process.env.NODE_ENV !== "production"`).

Put both checks in one function (`fakeDataEnabled()`), called only by the composition root.
Then:

- Load fake modules through a dynamic import behind that function, so a production bundle does
  not ship them. Check the built chunks for the fake world's file names; a real app was found
  shipping its fakes as dead code in a client chunk.
- A test builds the production composition with the flag set and asserts that no adapter is a
  fake (an `isFake` marker on each fake adapter makes this a one line assertion).
- A production build ignores the scenario URL parameter and renders no dev panel.

## 4. A fake world, deterministic

- One module (`src/infrastructure/fake/world.ts`) holds the whole fake dataset: users, roles,
  entities, histories, prices, whatever the pages read. Fake adapters only query it.
- Seeded and stable: the same scenario renders the same pixels on every run, so screenshots can
  be compared between critique rounds. Fake the clock too, or relative dates drift.
- Realistic shapes: real lengths, real number ranges, real distributions, and real public
  identifiers where they help (public contract addresses, for instance). Never a copy of
  production data and never a secret.

## 5. Scenarios switch every state

A scenario is a named variant of the fake world plus adapter behaviour. Minimum set:

- `default`: a full, healthy account.
- `signed-out`, and one scenario per role that changes what a page shows (`not-admin`, `admin`).
- `empty`: a new account with nothing yet.
- `loading`: adapters wait forever (or a long fixed delay), so skeletons can be judged.
- `error`: adapters throw the same errors the real ones throw, so error UI renders for real.
- `pending`: an operation in flight (a submitted payment, a pending transaction).
- `worst-case`: the `break-ui` dataset (very long names, unbreakable strings, huge and tiny
  numbers, many rows, missing optional fields, non Latin text, emoji).
- One per feature state that changes the layout (a signing flow step, a feature flag on and off).

Selection, in order of precedence: a URL parameter (`?fake=worst-case`), a floating dev panel
that lists every scenario, then a default. Persist the choice in a cookie, so server rendering
sees the same scenario as the client, plus `sessionStorage` for client navigation.

A new state in the product means a new scenario in the same change. A state that cannot be
switched on cannot be critiqued.

## 6. Fake auth and identities

- A fake session adapter returns the scenario's user and roles; protected routes pass their
  guard without a real login. The guard itself stays real; only the session source is fake.
- Wallets: a fake connector or an injected EIP-6963 provider that answers `eth_accounts` and
  signs with a throwaway local key. See
  the EIP-6963 spec (a provider announced through `eip6963:announceProvider`).
- OAuth, magic links, 2FA: the fake mode skips the provider and lands in the signed-in state;
  the provider integration keeps its own contract tests.

## 7. Running it and looking at every page

- One command starts it: `npm run dev:fake`, on a fixed port, no `.env`, no database, no network.
  It must work on a fresh clone of any machine.
- Route inventory from the router (`app/**/page.tsx`, a routes file, the framework's manifest),
  with a sample parameter for each dynamic segment. Keep it as a script, so the list never goes
  stale.
- A sweep script (Playwright) visits every route in every scenario at phone, tablet and desktop
  widths and saves screenshots. That set is what every critique round judges.
- Dev server on `localhost` in the agent's browser; the LAN address for the human.

## 8. Tests that keep it honest

- Contract tests: the same test suite runs against the real adapter (in its own integration
  job) and the fake one, so the fake behaves like the real thing.
- The production composition test from section 3.
- A smoke test that renders every route in the `default` and `error` scenarios and fails on an
  unhandled exception.

## Checklist for a task

1. Ports exist for everything the pages touch.
2. The composition root is the only place that picks fakes, behind `fakeDataEnabled()`.
3. Both locks in place, fakes dynamically imported, production test green, built chunks clean.
4. Fake world seeded; clock faked.
5. Every scenario in section 5 exists, plus the feature's own.
6. Protected pages render through a fake session or wallet.
7. `dev:fake` runs offline on a fresh clone; the route inventory and screenshot sweep run.

