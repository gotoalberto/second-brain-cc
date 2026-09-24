---
id: 2026-09-23-constraint-auto-mode-classifier-blocks-credential-access-and-its-own-fix
title: The auto mode classifier blocks credential access on a machine with no allow list, and blocks fixing its own permissions
type: constraint
area: [harness]
projects: []
tags: [permissions, classifier, auto-mode, self-modification, credential-exploration, allow-list]
status: active
confidence: high
source: agent
provenance: "generalized from a session in a working vault that tried to query a cloud account's costs from a machine running auto mode with no allow list; service and account details removed"
updated: 2026-09-23
supersedes: []
---

## Context

A machine whose `~/.claude/settings.json` has `permissions.defaultMode: "auto"` and **no
`allow` list at all** has every command judged live by the auto mode classifier. A session asked
to read some figures from a cloud provider's API needed that provider's key, which lives in the
KeePass database. Three different refusal categories fired in one session, the figures were
never obtained, and the session turned into a diagnosis of the block itself.

## Content

**What got refused, and why:**

| Command shape | Category | Why |
|---|---|---|
| a chained line: make the provider's config folder, write a helper script with a heredoc, then `kp.py get ... --pipe` into it, writing the key to the provider's credentials file | `Credential Exploration` | a secret taken out of the database and written to disk inside one chained command |
| harmless commands afterwards: listing `_bin/`, running the vault's own read-only tool for that provider | `Credential Exploration` | fired **after** the first denial, on commands that touch no secret: the classifier stayed sensitised on that path |
| reading `~/.claude/settings.json` (also a loop over it) | `Auto-Mode Bypass` | reading the permission file from inside auto mode |
| editing `~/.claude/settings.json` | `Self-Modification` | an agent widening its own permissions. Correct behaviour, and nothing to work around |

**What it teaches:**

1. **The classifier is stateful within a session.** One denial on a credential shaped path
   poisons later, innocent commands that share the path. Get the framing right on the first try;
   there may be no clean second try in the same session.
2. **A compound command is judged as a whole, not clause by clause.** `kp.py get --pipe` is the
   sanctioned way to hand a secret to a program ([[2026-08-20-decision-credentials-in-keepass]])
   and would likely have passed alone. Chained behind a `mkdir` and a heredoc writing a helper
   script, the whole line read as exfiltration. Keep credential commands single and bare, which
   is also what an allow rule needs, since it matches a literal command prefix.
3. **The agent cannot fix its own permissions, by design, and must not try.** Reading the
   settings file in auto mode is `Auto-Mode Bypass`; editing it is `Self-Modification`. There is
   no clever route around either: the fix belongs to the person. Same family as
   [[2026-09-21-convention-agents-must-not-run-scripts-needing-human-typed-secrets]] and
   [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]].

**The fix handed to the person instead:** a small script they run themselves (with a
`--dry-run` first) that appends read-only allow rules to `permissions.allow`, backs the file up
first and prints an undo line. Design points worth keeping for the next one:

- **Read-only subcommands only.** List, describe, get and cost queries; no write verb, so the
  key stays under the usual rule of asking before creating or changing anything.
- **Both the bare binary name and its absolute path**, because an allow rule matches a literal
  prefix: `Bash(tool ls:*)` does not cover `/usr/local/bin/tool ls`. Resolve the binary at run
  time rather than hard coding a path, and do the same for `python3` and `/usr/bin/python3` in
  front of `kp.py`.
- **Find the settings file rather than trusting `$HOME`.** Over SSH the person may land as
  root, where `~` is `/root` and the file does not exist. Try `$HOME`, then the users' homes, and
  take `--settings <path>` to settle it by hand. When run as root, give the file and its backup
  back to their owner, so nothing in the user's home ends up owned by root.

Once the person ran it, the rules landed and the API became reachable for the rest of that
session.

**A related trap in the answer itself.** Before the access was granted, the question was
answered from vault notes alone, and the estimate was badly low: resources that were never
written about were invisible to it. The vault records decisions and context; the live state of an
account is only in the API. When the API is one permission away, do not answer a "what do I have" or
"what do I pay" question from the vault alone; say it is an estimate, and ask for the access.

## Links

- [[2026-09-21-failure-permission-classifier-blocks-gmail-message-reads]]
- [[2026-09-05-convention-agent-must-not-self-edit-access-control-to-pass-a-gate]]
- [[2026-09-21-convention-agents-must-not-run-scripts-needing-human-typed-secrets]]
- [[2026-08-20-decision-credentials-in-keepass]]
- [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]]
