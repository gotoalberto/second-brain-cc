---
name: save
description: Saves what this session learned into the Brain vault: decisions, conventions, project state. Use it before closing any session that changed code or made decisions, and whenever the user asks you to save or remember something.
argument-hint: [what to save, optional]
---

Invoke the `librarian` subagent so it writes to the vault whatever deserves to outlive
this session.

Pass it, in the delegation message:
- **What was done**: actual changes, with file paths.
- **What was decided and why**: above all, the alternatives that were discarded and the
  reason. That is what the code does not hold, and what is worth most three months from
  now.
- **What was learned**: conventions discovered, traps found, commands that work in this
  project.
- **What is still open** and what is blocking it.
- **Files produced in the session**: every deliverable, intermediate and source file that
  exists only outside the vault (a scratch directory, `/tmp`, a worktree about to be removed,
  files sent to the user, for example with SendUserFile). For each one: absolute path, kind
  (deliverable, intermediate or material), the project slug and a one-line caption.
  Transcripts, generated HTML, PDFs, screenshots and datasets all count. Skip only what already lives in a git repository that will survive,
  or a raw download that can be fetched again (name where it lives instead).
  Build this list yourself before delegating: look back over the session and list the scratch
  directory. The librarian cannot see it and will not know those files exist unless you say so.
- The user's specific instruction, if any: «$ARGUMENTS».

## Files go to the files directory, anchored to a note

The librarian stores every listed file in the local files directory chosen during the first run:

```bash
python3 ~/Brain/_bin/files.py put <file...> --to <note it wrote or updated> \
  --project <slug> --kind deliverable|intermediate|material --caption "what it is"
```

`--to` is the note that explains the files, usually the one it just created. If no active
project fits, use a short descriptive slug (for example `team-meetings`); the slug is a folder in
the files directory, not a vault project, so it needs no new project note.

When it returns, verify with `python3 ~/Brain/_bin/files.py ls --project <slug>` that every file
is there, and store what is missing yourself. If `files.py` says no files directory is configured,
tell the user where the files are, that they were not archived, and that
`integrations/first-run/first_run.py run` sets the directory up.

Rules:
- **Everything written into the vault goes in English**: `title:`, `tags:`, the prose.
  A verbatim quote keeps the language it was said in, with the English alongside. Answer
  the user in their language; the note goes in English, because retrieval is lexical and a
  note in another language is unreachable by search:
  `~/Brain/30-Knowledge/2026-09-08-convention-vault-is-written-in-english.md`.
- Do not invent content as filler. If there genuinely is nothing memorable, have the
  librarian say so and write nothing.
- No credentials in notes: they go to the kdbx through `/kp`, and the note keeps the `kp://` reference.
- When done, say in two lines which notes were created or updated, with their paths.

If the librarian wrote anything, sync the vault instead of waiting for the daemon:

```bash
python3 ~/Brain/_bin/vault_sync.py
```

The daemon runs every 10 minutes, so without this whatever was just saved lives only on
disk for that long. It is the same script the daemon runs, serialised with flock and
with `pull --rebase`, so calling it by hand causes no races and no duplicate commits.
Do not call it if the librarian wrote nothing: there is nothing to commit and it only
adds noise to the log.
