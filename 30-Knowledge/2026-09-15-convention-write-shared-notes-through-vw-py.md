---
id: 2026-09-15-convention-write-shared-notes-through-vw-py
title: Shared notes are written through vw.py
type: convention
area: [memory-system, tooling]
projects: []
tags: [vw.py, concurrency, locks, redaction, shared-notes, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## The rule

`10-Projects/` and `70-Entities/` are shared across sessions, machines and scheduled jobs.
They are never written with a direct editor or a shell redirect. They go through
`_bin/vw.py`, which takes a per-file lock, redacts credentials, writes atomically and
reindexes the note.

```sh
python3 ~/Brain/_bin/vw.py new 10-Projects/<file>.md --title "<title>" --type project <<'EOF'
body
EOF
python3 ~/Brain/_bin/vw.py append 10-Projects/<file>.md <<'EOF'
text to append
EOF
python3 ~/Brain/_bin/vw.py set 10-Projects/<file>.md ...   # see vw.py --help
```

In Claude Code, `gate_write.py` denies `Write` and `Edit` there, and shell writes too. Without
hooks, the vault's pre-commit hook warns when such a change was not written through `vw.py`.
Other folders (`30-Knowledge/`, `20-Areas/`, `00-Inbox/`) take a normal write with full
frontmatter.

## Traps

- **`append` reads its content from stdin, not from a flag.** `vw.py append <note> --text "..."`
  exits 0 and writes nothing. Use a heredoc, or redirect a file. After an append, check with
  `grep` that the text landed.
- **`append` adds its own timestamp.** Text that already carries one comes out stamped twice.
- **`new` can wait on a git lock held by another session.** That is contention, not a hang.
  Before killing it, check whether the lock belongs to a live session and wait if it does. If
  the target file does not exist yet, killing is safe. If it does exist, a kill mid-write can
  leave a stub with empty frontmatter: check `type`, `area`, `projects`, `tags` and `title`
  before trusting or appending to it.
- **`new` also hangs when nothing is fed to its stdin.** Same symptom as the lock wait, different
  cause: from an agent's shell, stdin is not a terminal, so `new` waits for a body that never comes.
  Tell them apart before assuming the lock case (on Linux, `/proc/<pid>/wchan` shows a read wait and fd
  0 points at a socket). Killing it has the same side effect: a later `append` on that path creates a
  stub with `type: project`, empty `area`, `projects` and `tags`, and the filename as title, with no
  error. Always feed `new` something: a heredoc, `< /dev/null`, or `input=""` (or the real body) when
  calling it through `subprocess`.

## Why

Several writers at once (two sessions, a scheduled job, another machine after a pull) would
otherwise overwrite each other's appends. The redaction step is the last barrier against a
credential reaching a note that gets pushed.

## Links

- [[2026-08-20-decision-credentials-in-keepass]]
- [[2026-09-08-failure-scheduled-tasks-write-into-the-vault-unguarded]]
