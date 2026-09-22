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
keyfile if the database uses one. The normal way to get them there is the one-time handoff
([[2026-09-22-decision-one-time-handoff-for-new-machine-credentials]]):

```sh
python3 ~/Brain/_bin/handoff.py issue                # on a machine that already works
python3 ~/Brain/_bin/handoff.py redeem '<TOKEN>'     # on the new machine, from any directory
```

`issue` encrypts the keyfile and a few non-secret settings and prints one token with the exact
redeem command. With a shared directory configured (the first run's `multi_machine` step) the
payload goes through `<shared>/handoff/` and is deleted when redeemed; without one the token
carries it. `--to PATH` writes it to a USB stick or any synced folder instead, and `--with-db`
adds the `.kdbx` when it is not already in a synced folder. `redeem` writes the files mode 600,
records them with `kp.py init`, and prints what is left.

- The token is as sensitive as the keyfile. Paste it once, into the new machine's terminal,
  never into a chat, a note, a ticket or git. It expires after 20 minutes; issue a new one
  rather than keeping an old one.
- If the machines already share a synced folder, keep the `.kdbx` there; `redeem` finds it and
  points `kp.py init` at it.
- The alternative, when there is SSH between the machines: copy the keyfile (and the `.kdbx`)
  with `scp`, `chmod 600` it, and run `kp.py init --db PATH --keyfile PATH` yourself.
- The master password is typed only where `kp.py` asks for it, outside any conversation. The
  handoff never carries or asks for it.

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
  unless lingering is on. The first run's `remote_control` step turns it on (step 8); by hand,
  `sudo loginctl enable-linger $USER`.
- **A machine runs no scheduled task until a row names it.** The registry in
  `90-Meta/scheduled-tasks.md` is shared and every row is pinned to a machine: `*` for every
  machine, or one machine's label (its short hostname), its key or a key it had before a rename.
  `python3 ~/Brain/_bin/machine_identity.py` prints this machine's key. A new machine runs
  nothing, silently, until you add or move rows to it. Check with `tasks.py --list`. Before
  moving a row, see step 10.
- **The machine registers itself.** The first run ends by adding this machine to the machine
  registry, and the guardian's scheduled repair refreshes the entry once a day
  (`machines.py register --daily`). `python3 ~/Brain/_bin/machines.py` lists every machine with
  this one starred.

## 8. Remote Control server

The first run's `remote_control` step sets it up. It needs launchd or systemd user units: on a
machine with only cron the step is declined, because cron cannot supervise a long-lived server.
Once you say yes, the step:

1. Checks the machine: not root; the `claude` CLI found and logged in with a claude.ai account;
   a CLI that knows `remote-control --chrome` (asked of the parser, see below); none of the four
   switches from step 1 in the `env` block of `~/.claude/settings.json`. No Chrome, or a shell
   wrapper standing in for `claude`, is only a warning.
2. Asks the name the sessions carry, proposing the machine's label (the short hostname, from
   `machine_identity.machine_label()`) in lower case.
3. Asks for the working directory, proposing the home directory. Any other folder is created
   with `git init` if it is missing; the vault is refused.
4. Offers to start the server once on your terminal, for the one-time prompts below.
5. Records the directory and the name in `<brain state>/remote-control.json`.
6. On Linux, turns lingering on (`loginctl enable-linger`) so the unit runs with nobody logged
   in, and says so if that is refused.
7. Installs the supervisor from its template: `_bin/com.secondbrain.remote-control.plist` on
   macOS (`RunAtLoad` and `KeepAlive`, no `StartInterval`) or
   `_bin/systemd/second-brain-remote-control.service` on Linux (`Restart=always`, and no timer).
   The guardian keeps it installed like every other job.

Both templates run `_bin/remote_control.py serve`, which finds the CLI (on `PATH`, then
`~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, preferring the real CLI over a wrapper) and
starts, from the recorded directory:

```sh
claude remote-control --chrome --name <name>
```

`python3 ~/Brain/_bin/remote_control.py show` prints the recorded directory and name, the
command and anything in the way. **Not tmux or a shell left open**: the server gives up and
exits after roughly ten minutes without network, and only a supervisor brings it back.

Two flags decide whether it works at all, and `serve` gets both right:

- **`--chrome`, always.** The `claudeInChromeDefaultEnabled` setting does not cover server
  mode. Without the flag every session the server hands out has no browser tools and says,
  misleadingly, that it runs in a cloud container. **Do not look for the flag in
  `remote-control --help`**: the help text can hide it while the flag works, and a check that
  greps the help drops it silently. Run it and read the error instead; only
  `Unknown argument: --chrome` means an older CLI, and `claude update` fixes it.
- **`--spawn worktree` must not be used.** This repo registers a `WorktreeCreate` hook
  (`seed_worktree.py`) that prepares a worktree, while Claude Code expects that hook to create
  one and return its path. With both in play every session dies at birth and the app hangs on
  "Connecting…".

**The working directory is the home directory**, on macOS and Linux alike, so a session started
from the app opens where you would open a terminal, not inside whichever folder happened to be
chosen on install day. A dedicated folder or repository still works if you prefer one; the vault
does not. The home directory is not a git repository, and that is fine **as long as the spawn
mode stays `same-dir`**: only `--spawn worktree` needs a repository, and it is never used.

The trust dialog still has to be accepted once for that directory, interactively, or the server
exits with `Workspace not trusted`. Trust is saved per directory, and the home directory is no
exception: `~/.claude.json` records it as `projects["$HOME"].hasTrustDialogAccepted`.

The first start asks three things a supervised job cannot answer: whether to trust the
workspace, `Enable Remote Control? (y/n)`, then a spawn mode, `same-dir` or `worktree`.
**Choose same-dir**; worktree is the mode that breaks against the hook above. The answers
persist, so they are given once. That is what step 4 of the first run is for; when it says
Connected, stop it with Ctrl+C and the supervisor takes over. By hand, any time:
`cd <dir> && claude remote-control --chrome --name <name>`.

**Install Claude Code with the native installer, not Homebrew.** The Homebrew cask can lag
several releases behind the latest CLI, and an old CLI is exactly what rejects `--chrome`. Use
`curl -fsSL https://claude.ai/install.sh | bash`, which installs to `~/.local/bin/claude`, first
on the supervisors' `PATH`. If you keep a wrapper script named `claude` for your own shell (to
add a flag, say), it must end in `"$@"`, or every flag the caller passes, `--chrome` included,
vanishes silently:

```sh
exec "$HOME/.local/bin/claude" --your-flag "$@"
```

`remote_control.py` prefers the real CLI over such a wrapper and warns when a wrapper is all it
finds.

**Restart the service after any change** (the login, the CLI, Chrome pairing, this
configuration): `systemctl --user restart second-brain-remote-control` on Linux,
`launchctl kickstart -k gui/$(id -u)/com.secondbrain.remote-control` on macOS. The server keeps
the flags and configuration it started with, so an edit does nothing until the restart.

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
`isLocal: true`. Pairing is not the end: step 9a is what gives sessions the browser.

The VNC keyboard layout is usually `us`, so symbols are not where a Mac keyboard puts them;
`xdotool type` enters what the layout cannot.

## 9a. Chrome in sessions, on macOS and Linux

Browser tools are attached **only when the CLI process starts with `--chrome`**. A session that
started without it cannot acquire them mid-flight. So every entry point passes the flag:

| Entry point | How it gets `--chrome` |
|---|---|
| Remote Control (the Claude app, phone, claude.ai/code) | `remote_control.py serve` always passes it |
| Terminal, by hand | `claude --chrome` |
| Routine, subprocess, `claude -p` | the caller passes it; routines that allow `mcp__claude-in-chrome` do, on the CLI login |

**Verify, in this order:**

```sh
# 1. the server runs with the flag
ps -eo command | grep "[r]emote-control"
#    want: .../claude remote-control --chrome --name <name>

# 2. in a NEW session opened from the Claude app, the tools are listed
#    mcp__claude-in-chrome__* present (deferred counts)

# 3. and they answer
#    list_connected_browsers returns the browsers
```

Only step 3 proves it; steps 1 and 2 can look right while the extension is unreachable. The
session start `## This machine` block reports step 1 for you, and whether Chrome runs.

**Restart after any change** (step 8): the server inherits its flags from the moment it started.

Prerequisites that matter: Chrome paired and running on this machine (step 9), a claude.ai
login (`claude auth login`, a direct plan). Chrome is refused to API keys and
`claude setup-token` tokens even with `--chrome`. Things that are **not** the mechanism, so do
not spend time on them: the `claudeInChromeDefaultEnabled` setting, the CLI version by itself
(beyond knowing the flag), and a permissions-bypass wrapper that passes `"$@"`. Details:
[[2026-09-21-reference-where-claude-in-chrome-is-available]].

## 10. Scheduled-task preflight

Before pinning a scheduled task to the machine or enabling it there, its repos, programs and
paths must exist on this machine. Run the preflight on the machine, let `--fix` clone the repos
that declare a URL, install what is left, and repeat until every line passes:

```sh
python3 ~/Brain/_bin/routine_requires.py here --fix                      # every enabled agent task this machine runs
python3 ~/Brain/_bin/routine_requires.py check 90-Meta/routines/<id>.md  # one routine, before its row names this machine
```

Either exits 2 while anything is missing.

Logins (sites in this machine's Chrome, OAuth for MCP servers) cannot be checked by a script;
check them by hand. [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]

## 11. Verify, then verify from the phone

On the machine: `claude auth status`; `kp.py status` plus one real read; `tasks.py --list`;
`machines.py` listing this machine; `systemctl --user list-timers` (or
`launchctl list | grep secondbrain`) for every periodic job; and the Remote Control log showing
`Connected · <name>` (`journalctl --user -u second-brain-remote-control` on Linux,
`~/Library/Application Support/brain/logs/remote-control.log` on macOS).

Then check that the harness is really wired into Claude Code, because a machine can sync and
register itself while nothing reaches its sessions (step 6 run from the wrong directory fails
with `can't open file '.../_bin/...'` and installs nothing):

- `~/.claude/settings.json` carries the Brain hooks: `grep -c '_bin/compass.py' ~/.claude/settings.json`
  is not 0.
- `~/.claude/skills` and `~/.claude/agents` are not empty.
- A new session starts with the Brain context block. No block means no hooks, whatever else
  looks fine.
- The machine listed by `machines.py` proves only that it registered, not that sessions get
  the harness.

If any of these fails, run step 6 again, with the absolute paths as written.

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

**The label a machine's sessions are grouped under in the app is the server's environment.**
The server is assigned it when it registers, and you rename it from the app; no CLI flag,
configuration key or environment variable sets it. `--name` titles the sessions inside the
group. The working directory does not name the machine, so the home directory serves as well
as any dedicated folder.
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
  inventory answers "how many machines, and under which account each". Every machine registers
  itself (step 7); the registry lives on the shared path when one is configured, else in this
  machine's state, never in the vault.

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
