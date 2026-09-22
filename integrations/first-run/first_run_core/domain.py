"""The first run's rules. Pure: no IO, no clock, no platform calls.

The first run asks, one step at a time, whether to connect each optional piece, and where to keep
files (the one step that cannot be declined). Every answer is kept in <brain state>/first-run.json,
so running it again resumes where it stopped and never asks an answered question twice:

  steps       {step: {"status": "done" | "declined", "at": ISO time, ...details}}
  scheduler   {"kind": "launchd" | "systemd" | "cron" | "none", "jobs": [accepted job names]}

The remote_control step's own entry ({"kind", "dir", "name"}) is what tells the guardian to keep the
Remote Control server installed too; it is not one of the scheduler's periodic jobs.

A step that failed, or that waits on a step not done yet, is not recorded: the next run asks it
again. Declining a step also declines the steps that cannot work without it. The guardian reads
`scheduler` and installs or reloads only those jobs.
"""

from __future__ import annotations

import copy
import json
import os
import re

STEPS = ("kdbx", "google", "files", "multi_machine", "alert_email", "mcp", "scheduler", "remote_control", "routines")
# Steps that cannot be declined: Brain does not work without them. They are asked until they are done.
REQUIRED = ("files",)
ANSWERS = ("done", "declined")
# A step that cannot work without another one: declined with it, left unasked while it is not done.
DEPENDS = {"google": "kdbx", "routines": "kdbx"}

JOBS = (
    ("guardian", "every 15 min: keep hooks, git hooks and jobs wired, and alert on problems"),
    ("sync", "every 10 min: commit and push the vault"),
    ("tasks", "every 10 min: run the periodic tasks in 90-Meta/scheduled-tasks.md"),
    ("watch", "every minute: fire file events (reindex, link repair, sync debounce)"),
)
SCHEDULERS = ("launchd", "systemd", "cron")
# The Remote Control server is a long-lived process, not a periodic job: only a supervisor that restarts it
# can keep it (launchd KeepAlive, systemd Restart=always). It has its own step, not a row in JOBS.
SUPERVISORS = ("launchd", "systemd")
REMOTE_CONTROL_JOB = "remote-control"

_EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")


def new_state() -> dict:
    return {"version": 1, "steps": {}, "scheduler": {"kind": "none", "jobs": []}}


def parse_state(text: str) -> dict:
    try:
        data = json.loads(text) if (text or "").strip() else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("steps"), dict):
        return new_state()
    state = new_state()
    state["steps"] = {k: v for k, v in data["steps"].items() if k in STEPS and isinstance(v, dict)
                      and v.get("status") in ANSWERS and not (k in REQUIRED and v.get("status") == "declined")}
    sched = data.get("scheduler")
    if isinstance(sched, dict):
        state["scheduler"] = {"kind": sched.get("kind") if sched.get("kind") in SCHEDULERS else "none",
                              "jobs": [j for j in (sched.get("jobs") or []) if j in dict(JOBS)]}
    return state


def render_state(state: dict) -> str:
    return json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def record(state: dict, step: str, status: str, details: dict, now) -> dict:
    if step not in STEPS:
        raise ValueError("unknown step %r" % step)
    if status not in ANSWERS:
        raise ValueError("a step is either done or declined, not %r" % status)
    if status == "declined" and step in REQUIRED:
        raise ValueError("%s cannot be declined" % step)
    out = copy.deepcopy(state)
    entry = {"status": status, "at": now.isoformat(timespec="seconds")}
    entry.update(details or {})
    out["steps"][step] = entry
    return out


def forget(state: dict, step: str) -> dict:
    """Ask a step again next time, with every step that depends on it."""
    out = copy.deepcopy(state)
    for s in [step] + [d for d, parent in DEPENDS.items() if parent == step]:
        out["steps"].pop(s, None)
    if step == "scheduler":
        out["scheduler"] = {"kind": "none", "jobs": []}
    return out


def next_step(state: dict):
    return next((s for s in STEPS if s not in state["steps"]), None)


def is_complete(state: dict) -> bool:
    return next_step(state) is None


def status_exit(state: dict) -> int:
    """`first_run.py status`: 0 when every step has an answer, 3 when the first run still has questions."""
    return 0 if is_complete(state) else 3


def parse_yes_no(text, default: bool):
    t = (text or "").strip().lower()
    if not t:
        return default
    if t in ("y", "yes"):
        return True
    if t in ("n", "no"):
        return False
    return None


def valid_email(address) -> bool:
    return bool(_EMAIL.fullmatch(address or ""))


def default_kdbx_path(platform: str, home: str) -> str:
    if platform == "darwin":
        return os.path.join(home, "Documents", "brain.kdbx")
    return os.path.join(home, ".local", "share", "brain", "brain.kdbx")


def detect_scheduler(platform: str, which, environ) -> str:
    """launchd on macOS; systemd user units on Linux when there is a user session to run them; cron where
    systemd is absent; "none" when there is nothing to schedule with."""
    if platform == "darwin":
        return "launchd"
    if which("systemctl") and (environ.get("XDG_RUNTIME_DIR") or environ.get("DBUS_SESSION_BUS_ADDRESS")):
        return "systemd"
    if which("crontab"):
        return "cron"
    return "none"


def job_label(kind: str, job: str) -> str:
    """The same labels guardian_core.adapters.job_label gives the job templates in _bin."""
    return ("com.secondbrain.%s" % job) if kind == "launchd" else ("second-brain-%s" % job)


def scheduler_state(kind: str, jobs) -> dict:
    return {"kind": kind, "jobs": list(jobs)}


def mcp_snippets(vault: str, python: str = "python3") -> dict:
    """How to register the vault's MCP server with common agents. Printed for the user, never written
    into another program's config by the first run."""
    server = os.path.join(vault, "integrations", "mcp", "server.py")
    return {
        "claude-code": "claude mcp add brain -- %s %s" % (python, server),
        "claude-desktop": json.dumps({"mcpServers": {"brain": {"command": python, "args": [server]}}}, indent=2),
        "json-clients": json.dumps({"mcpServers": {"brain": {"command": python, "args": [server],
                                                             "env": {"BRAIN_VAULT": vault}}}}, indent=2),
        "opencode": json.dumps({"$schema": "https://opencode.ai/config.json",
                                "mcp": {"brain": {"type": "local", "command": [python, server], "enabled": True,
                                                  "environment": {"BRAIN_VAULT": vault}}}}, indent=2),
    }


def profile_line(vault: str) -> str:
    return 'export BRAIN_VAULT="%s"' % vault.replace("\\", "\\\\").replace('"', '\\"')


def token_ref(n: int) -> str:
    return "kp://apis/agent-routines-token-%d" % n


def token_label(n: int) -> str:
    return "routines-%d" % n


# ---------------------------------------------------------------- Remote Control


def valid_label(name) -> bool:
    """The name the server passes as --name, and the folder name when a dedicated one is chosen."""
    return bool(_LABEL.fullmatch(name or "")) and ".." not in name


def default_remote_dir(home: str, label: str, vault: str) -> str:
    """The home directory: a session started from the app then opens where you would open a terminal. It needs
    no git repository, because spawn mode stays same-dir, and its workspace trust is kept like any directory's.
    Never the vault (compared case-insensitively, as macOS disks are); if the home somehow is the vault, a
    folder named like the machine instead."""
    if os.path.normpath(home).casefold() == os.path.normpath(vault).casefold():
        return os.path.join(home, label)
    return home


def auth_problems(text: str) -> list:
    """What in `claude auth status` stops Remote Control. It takes only a CLI logged in with a claude.ai account:
    API keys and `claude setup-token` tokens are refused, and Chrome stays off with them even under --chrome."""
    try:
        data = json.loads(text or "")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return ["`claude auth status` gave no answer that could be read; update the CLI (claude update) "
                "and log in with `claude auth login`"]
    if data.get("loggedIn") is not True:
        return ["the claude CLI is not logged in: run `claude auth login` with a claude.ai account"]
    method = data.get("authMethod")
    if method and method != "claude.ai":
        return ["the claude CLI is logged in through %s: Remote Control needs a claude.ai account "
                "(`claude auth login`); API keys and setup-token tokens do not work" % method]
    return []


def first_start_text(path: str, label: str) -> str:
    """The prompts the server asks once, interactively, before a supervisor can run it unattended."""
    return "\n".join([
        "  The first start asks three things, once; the answers are kept for this directory:",
        "    1. whether to trust the workspace %s: yes" % path,
        "    2. Enable Remote Control? (y/n): y",
        "    3. the spawn mode, [1] same-dir or [2] worktree: choose same-dir. A worktree spawn mode",
        "       conflicts with Brain's WorktreeCreate hook, and every session would hang on Connecting.",
        "  When it says Connected, stop it with Ctrl+C: the supervisor takes over from there.",
        "  By hand, any time: cd %s && claude remote-control --chrome --name %s" % (path, label),
    ])


def verify_text(label: str, kind: str) -> str:
    """How to see the server is up, and how to prove it from the phone."""
    if kind == "systemd":
        log = "systemctl --user status %s; journalctl --user -u %s" % ((job_label(kind, REMOTE_CONTROL_JOB),) * 2)
    else:
        log = ("launchctl list %s; the log, ~/Library/Application Support/brain/logs/remote-control.log,"
               % job_label(kind, REMOTE_CONTROL_JOB))
    return "\n".join([
        "  Check it: %s should show it Connected." % log,
        "  Then from the phone: open the Claude app, choose Remote Control and %s, start a session with +," % label,
        "  and ask it something only this machine could answer.",
    ])
