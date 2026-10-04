---
id: 2026-09-01-howto-nextjs-render-prop-crosses-server-client-boundary
title: Next.js render props across the server and client boundary
type: howto
area: [frontend]
projects: []
tags: [nextjs, server-components, client-components, build, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-01
supersedes: []
---

## The trap

A page without `"use client"` rendered `<Gate>{(user) => <Panel user={user} />}</Gate>`, where `Gate` was a
Client Component. A function cannot cross the server to client boundary: props from a Server Component
into a Client Component must be serializable, and a closure is not.

It does not fail as a type error, a lint warning or a runtime error in `next dev`, which tolerates it. It
fails **only when Next.js prerenders the page** (`next build` or a production deploy), with an opaque
error pointing at the render rather than the prop.

## Fix

Move the whole piece that needs the render prop into its own Client Component (a dedicated file with
`"use client"` at the top), and have the Server Component render it with plain serializable data only
(strings, numbers, booleans, plain objects and arrays). The branching that lived in the callback moves
inside the client component.

## Rule

Before shipping a prop that is a function (a render prop, a handler passed down several layers, a
factory), check which side of the `"use client"` boundary its origin and its destination sit on. Since
the failure only surfaces at prerender, run `next build` before trusting a component tree that spans the
boundary, not only `next dev`.

## Links

- [[2026-08-30-howto-nextjs-shared-component-leaks-client-bundle]]
- [[2026-09-01-howto-nextjs-client-page-metadata-ignored]]
