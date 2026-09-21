---
id: 2026-09-21-runbook-install-on-a-new-machine
title: Runbook for installing the harness on a new machine and reaching it from the Claude app
type: howto
area: [harness]
projects: []
tags: [install, machines, remote-control, macos, linux, launchd, systemd, chrome, kdbx, runbook]
status: active
confidence: high
source: agent
provenance: "generalized from real installs on a macOS laptop and a Linux server in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## When an install is finished

**A machine with the harness installed must appear in the Claude app under Remote Control.**
That is how you reach it: open the Claude app, pick the machine under Remote Control, and work
in a session that runs on that machine, with its files, its credentials and its browser. A
cloud session runs on Anthropic's infrastructure and has none of those.

An install that does not end with the machine listed there is not finished.

## Order

Each step depends on the one before, and several fail silently when taken out of order. The
costly one is leaving Remote Control running from before a later step: **the server keeps the
configuration it started with**, so anything changed afterwards needs a restart of the service.

Commands below are the shape of the tools; each script's `--help` is authoritative.

## 1. Account login

Sign the standalone CLI in with `claude auth login` and check it with `claude auth status`,
which prints `loggedIn`, `authMethod`, `email` and `orgName`.

- **Pick the account whose Claude app should list this machine.** An organization account
  brings the organization's managed settings with it. A session can sit indefinitely on an
  unanswered "managed settings require approval" prompt, looking alive and doing nothing. Check
  `orgName` is the one you meant.
- **API keys and `claude setup-token` tokens do not work here.** Remote Control refuses them,
  and Claude Code keeps Chrome off for them even when given `--chrome`. The CLI on every
  machine stays logged in with a claude.ai subscription account. Routine tokens from the pool
  ([[2026-09-15-runbook-brain-routine-auth]]) are for model requests only.
- **On a Mac the CLI may not be logged in at all**, even on a machine where you use Claude Code
  every day. The desktop app keeps its own credentials and hands them to the sessions it
  starts, so `claude auth status` can say `loggedIn: false`. A launchd job inherits none of
  that; the CLI needs its own login.

None of `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or
`DISABLE_GROWTHBOOK` may be set. Each one turns off the feature flag evaluation Remote Control
depends on.

## 2. A non-root user

Run everything as a normal user with passwordless sudo, never as root. Claude Code refuses to
skip permission prompts under root, which blocks the mode that makes driving a machine from a
phone bearable. [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]]

## 3. Dependencies

`git`, `python3` 3.9 or newer with SQLite FTS5, `keepassxc-cli`, `ripgrep`, and Claude Code
from its official installer (`curl -fsSL https://claude.ai/install.sh | bash`), which puts the
CLI at `~/.local/bin/claude`.

The installer does **not** add `~/.local/bin` to `PATH`; it only prints the line to add. Put it
in the shell profile, or the binary is simply not found and nothing says why. On Debian or
Ubuntu, `apt-get install --no-install-recommends keepassxc ripgrep` covers the rest.

## 4. Vault access through a per-machine deploy key

Generate an ed25519 key **on the new machine**, so the private half never travels, and add the
public half to the vault repository as a deploy key **with write access** (the machine syncs
and pushes the vault):

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "<machine label> vault"
gh repo deploy-key add ~/.ssh/id_ed25519.pub --repo <owner>/<vault repo> --title "<machine label>" --allow-write
git clone git@github.com:<owner>/<vault repo>.git ~/Brain
```

Run the `gh` command from a machine that already has `gh` authenticated, or paste the key in
the repository's settings page.

A deploy key reaches that one repository and nothing else. The machine can sync the vault and
still fail to clone, commit or open a pull request anywhere else. Giving it a real GitHub
identity is a separate procedure:
[[2026-09-21-runbook-github-cli-and-git-identity-on-a-linux-machine]].

## 5. Credentials

Credentials live in the local KeePass database
([[2026-08-20-decision-credentials-in-keepass]]). The new machine needs that `.kdbx`, and the
keyfile if the database uses one:

- If your machines already share a synced folder (the first run's `multi_machine` step), keep
  the `.kdbx` there and point `kp.py init --db PATH` (or `BRAIN_KP_DB`) at it. Otherwise copy
  the file.
- Copy a keyfile over SSH, never through a chat, a note or git, and give it mode 600.
- The master password is typed only where `kp.py` asks for it, outside any conversation.

Check with `python3 ~/Brain/_bin/kp.py status`, then prove it by reading one real entry and
comparing a hash of the value (never the value) with the same entry read on another machine.

## 6. The harness

```sh
bash ~/Brain/bootstrap.sh                       # index and health; installs nothing into agents
bash ~/Brain/integrations/first-run/setup.sh    # the first run, one yes at a time
bash ~/Brain/integrations/claude-code/install.sh
```

The first run is where the kdbx path, the files directory, the shared directory and the
scheduled jobs are chosen. Re-running it resumes where it stopped.

## 7. Periodic jobs

macOS gets the launchd jobs from `_bin/com.secondbrain.*.plist`. Linux gets the systemd user
units from `_bin/systemd/second-brain-*.service` and `.timer`, installed under
`~/.config/systemd/user`. The first run installs them when you accept, and the guardian keeps
them in step with the templates ([[2026-09-15-runbook-brain-guardian]]).

- **Start each job by hand once and check it succeeded.** Enabled is not the same as working.
- On a Linux server nobody logs into, systemd user units stop with the last login session
  unless lingering is on: `loginctl enable-linger <user>`.
- **A machine runs no scheduled task until a row names it.** The registry in
  `90-Meta/scheduled-tasks.md` is shared and every row is pinned to a machine (its label or
  `*`), so a new machine runs nothing, silently, until you add or move rows to it. Check with
  `tasks.py --list`. Before moving a row, see step 10.

## 8. Remote Control server

A long-lived server, supervised: `_bin/com.secondbrain.remote-control.plist` on macOS
(`RunAtLoad` and `KeepAlive`, no `StartInterval`), `_bin/systemd/second-brain-remote-control.service`
on Linux (`Restart=always`, and no timer). The first run offers it like the other jobs. **Not
tmux or a shell left open**: the server gives up and exits after roughly ten minutes without
network, and only a supervisor brings it back.

```sh
claude remote-control --chrome --name <machine label>
```

Two flags decide whether it works at all:

- **`--chrome` is required.** The `claudeInChromeDefaultEnabled` setting does not cover server
  mode. Without the flag every session the server hands out has no browser tools and says,
  misleadingly, that it runs in a cloud container. An older CLI rejects the flag with
  `Unknown argument: --chrome`; `claude update` fixes it.
- **`--spawn worktree` must not be used.** This repo registers a `WorktreeCreate` hook
  (`seed_worktree.py`) that prepares a worktree, while Claude Code expects that hook to create
  one and return its path. With both in play every session dies at birth and the app hangs on
  "Connecting…".

The working directory is a **small dedicated git repository** (see the label section below),
never the home directory, whose workspace trust has been accepted once, interactively. Trust is
never saved for the home directory, and without it the server exits with
`Workspace not trusted`.

Run the server once by hand in that directory before handing it to the supervisor. The first
start asks two questions a supervised job cannot answer: `Enable Remote Control? (y/n)`, then a
spawn mode, `same-dir` or `worktree`. **Choose same-dir**; worktree is the mode that breaks
against the hook above. Both answers persist, so they are given once.

Restart the service after any configuration change.

## 9. Browser

Each machine drives its own Chrome with the Claude extension
([[2026-09-21-reference-where-claude-in-chrome-is-available]]). On macOS that is the Chrome you
already use. On a Linux server it needs a desktop that is always on, because sessions and
routines use the browser when nobody is logged in.

**Install.** `xfce4`, `tigervnc-standalone-server` and `google-chrome-stable`, plus `xdotool`
and `xclip`. `~/.vnc/xstartup`:

```sh
#!/bin/sh
unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS
exec dbus-launch --exit-with-session startxfce4
```

Generate the VNC password and file it in the kdbx. Listen on localhost only and reach the
desktop through an SSH tunnel, never an open port.

**The desktop as a system unit**, enabled at boot, `/etc/systemd/system/vnc-desktop.service`:

```ini
[Unit]
Description=VNC desktop for the harness user (localhost only)
After=network.target

[Service]
Type=forking
User=<user>
Group=<user>
Environment=HOME=/home/<user>
ExecStartPre=-/usr/bin/vncserver -kill :1
ExecStart=/usr/bin/vncserver :1 -localhost yes -geometry 1600x1000 -depth 24 -SecurityTypes VncAuth
ExecStop=/usr/bin/vncserver -kill :1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`sudo systemctl daemon-reload && sudo systemctl enable --now vnc-desktop`. A desktop that only
exists while someone has it open is not there for routines.

**Chrome kept alive.** A loop in `~/.local/bin/chrome-keepalive.sh` reopens Chrome if it
crashes or is closed, started by the desktop's autostart
(`~/.config/autostart/google-chrome.desktop` with `Exec=` pointing at the script):

```sh
#!/bin/sh
while true; do
  /usr/bin/google-chrome --no-first-run --no-default-browser-check >>"$HOME/.cache/chrome-keepalive.log" 2>&1
  sleep 5
done
```

**Extension and sign-ins, once, by hand through VNC.** Install the Claude in Chrome extension,
sign it in with the machine's Claude account, and sign in to the sites your routines need; the
profile keeps the sessions. Pair with `claude --chrome` and check that `/chrome` shows the
extension installed and enabled. Then restart the Remote Control service (step 8).

**Check.** `systemctl is-enabled vnc-desktop` says `enabled`, `pgrep -a chrome` shows Chrome,
and from a session `list_connected_browsers` lists a browser with `osPlatform: Linux` and
`isLocal: true`.

The VNC keyboard layout is usually `us`, so symbols are not where a Mac keyboard puts them;
`xdotool type` enters what the layout cannot.

## 10. Scheduled-task preflight

Before pinning a scheduled task to the machine or enabling it there, its repos, programs and
paths must exist on this machine. Run the preflight on the machine, let `--fix` clone the repos
that declare a URL, install what is left, and repeat until every line passes:

```sh
python3 ~/Brain/_bin/routine_requires.py --fix
```

Logins (sites in this machine's Chrome, OAuth for MCP servers) cannot be checked by a script;
check them by hand. [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]

## 11. Verify, then verify from the phone

On the machine: `claude auth status`; `kp.py status` plus one real read; `tasks.py --list`;
`systemctl --user list-timers` (or `launchctl list | grep secondbrain`) for every periodic job;
and the Remote Control log showing `Connected · <name>`.

Then open the Claude app on the phone, choose **Remote Control** and the machine, start a
session with **+**, and ask something only that machine can answer (a file in its home, its
hostname). A session under the machine's name that hangs on "Connecting…" means the server is
refusing it. Read the server log; the app will not tell you why.

## Traps in the app

**Cloud sessions look like machine sessions and are not.** They run on Anthropic's
infrastructure. One that has cloned the vault repository even shows vault context, which makes
it convincing. The environment picker separates them: Local, Cloud, Remote Control, SSH.

**A session's own account of where it runs is unreliable.** Sessions served by a machine have
described themselves as running in a cloud container while reading that machine's files. Trust
the server log and the environment picker, not the session.

## The label under Remote Control

**The name a machine shows comes from the git repository of the server's working directory,
not from `--name`.** With a remote, it is the repository's name; with no remote, the
directory's name. A server pointed at the vault shows the vault repository's name, the same on
every machine. `--name` still titles the sessions inside the group.

So give each machine a small dedicated repository named the way the machine should appear
(`~/laptop`, `~/server`), created with `git init` and nothing else in it, and serve from there.
The machine's identity in the harness is a separate thing
([[2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label]]).

## Keys in ~/.claude.json

Remote Control keeps its answers in `~/.claude.json`:

- per project, keyed by the absolute path under `projects`: `hasTrustDialogAccepted` and
  `remoteControlSpawnMode`;
- global: `hasUsedRemoteControl` (gates the `Enable Remote Control?` prompt),
  `remoteDialogSeen` and a machine id for Remote Control.

Moving the working directory to a new path loses both per-project keys. Copy the entry to the
new path and neither prompt comes back. Without the trust key the server exits with
`Workspace not trusted`, naming the old directory, which is confusing. A machine that keeps
asking whether to enable Remote Control is missing `hasUsedRemoteControl`.

**Do not edit `~/.claude.json` while a Claude Code session is live on the same machine.** The
session rewrites the file too, and one write clobbers the other; that is how an acceptance that
was really given goes missing. Stop the session and the server, edit, then start them again.

## Several machines on several accounts

The Claude account a machine is signed into decides one thing: **which account's Claude app
lists the machine under Remote Control.** Nothing else, and there is nothing to configure; it
follows from `claude auth login` on that machine.

It does not decide what the machine can see. The vault travels over git with a per-machine
deploy key, which belongs to the repository. Secrets travel as a kdbx file and its keyfile on
the machine. Neither is a Claude credential. Two machines on two different Claude accounts read
the same notes and the same secrets, and switching a machine's account changes where its
sessions appear and nothing else. This is the same independence the machinery is built on:
[[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]].

- A work machine can run the harness under a work account without that account gaining access
  to anything, and without losing the shared vault. It will carry the work organization's
  managed settings and policy, so check `orgName` when something behaves oddly.
- `_bin/machines.py` records each machine and the Claude account it is signed into, so the
  inventory answers "how many machines, and under which account each".

Prove the three properties separately on a new machine rather than assuming they came
together:

1. `claude auth status`: the right account, therefore the right app.
2. `git -C ~/Brain pull` and one real `kp.py` read: the shared context, whatever the answer to 1.
3. The machine listed under Remote Control in that account's app, and a session there
   answering something only that machine knows.

## Links

- [[2026-09-21-decision-supported-environments-macos-and-linux]]
- [[2026-09-21-decision-machine-identity-is-a-stable-id-plus-a-human-label]]
- [[2026-09-21-convention-machines-default-to-bypass-permissions-with-a-non-root-user]]
- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
- [[2026-09-21-reference-where-claude-in-chrome-is-available]]
- [[2026-09-21-runbook-github-cli-and-git-identity-on-a-linux-machine]]
- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-15-decision-brain-machinery-independent-of-claude-app-and-account]]
