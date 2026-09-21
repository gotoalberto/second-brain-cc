"""What the guardian's use cases need from the world, and nothing about how it is done.

application.py talks only to these. adapters.py, claude_code.py, mail_queue.py and
mailer.py implement them against the real machine; the tests implement them in memory.
Swapping how something is done — another agent's event wiring, a different mailer, a
different scheduler — means writing another class with the same methods, never touching
the use cases.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class SettingsUnreadable(Exception):
    """An agent's config file exists but cannot be parsed. Repair must not overwrite it."""


class MailUnavailable(Exception):
    """The mail channel cannot send right now (disabled, no token, no scope, no network).

    The outbox catches it and keeps the message for the next run. It never reaches the
    use cases.
    """


class AgentAdapter(Protocol):
    """One AI agent's wiring into Brain's events (Claude Code's hooks, for instance).

    Brain's events are Brain's; an agent only carries generated wiring that triggers
    them. The adapter compares that wiring with what Brain expects and repairs it, and
    is the only place that knows where and in what shape the agent keeps it.
    """

    def name(self) -> str: ...
    def present(self) -> bool: ...                  # is this agent installed on this machine
    def check(self): ...                             # domain.AgentWiring, read-only
    def repair(self): ...                            # domain.AgentRepair; backs up before writing


class LaunchdControl(Protocol):
    def labels(self) -> list: ...                    # the jobs the vault defines
    def installed(self, label: str) -> bool: ...
    def is_loaded(self, label: str) -> bool: ...
    def last_exit_ok(self, label: str) -> tuple: ...  # (ok, detail)
    def drifted(self, label: str) -> bool: ...        # installed plist differs from the template
    def self_label(self) -> str: ...                  # the job this process runs as, or ""
    def install(self, label: str) -> tuple: ...       # (ok, detail)
    def reinstall(self, label: str) -> tuple: ...     # backup, rewrite, reload; (ok, detail)
    def bootstrap(self, label: str) -> tuple: ...     # (ok, detail)


class Clock(Protocol):
    def now(self) -> dt.datetime: ...


class Notifier(Protocol):
    def notify(self, title: str, message: str) -> None: ...


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...  # raises MailUnavailable


class MailOutbox(Protocol):
    def enqueue(self, to: str, subject: str, body: str) -> None: ...
    def flush(self) -> tuple: ...                    # (sent, kept); never raises MailUnavailable
    def pending(self) -> int: ...
    def oldest_age_s(self): ...                       # float seconds, or None when empty
    def enabled(self) -> bool: ...


class AgentRunner(Protocol):
    def available(self) -> bool: ...
    def run(self, prompt_path: str, timeout: int) -> tuple: ...  # (rc, stdout, stderr)


class VaultProbe(Protocol):
    def sync_status(self): ...                        # domain.SyncStatus
    def index_age_s(self): ...                        # float seconds, or None when missing
    def broken_links(self) -> int: ...


class GitHooksControl(Protocol):
    """Brain's git hooks on the vault repository: core.hooksPath and the hook files' modes.

    Writes that one key, in the main repository's config, and the execute bits of the
    hook files. Never another key, a per-worktree, global or system config.
    """

    def status(self): ...                             # domain.GitHooksStatus; raises when not a repository
    def set_hooks_path(self) -> tuple: ...            # (ok, detail)
    def make_executable(self, name: str) -> tuple: ...  # (ok, detail)


class TokenPoolProbe(Protocol):
    """The routine token pool as routine_auth_core last left it. Read-only.

    Never reads KeePass and never sees a token value: only the pool's references and the
    state file routine runs write.
    """

    def pool(self): ...                               # domain.TokenPool


class DesktopTasksProbe(Protocol):
    """The Claude app's own scheduled tasks. Read-only: the guardian never enables or disables one."""

    def enabled(self) -> list: ...                   # [(task id, account uuid)] enabled, across sessions


class InterpreterProbe(Protocol):
    def python3_health(self) -> list: ...             # [domain.InterpreterStatus], hooks' first


class StateStore(Protocol):
    def load(self) -> dict: ...
    def save(self, data: dict) -> None: ...


class RaisedAlerts(Protocol):
    def load(self) -> dict: ...                       # {key: {"severity", "summary", "at"}}


class RoutineSource(Protocol):
    def host(self) -> str: ...
    def routines(self) -> list: ...                   # rows of 90-Meta/scheduled-tasks.md
    def last_runs(self) -> dict: ...                  # {id: {"last_run_date", "last_exit", ...}}
    def meta(self, row: dict) -> dict: ...            # {"app_task", "needs_bridge"} from the routine file
    # Optional: does a row's `machine` cell name this machine (key, uuid, historical form)?
    # A source without it matches `*` and host() only.
    def is_mine(self, machine: str) -> bool: ...


class HookLivenessSource(Protocol):
    """What shows Brain's hooks fire, gathered with no agent. Read-only, except the epoch file."""

    def sessions(self, since: float) -> list: ...     # [domain.SessionTranscript] written since `since`
    def heartbeats(self, since: float) -> list: ...   # [domain.Heartbeat] recorded since `since`, oldest first
    def events(self) -> list: ...                      # [domain.HookEventSpec] from the event registry
    def epoch(self): ...                               # epoch seconds liveness started, or None
    def start_epoch(self, ts: float) -> float: ...     # record `ts` unless an epoch exists; the epoch in force
    def config(self): ...                              # domain.LivenessConfig


class HookProbe(Protocol):
    """Every canonical Brain hook run the way Claude Code runs it, in a scratch state."""

    def results(self) -> list: ...                    # [(domain.ProbeCase, domain.ProbeResult)], once per process
