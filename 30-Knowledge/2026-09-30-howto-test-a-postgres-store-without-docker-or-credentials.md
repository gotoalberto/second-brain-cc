---
id: 2026-09-30-howto-test-a-postgres-store-without-docker-or-credentials
title: Testing a Postgres store without Docker or credentials
type: howto
area: [testing, backend]
projects: []
tags: [postgres, pglite, testing, vitest, sync, backfill]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-30
supersedes: []
---

# Testing a Postgres store without Docker or credentials

## When to use it

The code under test talks to Postgres through `pg`, the agent's user cannot reach a Docker socket,
and the real database's credentials should not be on the machine. Mocking the queries would test the
mock. Real SQL can still run.

## PGlite as a socket server

PGlite is Postgres compiled to WebAssembly; its socket server speaks the wire protocol, so an ordinary
`pg` client connects to it.

```sh
mkdir -p /tmp/pglite && cd /tmp/pglite && npm init -y && npm i @electric-sql/pglite @electric-sql/pglite-socket
npx pglite-server --port 55433 &
```

Then point a throwaway test at `postgres://postgres@127.0.0.1:55433/postgres` with `max: 1` in the
pool, and without any `ssl` option: PGlite does not speak SSL, so a test suite that hard-codes `ssl`
cannot use it as is. Stop the server by its port (`fuser -k 55433/tcp`), never with `pkill -f`
([[2026-09-23-trap-pkill-f-matches-its-own-wrapper-and-kills-the-shell]]).

## A real Postgres when the machine allows it

When the test needs behaviour PGlite does not emulate, a disposable container is the next step,
bound to loopback only:

```sh
docker run -d --rm --name pg-test -e POSTGRES_PASSWORD=test -p 127.0.0.1:55432:5432 postgres:16-alpine
```

Either way, gate the suite on an environment variable so it skips cleanly when no server is running
(`describe.skipIf(!process.env.TEST_DATABASE_URL)` in Vitest), and have each test create and drop its
own schema rather than depend on a prepared database.

## A sync rule found the same way

A reader that follows a live event log forward (an orders feed, for example) and fills its older
history backward decided to backfill "when the forward side had nothing new". On a busy feed that
never happens: between two calls there is always a new order, so every call took the forward branch
and the history never filled. Decide on "the forward read reached the newest event in this call", and
let that same call continue with one backward page. Two details that held up: a backward page larger
than the cap keeps whole events at its newest end and moves its start, so the stored history has no
gap; and a concurrent caller holding the lock fills its own page while the cursor moves, so the next
call continues from there.

## Links

- [[2026-09-23-trap-pkill-f-matches-its-own-wrapper-and-kills-the-shell]]
- [[2026-08-26-convention-code-development-pipeline]]
