# First run

The first run connects the optional pieces of the harness on one machine. It asks one step at a
time, and nothing is installed, created or registered without a yes. One step is required: the
local directory where Brain keeps files.

```bash
bash integrations/first-run/setup.sh            # ask what is left
bash integrations/first-run/setup.sh --dry-run  # show what would be installed, save nothing
python3 integrations/first-run/first_run.py status
```

`bootstrap.sh` offers it at the end, and every agent that reads the generated `AGENTS.md` is told to
offer it on its first session on a machine that has not had one (`first_run.py status` exits 3).

## The steps

| step | what a yes does |
|---|---|
| `kdbx` | Records the KeePass database this machine uses (`kp.py init --db PATH`), creating it if you ask (keepassxc-cli asks for its master password), and optionally arms the master cache (`kp.py unlock`) so scheduled jobs can read credentials headless. The default path is `~/Documents/brain.kdbx` on macOS and `~/.local/share/brain/brain.kdbx` on Linux; any local path or synced folder works. |
| `google` | Connects any number of named Google accounts through `_bin/google.py`: for each, a name, its address, and the OAuth client of a Google Cloud project ("Desktop app" client, with the Gmail, Calendar and Drive APIs enabled). The client secret goes to KeePass, never to a file; the browser consent stores the refresh token there too. Needs `kdbx`. |
| `files` | Required. Asks where Brain keeps files (deliverables, intermediate steps, source material) for `_bin/files.py`, proposing `~/BrainFiles`. The directory is created if missing and a test file is written and removed before the answer is accepted; a directory that cannot be used is asked again. The choice is recorded in `<brain state>/files-dir.json` (0600). `BRAIN_FILES_DIR`, when set, overrides it. |
| `alert_email` | Writes `<brain state>/guardian-mail.json` so the guardian emails its alerts: through a connected Google account (Gmail API) or through SMTP with the password in KeePass. |
| `mcp` | Prints the MCP registration for Claude Code, Claude Desktop, Cursor-style clients and OpenCode; offers to run `claude mcp add` when the Claude Code CLI is installed, and to export `BRAIN_VAULT` in your shell profile (backed up first). No other agent's config file is written. |
| `scheduler` | Detects launchd (macOS), systemd user units (Linux with a user session) or cron, asks for each job (guardian, sync, tasks, file watch), shows the exact plist, units or crontab line, and installs only after a final yes. The accepted jobs are recorded, and the guardian repairs and reloads only those. |
| `remote_control` | Makes this machine reachable from the Claude app under Remote Control. Checks first that it can work: a normal user (not root), the `claude` CLI logged in with a claude.ai account (`claude auth status`; API keys and `claude setup-token` tokens are refused), a CLI recent enough for `remote-control --chrome` (asked of the parser with `--chrome --help`, since the help text can hide the flag), and no telemetry switch in `~/.claude/settings.json`; a shell wrapper standing in for `claude` is a warning. Asks the name the sessions carry (proposed: its label from `machine_identity.machine_label()`, the short host name, in lower case) and the working directory to serve from (proposed: the home directory, which needs no git repository; any other folder is created with `git init` if missing; never the vault), starts `claude remote-control --chrome --name <name>` once on the terminal so you answer its one-time prompts (trust the workspace, enable Remote Control, spawn mode **same-dir**), records the directory and name in `<brain state>/remote-control.json`, turns on lingering on Linux (`loginctl enable-linger`), and installs the launchd agent or systemd user unit that keeps the server running. Needs launchd or systemd user units: cron cannot supervise a server. |
| `routines` | Checks the CLI agent named in `90-Meta/agent-command.txt` and adds numbered token references to `90-Meta/routine-tokens.json` (ignored by git), with the command that stores each token in KeePass. Enabling a routine is editing its row in `90-Meta/scheduled-tasks.md`. Needs `kdbx`. |

Declining `kdbx` declines the two steps that need it. `files` is the one step that cannot be
declined: it has no yes or no, and it is asked on every run until it is done.

Every run, and `skip-all`, ends by registering this machine in the machine registry
(`_bin/machines.py register --daily`: at most once a day, and a failure never fails the first run).
The guardian's scheduled repair keeps the entry fresh after that.

## Answers and re-running

Answers live in `<brain state>/first-run.json` (0600). Running the first run again asks only the
steps with no answer. A step that failed is not recorded, so the next run asks it again.

```bash
python3 integrations/first-run/first_run.py status          # exit 0 complete, 3 not yet
python3 integrations/first-run/first_run.py reset scheduler # ask one step again
```

## Unattended machines and CI

`setup.sh` without a terminal changes nothing and exits 0. To mark a machine as set up without
connecting anything:

```bash
python3 integrations/first-run/first_run.py skip-all
```

It creates and records the default files directory (`~/BrainFiles`, or `BRAIN_FILES_DIR` when set)
and records every other unanswered step as declined. If that directory cannot be created it says
why, leaves `files` unanswered and exits 1.

For a smoke test of the scheduler step in a scratch `HOME`, `BRAIN_FAKE_SCHEDULER=1` writes the job
files under that `HOME` and never calls launchctl, systemctl or crontab.
