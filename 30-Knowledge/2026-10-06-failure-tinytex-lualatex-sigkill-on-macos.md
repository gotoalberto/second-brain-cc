---
id: 2026-10-06-failure-tinytex-lualatex-sigkill-on-macos
title: TinyTeX lualatex killed instantly with SIGKILL on a Mac with endpoint security
type: failure
area: [tooling, deliverables]
projects: []
tags: [latex, tinytex, lualatex, macos, sigkill, endpoint-security, pdf]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-06
supersedes: []
---

## What was observed

On a Mac with an endpoint security agent installed, TinyTeX's `lualatex` and `luahbtex` had compiled PDFs fine for hours, then
started dying **instantly** with exit code 137 (SIGKILL). Even `lualatex --version` died, before
touching any input. No LaTeX log was written, because the process never got that far. Nothing in
TinyTeX had changed.

## How to read it

Exit 137 on `--version` means the binary is being killed from outside. No `.tex` source is involved. On such a machine the likely sender is the endpoint security agent, which can
kill unsigned or recently touched binaries without warning. That was the suspicion here; no log line
proved it, but the timing (worked, then died, with no change) and the presence of such an agent both
pointed there.

## What to do

- **Stop diagnosing from inside the agent's sandbox.** The cause is a policy on the host; it needs the
  machine's administrators (an allowlist for the TeX binaries) or the user's own investigation.
- **Compiling on another machine (a build server) works, but fetching the PDFs back may be refused.** The permission
  classifier treated pulling compiled files from a remote server to the laptop as a way around a
  restriction. Ask the user for that route explicitly. A yes covers that one request; ask again the
  next time.
- **Do not retry a refused route** without that authorisation; it fails the same way.
- If PDF output does not depend on LaTeX, an HTML template printed with headless Chrome avoids the TeX
  binaries altogether ([[2026-09-10-convention-report-deliverable-shape]]).

## Links

- [[2026-10-17-convention-ask-for-blocked-permissions-with-a-pasteable-command]]
