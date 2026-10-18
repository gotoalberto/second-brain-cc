---
id: 2026-10-16-runbook-vw-py-needs-stdin-closed
title: How vw.py reads its body from stdin, and why it no longer hangs
type: howto
area: [memory-system, tooling]
projects: []
tags: [vw.py, stdin, hang, socket, shared-notes, runbook]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-16
supersedes: []
---

## What was wrong

`vw.py new` read its body with `sys.stdin.read() if not sys.stdin.isatty() else ""`, and `append` and
`set` read stdin unconditionally. An agent's shell tool can hand the process a unix socket on fd 0
that is not a terminal and never reaches EOF, so the call waited for ever: no output, no error. Killing
it mid write left a stub note that a later `append` silently filled in. The workaround, documented in
[[2026-09-15-convention-write-shared-notes-through-vw-py]], was to remember `< /dev/null` on every call,
and it kept being forgotten.

## The fix

`_bin/vw.py` has one helper, `read_body(required)`, used by `new`, `append` and `set`. It reads stdin
only when fd 0 is a regular file or a pipe, the only two things that can carry a body. Anything else
(a socket, `/dev/null`, a terminal, a closed or unusable fd) counts as no body:

- `new` carries on and writes the note with its frontmatter only.
- `append` and `set` fail at once with `vw: nothing on stdin. Pass the body with a heredoc, a pipe or
  '< file'.` and exit code 2.

A heredoc, a pipe and `< file` work as before; `< /dev/null` is no longer needed; a missing body is an
error in under a second instead of a hang.

```sh
python3 ~/Brain/_bin/vw.py append 10-Projects/<note>.md <<'EOF'
text to append
EOF
printf '%s\n' "text to append" | python3 ~/Brain/_bin/vw.py append 10-Projects/<note>.md
```

## How it is held

`_bin/vw_stdin_test.py` covers a socket on fd 0 for both modes (body optional and required), a pipe,
a file, `/dev/null`, a terminal and an unusable fd.

## What this does not change

- Killing `vw.py` mid write still corrupts the note.
- The other wait is real: `new` can block on the index git lock held by another live session. If
  `vw.py` takes a while now, it is that lock. Wait for it instead of killing it.

## Links

- [[2026-09-15-convention-write-shared-notes-through-vw-py]]
