---
id: 2026-09-01-howto-nextjs-client-page-metadata-ignored
title: Next.js App Router metadata in client pages
type: howto
area: [frontend]
projects: []
tags: [nextjs, metadata, app-router, seo, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The trap

`export const metadata = {...}` in a route's `page.tsx` is **silently ignored** by the App Router when
that file starts with `"use client"`: metadata exports only work in Server Components. No build error, no
warning; the route falls back to the nearest ancestor layout's metadata. A route shipped the home page's
`<title>` in production for weeks this way.

**Fix**: move the metadata into the route's own `layout.tsx`, which can stay a Server Component even when
the page under it is a client component.

**Rule**: whenever a route is missing its `<title>` or social card tags and its `page.tsx` starts with
`"use client"`, look for a `metadata` export in that same file first.

## Dynamic metadata that reads a backend

When the title depends on data (a product's name, say), put `generateMetadata` in that sibling layout,
fetch what it needs there, and **return `{}` on any failure** instead of throwing. An inherited generic
title is an acceptable degradation; a page that fails to render because metadata threw is not.

## Title templates under an intermediate title

The root's `title: { template: "%s · Example" }` stops applying to a subtree as soon as an intermediate
segment sets its own `title` as a plain string. Pages under it need `title: { absolute: "Orders · Example" }`
and must spell out the suffix themselves.

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-09-01-howto-nextjs-render-prop-crosses-server-client-boundary]]
- [[2026-08-30-howto-nextjs-shared-component-leaks-client-bundle]]
