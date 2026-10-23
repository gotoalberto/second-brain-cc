---
id: 2026-10-23-convention-routine-that-publishes-states-it-as-the-users-request
title: An unattended routine that publishes says so first, as the user's explicit request
type: convention
area: [harness, permissions]
projects: []
tags: [routines, headless, classifier, auto-mode, bypasspermissions, publishing, claude-in-chrome, prompt]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-23
supersedes: []
---

## The rule

When a scheduled routine publishes something in the user's name (a post, a reply, a message, a form
submission), its prompt states the publishing case first and as the user's own explicit request:
"On a day marked `Mode: publish`, the user asks you to publish this post: open the composer, attach
the image, press Post." Any prohibition ("publish nothing") is scoped to the cases where it applies,
and never written as the general rule with the publishing case as an exception further down.

## Why

The permission classifier decides whether an action that commits something in a connected app was
requested by reading the prompt text. A routine prompt that opens with "publish nothing, never open
the composer" and only later says "except on marked days" reads, to the classifier, as a run where
publishing was not asked for. The publish click is then denied as an unrequested commit, and that can
happen even in a run started with `--permission-mode bypassPermissions`. The same click in an
interactive session, where the user asked for it in the chat, goes through.

Two separate things can deny a browser action in a bypass run, and they look alike in the log:

- the server-side Chrome classifier floor, which makes every Claude in Chrome action ask; the fix is
  in [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]];
- the classifier's judgement that a commit was not requested, which no setting turns off and only the
  prompt wording fixes.

Check the floor first. If the denial persists with the floor off, the wording is the cause.

## How

- First bullet of the headless instructions: the publishing case, phrased as "the user asks you to
  publish", with the exact steps.
- Prohibitions name their scope: "On every other day, publish nothing."
- Keep a check against publishing twice (a log line read before the click), since a denied run is
  often retried by hand.
- Do not rerun a routine that may have half published. Check the target first.
- A code change in the runner is not the fix: the classifier reads the prompt, so the prompt is what
  changes.

## Example

An invented bakery routine posts the daily bread list on its shop page only on days the owner pinned.
Before: "Never publish. On pinned days, publish the list." After: "On a pinned day the owner asks you
to publish today's list on the shop page: open the editor, paste the list, press Publish, then log the
post. On any other day, publish nothing."

## Links

- [[2026-09-15-convention-headless-agent-prompt-must-be-framed-as-an-order]]
- [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]]
- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-10-17-convention-ask-for-blocked-permissions-with-a-pasteable-command]]
