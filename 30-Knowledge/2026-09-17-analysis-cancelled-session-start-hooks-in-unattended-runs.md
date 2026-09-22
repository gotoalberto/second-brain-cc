---
id: 2026-09-17-analysis-cancelled-session-start-hooks-in-unattended-runs
title: Cancelled SessionStart hooks in unattended SDK runs and hook liveness
type: analysis
area: [harness]
projects: []
tags: [guardian, hook-liveness, heartbeat, routines, sdk, false-positive]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

## Context

The guardian warned that the session-start hook did not fire in one active session. The session was
an unattended routine run through the SDK.

## Findings

The warning was false. The routine's transcript carries an attachment of type `hook_cancelled` for
`SessionStart:startup`, written before the queued prompt: Claude Code itself cancels the
SessionStart hooks there, so `compass.py` is killed before its heartbeat line is written. Every SDK
run did the same, while the asynchronous skills hook and the prompt hook still wrote their lines.
`compass.py` itself runs in a fraction of a second, so it is not a timeout.

Fix: `HookLivenessSource` in `_bin/guardian_core/adapters.py` reads `hook_cancelled` attachments from
the first 64 KB of each transcript into `SessionTranscript.cancelled`, and `hook_liveness` in
`domain.py` does not call a hook event silent in a session where Claude Code cancelled it. A cancelled
SessionStart does not excuse any other missing hook.

A consequence worth knowing: unattended SDK runs never receive the startup context; they rely on
their own prompt and on the per-prompt retrieval hook.

## Links

- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
