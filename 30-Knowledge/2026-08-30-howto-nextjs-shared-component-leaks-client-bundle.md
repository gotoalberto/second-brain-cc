---
id: 2026-08-30-howto-nextjs-shared-component-leaks-client-bundle
title: Next.js shared components and client bundle size
type: howto
area: [frontend]
projects: []
tags: [nextjs, bundle-size, client-components, performance, composition, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-30
supersedes: []
---

## The problem

A shared `Nav`, rendered by every page, always included a heavy client widget (a sign-in button backed by
a large SDK). Pages that are just text shipped about 2 MB of that SDK across some twenty files they never
used.

## What did not work

1. **Moving the SDK's providers from the root layout to the one route that needs them.** `Nav` still
   imported the widget, so the module graph still contained the SDK everywhere `Nav` was used.
2. **Rendering the widget conditionally behind a prop.** A conditional render still needs a static import
   in that file, so the bundler still puts the module in every page's client chunk.
3. **`next/dynamic` inside `Nav`.** Did not shrink the other pages enough, and `ssr: false` is not allowed
   inside a Server Component: it broke the build.

## What worked

Take the widget out of the shared component and give it a slot:

```tsx
export function Nav({ action }: { action?: React.ReactNode }) {
  return <nav>{/* links */}{action}</nav>;
}
```

Only the pages that need it pass `action={<SignInButton />}`. The text pages render `<Nav />` with nothing
from the SDK in their module graph, and dropped to a handful of files and a fifth of the weight.

## The rule

Conditionally rendering a component is not conditionally importing it. Once a module is named inside a
shared component, it enters the client graph of every page that uses that component, whether or not the
render path runs. Keep heavy, feature-specific client code out of shared components and inject it from
the leaf pages (slots, composition). When a page carries a library it does not obviously use, check its
shared components' imports before blaming tree-shaking.

Measure the weight in a fresh tab, since prefetches from earlier navigation inflate the numbers
([[2026-08-23-verify-frontend-findings-against-production]]).

## Links

- [[2026-09-01-howto-nextjs-render-prop-crosses-server-client-boundary]]
