---
id: 2026-09-15-reference-cli-total-cost-usd-is-an-estimate-not-a-bill
title: Cost figure in the Claude Code CLI JSON output under a subscription token
type: reference
area: [harness, ai-agents]
projects: []
tags: [claude-code-cli, oauth, billing, subscription, routines, reference]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Content

When the Claude Code CLI runs non-interactively with JSON output (`claude -p ... --output-format
json`) and authenticates with a long-lived OAuth token from `claude setup-token`, its output still
carries a `total_cost_usd` field computed from token counts at public API prices, whatever the
authentication method.

When the token belongs to a flat-rate subscription account, that number is not a charge. Usage draws
on the plan's own limits and nothing extra is billed, unless the account has paid usage beyond the
plan enabled in its settings. Check your own account settings rather than trusting this note, since
plans change.

- **Do not treat `total_cost_usd` as spend** for runs authenticated with a subscription token. Use
  it as a rough size of the work.
- **Hitting the plan limit shows up as a distinct failure**, not as a rising cost figure. That
  failure is the signal a token pool with failover acts on.
- `claude setup-token` runs the same browser login as an interactive login, so the token belongs to
  whichever account was chosen in that browser session, with that account's usage and limits.

## Links

- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-09-convention-memory-must-not-assert-mutable-state]]
