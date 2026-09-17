# Second Brain

Persistent memory and a working protocol for **any AI agent**: an
[Obsidian](https://obsidian.md)-compatible vault of Markdown notes plus a small,
standard-library-only Python engine with a SQLite FTS5 search index and a git-synced repo.
Notes survive across sessions and machines, and a lightweight protocol tells the agent how
to search that memory, isolate its work and write back what it learned.

It is **agent-agnostic**. The knowledge and the engine are plain files and stdlib Python;
agents connect through thin integrations: an MCP server, a CLI, or a native Claude Code
layer. Swap the agent, keep the brain.

## Why

Agents start every session with a blank slate. They forget the decision you made last
week, the convention this repo follows, and who the people and systems in your world are.
This project gives an agent two things:

- **Persistent memory**: durable notes (decisions, conventions, how-tos, project state,
  people and systems) that outlive any single session.
- **A working protocol**: a repeatable loop that searches the vault for context first,
  works in isolation, then saves what changed.

## Ways to connect your agent

The vault is the same for all of them; pick whichever your assistant speaks.

| Integration | For | Setup |
|---|---|---|
| **[MCP server](integrations/mcp/)** | Any MCP agent: Claude Desktop, Cline, Cursor, Continue, Zed, Windsurf, OpenCode, your own client | Point it at `integrations/mcp/server.py` (the first run prints the snippets) |
| **[CLI](integrations/cli/)** | Any agent that can run a shell, and you at a terminal | Put `integrations/cli/brain` on your `PATH` |
| **[Claude Code](integrations/claude-code/)** | Automatic recall, agents, skills | `bash integrations/claude-code/install.sh` |

All of them drive the **same** `_bin/` engine, so redaction, locking, indexing and the
frontmatter contract hold no matter which agent is writing. Avoid running two write-back
integrations at once. [OpenCode](integrations/opencode/) has a worked example.

## Quick start

```bash
git clone https://github.com/gotoalberto/second-brain-cc.git ~/Brain
bash ~/Brain/bootstrap.sh
```

`bootstrap.sh` checks Python and SQLite/FTS5 (the only hard requirement), notes which
optional tools are present, builds the index, runs a health check and offers the
[first run](#first-run). It installs nothing into any agent and schedules nothing.

If you clone somewhere other than `~/Brain`, export `BRAIN_VAULT=/path/to/vault` (the first
run offers to add it to your shell profile); the MCP server and the CLI also detect it.

**Requirements:** Python 3.9 or newer with SQLite/FTS5 (bundled with CPython) and `git`, on
macOS or Linux. Optional: [KeePassXC](https://keepassxc.org) for credentials and Obsidian as a
GUI.

## First run

```bash
bash integrations/first-run/setup.sh          # ask what is left, one yes at a time
python3 integrations/first-run/first_run.py status
```

The first run asks, step by step, whether to connect each optional piece, and installs
nothing without a yes: a KeePass database, Google accounts, an alert email for the guardian,
the MCP server for your agents, scheduled jobs (launchd on macOS, systemd user units on Linux,
cron where systemd is absent), and CLI-agent routines with a token pool. It also asks where to
keep files, proposing `~/BrainFiles`. That step is required: the directory is created and
recorded before the run can complete.
Answers are remembered in `<brain state>/first-run.json`, so re-running resumes where it
stopped. Every agent that reads the generated `AGENTS.md` is told to offer it in its first
session on a machine that has not had one. Details:
[`integrations/first-run/README.md`](integrations/first-run/README.md).

`<brain state>` is `BRAIN_STATE` when set, otherwise `~/Library/Application Support/brain` on
macOS and `~/.local/state/brain` on Linux (`_bin/brain_paths.py`).

Files (deliverables, intermediate steps, source material) live in that directory, outside the
vault, and the note that explains each one keeps its key. `BRAIN_FILES_DIR` overrides the
directory chosen in the first run (`_bin/brain_files.py`).

```bash
python3 _bin/files.py put report.pdf --to 30-Knowledge/<note>.md --project <slug> \
  --kind deliverable --caption "what it is"      # kinds: deliverable, intermediate, material
python3 _bin/files.py ls --project <slug>
python3 _bin/files.py get <key> --out <dir>
python3 _bin/files.py check                      # broken references and orphaned files
```

## Multiple machines

By default everything above is single-machine: one vault, one local KeePass database, one
files directory. If you run this on more than one machine and already sync a folder between
them — Dropbox, iCloud Drive, a NAS mount, a USB drive — the first run's `multi_machine` step
can point at it, and two things start coordinating over it:

- **Presence.** Each machine's heartbeat also lands at
  `<shared>/presence/<project>/<machine key>__<sid>`, so `presence.py view` (and anything that
  reads its cache) can tell you someone on ANOTHER machine has the same project open, not just
  this one.
- **File claims.** `_bin/claims_sync.py` lets a session declare which files it is editing —
  `claims_sync.py claim <path...> --sid <sid>`, `claims_sync.py release <path...> --sid <sid>` —
  as a warning for another machine to read (`claims_sync.py view`), the same way `lease.py`
  warns two sessions on one machine. This is informational only: it is not wired into the
  write gate or into `claim.py`'s local table, so nothing blocks a write because of it.

The machine identity behind both is `_bin/machine_identity.py`: a hostname plus the first 8 hex
characters of a hardware/boot UUID (`ioreg` on macOS, `/etc/machine-id` or
`/sys/class/dmi/id/product_uuid` on Linux), so two machines that happen to share a hostname do
not collide. Only that short derived key is ever written anywhere; the full UUID never is.

**The harness never syncs this folder itself.** It only reads and writes files under the path
you give it — keeping that path synced between your machines (Dropbox, iCloud, your NAS's own
mechanism) is entirely up to whatever already syncs it for you.

```bash
python3 _bin/claims_sync.py claim src/x.ts --sid <sid>    # declare a claim
python3 _bin/claims_sync.py view                          # fresh claims held by OTHER machines
python3 _bin/claims_sync.py reap                           # clean up claims nobody is renewing
```

- The shared path is `BRAIN_SHARED_DIR`, else what the first run's `multi_machine` step
  recorded in `<brain state>/shared-dir.json` (`_bin/brain_shared.py`). Unconfigured (the
  default), nothing above does anything extra: single-machine behaviour is unchanged, byte for
  byte.
- Declining the `multi_machine` step (or skipping it with `first_run.py skip-all`) is the
  default and always allowed — unlike the files step, it is never required.
- A claim nobody renews for longer than 15 minutes plus a 2-minute margin is treated as
  orphaned (a crashed session, a machine that vanished) and reaped automatically, piggybacked
  on the same 120 s cadence the presence heartbeat already runs on — no separate scheduled job.

### A second KeePass client: `kpcli`

If two machines share a `.kdbx` over that same synced path, both need a way to read it.
`keepassxc-cli` (the default `kp.py` already speaks) is not installable everywhere; a machine
that has Perl instead can use `kpcli`'s underlying module, `File::KDBX`, through
`_bin/kp_kdbx.pl`:

```bash
cpanm --local-lib=~/perl5 File::KDBX     # optional: only for the kpcli backend
BRAIN_KP_BACKEND=kpcli python3 _bin/kp.py ls
```

- Set with `BRAIN_KP_BACKEND=kpcli`, or leave it unset: `kp.py` prefers `keepassxc-cli` and
  only falls back to `kpcli` when nothing finds it. The default stays `keepassxc-cli`, unchanged.
- `_bin/kp_backend.py` covers exactly what `kp.py` actually issues through its central `cli()`
  function: `ls`, `search`, `show`, `mkdir`, `add`, `edit`. Everything else the kpcli backend
  does not cover (`clip`, `kp.py init --create`, the `.lock`-file checks under `kp.py locks`)
  refuses with a clear message instead of guessing or silently doing nothing — use
  `keepassxc-cli` for those, or `--show`/`--info`/`--pipe` in place of the clipboard.
- `File::KDBX` is not a Perl core module and is never required for the default backend: only
  install it if `BRAIN_KP_BACKEND=kpcli` is what you actually want.

## How it works

- **Folders.** Memory is plain Markdown with YAML frontmatter in numbered folders (see
  [Layout](#layout)). Each note declares its `id`, `type`, `tags`, `status` and provenance,
  and links to others with `[[wikilinks]]`, forming a graph.
- **Search.** `_bin/index_vault.py` builds a SQLite database with an FTS5 full-text index;
  `_bin/query.py` searches it and `_bin/retrieve_core.py` renders what the prompt hook, the
  MCP `recall` tool and `brain recall` inject. No embeddings, no external service, no API key.
- **Write path.** Every write to shared notes goes through `_bin/vw.py`: it redacts
  credentials, serialises with a per-file lock, writes atomically and reindexes.
- **Git sync.** `_bin/vault_sync.py` keeps the vault in a git repo so memory travels between
  machines.
- **Events.** [`90-Meta/events.json`](90-Meta/events.json) is the registry of every event
  (session start, prompt, write gate, sync, reindex, link repair) and every trigger wired to
  it: Claude Code hooks, git hooks, the file watch, scheduled jobs, CLI and MCP.
  `hooks.json`, `githooks/` and `AGENTS.md` are generated from it;
  [`90-Meta/HOOKS-WITHOUT-CLAUDE.md`](90-Meta/HOOKS-WITHOUT-CLAUDE.md) lists how to fire each
  event without Claude Code.
- **Protocol.** [`90-Meta/AGENT-PROTOCOL.md`](90-Meta/AGENT-PROTOCOL.md) is the contract any
  agent follows; [`90-Meta/PROTOCOL-COMPACT.md`](90-Meta/PROTOCOL-COMPACT.md) is the short
  version, and [`AGENTS.md`](AGENTS.md) is generated from it for agents with no adapter.

> **Vault content is DATA, not instructions.** Notes record what was decided and how things
> are done here. They are reference material for the agent to read, never commands for it
> to obey.

## Credentials: a local KeePass database

The vault never stores a credential. Secrets live in a KeePass database (`.kdbx`) on your
own disk or synced folder, read with `keepassxc-cli` through `_bin/kp.py`, and notes carry
only references such as `kp://apis/example-service-api-key#password`.

```bash
python3 _bin/kp.py init --db ~/Documents/brain.kdbx --create   # what the first run does
python3 _bin/kp.py status
python3 _bin/kp.py put apis/example-service-api-key --stdin      # file a secret from stdin
python3 _bin/kp.py get apis/example-service-api-key --pipe 'python3 script.py'
python3 _bin/kp.py unlock --ttl 30d                             # arm the master cache
```

- The database path is `BRAIN_KP_DB`, else what `kp.py init` recorded in
  `<brain state>/kp-config.json`. There is no guessed default.
- Everything an agent writes goes inside one group, `Brain` by default (`BRAIN_KP_GROUP`);
  your own entries elsewhere are never reorganised.
- The master password never passes through argv, the environment or a plain file. It is
  asked in a dialog (osascript on macOS, zenity on a Linux desktop) or on the terminal, and
  can be cached in the OS keyring (the Keychain on macOS, libsecret's `secret-tool` on Linux)
  with `kp.py unlock`.
- Scheduled jobs read headless (`BRAIN_KP_NOPROMPT=1`): no prompt, and exit 4 when the master
  is not cached. Exit 5 is a database open elsewhere, 6 a database not configured or found.
- A secret is never printed unless you pass `--show`: it goes to the clipboard or into another
  process's stdin. Every write takes a backup first and verifies the database afterwards.

## Google accounts

`_bin/google.py` reaches Gmail, Calendar and Drive, read and write, through Google's REST APIs
for any number of named accounts, with no connector and no third-party library.

```bash
python3 _bin/google.py add --account personal --client-id <id> --login-hint me@example.com  # secret on stdin
python3 _bin/google.py auth --account personal        # browser consent on 127.0.0.1
python3 _bin/google.py api --account personal "https://www.googleapis.com/calendar/v3/users/me/calendarList"
python3 _bin/google.py send --account personal --to me@example.com --subject "Digest" --body-file digest.txt
```

Each account has its own OAuth client ("Desktop app" client in a Google Cloud project with the
Gmail, Calendar and Drive APIs enabled) and refresh token, both in KeePass under
`google/<account>/`. `api` prints Google's reply and exits 1 on an HTTP error; `token`, `api`
and `send` never prompt. Every delivered message is logged (never its body) to
`<brain state>/logs/mail-sent.jsonl`, which the routine runner checks.

## Guardian and scheduled jobs

`_bin/guardian.py` keeps the machinery wired with no AI agent involved. When you accept it in
the first run it runs `repair` every 15 minutes: it merges the vault's hooks into each agent's
config (backing it up, removing only Brain hooks whose script no longer exists), syncs skills
and agents, sets `core.hooksPath` to the vault's `githooks/`, reinstalls or reloads the
scheduled jobs you accepted, probes that the hooks actually fire, and alerts you (desktop
notification, email if configured, log) about what it could not fix. A repair run exits 0 when
it completed, whatever it found. `guardian.py status` shows everything it watches.

The jobs it can manage are the guardian itself, the git sync, the task runner and the file watch.
Their templates live in `_bin/` (`com.secondbrain.*.plist`, `systemd/second-brain-*`,
`cron/second-brain-*`); only the ones accepted in the first run are ever installed.

## Routines and the two schedulers

- **`_bin/tasks.py`** runs the table in [`90-Meta/scheduled-tasks.md`](90-Meta/scheduled-tasks.md):
  `shell` commands and `agent` routines, pinned to machines. An `agent` routine
  (`90-Meta/routines/`, see the [example](90-Meta/routines/example-routine.md)) runs through the
  CLI agent named in [`90-Meta/agent-command.txt`](90-Meta/agent-command.txt), with a token from
  the pool in `90-Meta/routine-tokens.json` (KeePass references only, never committed), a narrow
  tool allowlist, a private scratch directory per run, a prompt framed as an order to run now, and
  a success contract checked against the send log rather than the model's last words. Failures
  raise guardian alerts.
- **[`integrations/scheduler/`](integrations/scheduler/)** is the simplest option: Markdown tasks
  with a cron expression and a prompt, handed to any agent command on stdin.

They coexist; a task belongs in one of them.

## Skills

Published under `integrations/claude-code/plugin/brain/skills/` and installed by
`integrations/claude-code/install.sh`. Where a skill needs the vault's path it says `__VAULT__`,
which the installer replaces with yours.

| Skill | What it does | What it needs |
|---|---|---|
| `task` | Runs a task end to end: context, worktree, plan, implementation, verification, write-back | The vault and Python |
| `ctx` | Gathers a task's context into a Context Pack before any work | The vault |
| `recall` | Searches the vault for past decisions and conventions | The vault |
| `save` | Writes what a session learned into the vault | The vault, and the files directory chosen in the first run, where `files.py` stores the session's files |
| `vault-doctor` | Diagnoses the vault and the memory system | The vault; reads `guardian.py status` when the guardian is installed |
| `kp` | Reads and files credentials in your KeePass database | KeePassXC (`keepassxc-cli`) and a database connected in the first run |
| `dev` | The development pipeline: hexagonal architecture, tests first, design and review gates for anything with an interface | The third-party skills below, and a browser or preview tool for the rendered checks |
| `job-search` | Finds openings and prepares applications from your own profile | A Google account connected with the send scope; your own `profile.md`, `preferences.md` (recipient address, account name) and `search-queries.md` created from the skill's `templates/` under `80-Private/job-search/` (local, never pushed); `curl` and `jq` |

### Third-party skills used by `dev`

Not shipped here (their licences are their authors'); install them separately:

| Skill | Source | Example install |
|---|---|---|
| `impeccable` | https://impeccable.style | see its site |
| `frontend-design` | Anthropic's public skills repository | `npx skills@latest add anthropics/skills -g -a claude-code -s frontend-design -y` |
| `design-taste-frontend` | `leonxlnx/taste-skill` | `npx skills@latest add leonxlnx/taste-skill -g -a claude-code -s design-taste-frontend -y` |
| `emil-design-eng`, `animate`, `animate-expo`, `find-animation-opportunities`, `review-animations`, `apple-design` | Emil Kowalski's skills repository | `npx skills@latest add emilkowalski/skills -g -a claude-code -s '*' -y` |

## Agent orchestration

How a task is split across subagents, and how to change it. The reasoning behind it:
[`30-Knowledge/2026-09-15-convention-agent-orchestration-per-task.md`](30-Knowledge/2026-09-15-convention-agent-orchestration-per-task.md).

**The roster** (`integrations/claude-code/plugin/brain/agents/*.md`):

| Agent | Model | Effort | Tools |
|---|---|---|---|
| `context-scout` | haiku | medium | Read, Grep, Glob, Bash, Write |
| `planner` | sonnet | high | Read, Grep, Glob, Write, Bash |
| `implementer` | the session's model | inherited | all tools |
| `verifier` | sonnet | high | read and execute only |
| `librarian` | sonnet | medium | Read, Write, Edit, Bash, Grep, Glob |
| `skill-forge` | sonnet | medium | the librarian's tools plus Skill |

To change a model, effort or tool list, edit that agent's frontmatter and run
`python3 _bin/install_plugin.py sync`.

**The pipeline per task:**

1. `context-scout` distils the context into a Context Pack.
2. `planner` turns it into a plan with the files to touch, for tasks that span more than one file.
3. `implementer` works in a git worktree, never the main checkout.
4. `verifier` checks that it builds, passes and does what it claims. At most two rounds of fixes;
   if it still fails, stop and tell the user.
5. Integration: rebase on the target branch and verify again.
6. `librarian` writes what was learned back to the vault.

One subagent per step, in the foreground, unless steps are genuinely independent. When
parallelising: one worktree per implementer with explicit file ownership, files registered with
`_bin/claim.py`, a verifier per branch, then rebase, run the suite on every supported interpreter
and fast-forward merge. Keep a single multi-agent workflow under about 15 agents unless the user
asks for more.

**The development gates** (the `dev` skill): hexagonal structure (a pure domain, use cases on
ports, adapters at the edge), tests written and seen failing before the implementation, the
standard library unless a dependency is agreed, and for anything with an interface, the design
and review steps of the skill.

**Headless routines** use the agent command in `90-Meta/agent-command.txt` and the token pool
described above, so they run with no desktop app open and on no particular logged-in account.

## What is tied to Claude Code, and what is not

- **Agent-agnostic:** the vault, the search index and every `_bin/` tool; the MCP server and the
  CLI; `kp.py`, `google.py` and `files.py`; the event registry, git hooks and the file watch; the
  guardian's scheduled jobs and alerts; the task runner (any CLI agent through
  `agent-command.txt`); the first run; `AGENTS.md`.
- **Claude Code only:** automatic recall on every prompt, the stop gate and the other hooks; the
  subagent roster and skills; the guardian's hook liveness probe, which reads Claude Code's
  transcripts. Other agents get the manual equivalents listed in `AGENTS.md` and
  `90-Meta/HOOKS-WITHOUT-CLAUDE.md`.

The deepest experience today is Claude Code with the plugin; nothing in the vault requires it.

## The engine (`_bin/`)

| Tool | Purpose |
|---|---|
| `index_vault.py`, `query.py`, `retrieve.py` / `retrieve_core.py` | Index, search and per-prompt retrieval. |
| `linkfix.py` | Find broken `[[links]]` and fix the ones with a safe fix; runs on every search. |
| `vw.py` | The only write path for shared notes (redact, lock, atomic, reindex). |
| `vault_sync.py` | Commit and push over git. |
| `doctor.py` | Health report. |
| `kp.py` | Credentials in a local KeePass database. |
| `google.py` | Named Google accounts: Gmail, Calendar, Drive. |
| `files.py` / `files_core.py`, `brain_files.py` | The file store: deliverables, intermediates and material in a local directory, anchored to notes; where that directory is. |
| `guardian.py` | Keeps hooks, git hooks and scheduled jobs wired, and alerts. |
| `brain_watch.py` | The file watch and the generated hooks. |
| `tasks.py` | The periodic task and routine runner. |
| `gen_instructions.py` | Generates `AGENTS.md`, `CLAUDE.md` and `90-Meta/HOOKS-WITHOUT-CLAUDE.md`. |
| `install_plugin.py`, `claude_settings.py` | Skills and agents sync; recommended Claude Code settings. |
| `brain_paths.py`, `migrate_state.py`, `pywrap.sh` | Where state lives; moving it out of `~/.claude`; the interpreter picker jobs start through. |
| `run_all_tests.py` | Every test, each in a scratch HOME. |

## Conventions that ship with it

`30-Knowledge/` carries working conventions the protocol links to. They are generic and meant to
be edited to your taste: the vault is written in one language because search is lexical; replies
and documents read like a person wrote them; a change is done when it is verified; one worktree
per deliverable; smoke checks isolate all state; a headless agent prompt is framed as an order; a
routine's success is checked in its log, not in the model's last words; scheduled jobs exit
non-zero for a crash, not for findings; no hosted connectors, only mechanisms you control.

## Tests and CI

```bash
python3 _bin/run_all_tests.py            # every *_test.py, each with its own HOME and BRAIN_STATE
```

No test reaches the real machine: KeePass, Google, launchctl, systemctl, crontab and agent CLIs are
fakes, and state lives in temporary directories. CI runs the suite on macOS and Linux with Python
3.9 and 3.14 ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

## Portability

To run under a different provider or write your own integration, see
[`90-Meta/PORTABILITY.md`](90-Meta/PORTABILITY.md): search with `query.py`, write with `vw.py`,
sync with `vault_sync.py`.

## Layout

```
00-Inbox/       quick unsorted captures, triaged later
10-Projects/    one note per active project (written via vw.py)
20-Areas/       ongoing areas of responsibility
30-Knowledge/   durable notes: decisions, conventions, how-tos, references, runbooks
40-Skills/      catalogue of reusable skills (generated)
50-Sessions/    per-session summaries (machine-written)
70-Entities/    one note per person, company or system (written via vw.py)
80-Private/     local-only, never pushed
90-Meta/        protocol, event registry, task registry, routines, templates
_bin/           the Python engine and its tests; job templates (plists, systemd/, cron/)
githooks/       generated git hooks (core.hooksPath)
integrations/   mcp/, cli/, claude-code/, opencode/, scheduler/, first-run/
AGENTS.md       generated protocol for any agent; CLAUDE.md points to it
```

Everything in this repo is public and generic, with placeholder examples only. Replace them with
your own notes and make it yours.
