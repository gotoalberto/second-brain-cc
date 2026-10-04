---
id: 2026-08-30-convention-derive-one-exhaustive-ui-state
title: Derive one exhaustive UI state instead of writing states as independent conditions
type: convention
area: [frontend]
projects: []
tags: [react, ui-state, react-query, tanstack-query, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The rule

When a component shows one of several mutually exclusive states (not configured, loading, error, empty,
loaded), **derive a single value that covers every case exhaustively** and switch on it, instead of
checking each state as its own `if` or ternary.

```ts
type View = "unconfigured" | "loading" | "error" | "empty" | "ready";

function viewOf(q: QueryLike, configured: boolean): View {
  if (!configured) return "unconfigured";
  if (q.error) return "error";
  if (q.data === undefined) return "loading";   // pending, fetching or paused alike
  return q.data.length ? "ready" : "empty";
}
```

## Why

A page with four hand-written conditions rendered nothing in production because all four were false at
once. React Query v5's `isLoading` is `isPending && isFetching`, so a query that is pending but not
fetching (exactly where a paused query sits) matched none of them, and the component fell through to
nothing. Independent booleans over a state with more combinations than the ones enumerated always leave a
gap, and the gap fails silently. A derived closed set forces every input to map to one visible output.

Collapsing the conditions is also what made the next bug visible at all.

- Read a library's definition before branching on booleans that look mutually exclusive by name
  (`isLoading`, `isFetching`, `isPending`).
- Give the derivation a unit test per state, including the combinations the library can produce.

## A query stuck in a paused state

The query in that page then sat in `fetchStatus: "paused"` forever, with no error. Setting
`networkMode: "always"` on the query and on the client defaults did not release it. For a screen that
performs a single read, a twenty-line hook with three explicit states (loading, error, data) replaced the
library and fixed it. Caching and retries pay off when several related reads share them; for one read,
an internal state machine the app cannot observe or steer is a cost.

When live polling looks frozen, first check that the tab is focused or visible: background tabs do not
run `refetchInterval` ([[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).

## Links

- [[2026-09-02-convention-interface-copy-and-data-labels]]
