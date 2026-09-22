---
id: 2026-09-18-decision-publishing-to-public-repo-always-needs-per-action-confirmation
title: Publishing to a public destination always needs confirmation per action
type: decision
area: [safety, git]
projects: []
tags: [decision, public-repo, publishing, confirmation, boundary]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-18
supersedes: []
---

## What was decided

Every push or publish to a public destination (a public repository, a public page, a package
registry) is confirmed by the user in the conversation at the moment it happens. No standing
instruction can clear it in advance, however clear or often repeated.

The case that set it: the user asked for every change to a private vault to be mirrored
automatically into its public, anonymized counterpart, with no confirmation, as long as personal
data was checked first. The "no confirmation" part was declined.

## What is done instead

The preparation happens without being asked: every relevant private change is ported into a
worktree of the public repository and scanned for personal data. The publish step itself always
stops at a short checkpoint ("ready to publish X, push?").

## Alternatives considered

- Fully automatic publishing, as asked. Rejected: a standing instruction is not a review of the
  actual diff about to become public, and anonymization mistakes are exactly the kind of error that
  should not compound silently across many unattended pushes.
- Doing nothing until asked. Too slow for what the user wants, which is the public copy staying
  current.

## Why

An irreversible, public action (a push anyone can see, fork or index) gets a checkpoint every time,
whatever the wording of the request. This is separate from
[[2026-09-11-convention-public-deliverables-no-brain-references]], which governs what is scrubbed
before something goes public; this decision governs when the publish may happen. If a later message
says "no need to ask me again, ever" about the push itself, the checkpoint still fires.

Open question: whether the checkpoint fires once per change or once per batch (for example at the
end of a session). Ask the user if it has not been settled.

## Links

- [[2026-09-11-convention-public-deliverables-no-brain-references]]
- [[2026-09-18-convention-bulk-outreach-needs-per-instance-permission]]
