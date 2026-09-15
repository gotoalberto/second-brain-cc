"""What the first run needs from the world, and nothing about how it is done.

application.py talks only to these. adapters.py implements them with the terminal, kp.py,
google.py, the files directory (brain_files.py), the agents' own CLIs and the guardian's scheduler adapters; the tests implement
them in memory. Every method that changes the machine returns (ok, detail) and never raises.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class Prompter(Protocol):
    def interactive(self) -> bool: ...
    def yes_no(self, question: str, default: bool = False) -> bool: ...
    def ask(self, question: str, default: str = "") -> str: ...
    def secret(self, question: str) -> str: ...       # never echoed
    def say(self, text: str) -> None: ...


class StateStore(Protocol):
    def load(self) -> dict: ...
    def save(self, state: dict) -> None: ...


class Kdbx(Protocol):
    def exists(self, path: str) -> bool: ...
    def init(self, path: str, create: bool) -> tuple: ...  # kp.py init --db PATH [--create]
    def unlock(self) -> tuple: ...                         # kp.py unlock: arms the master cache


class Google(Protocol):
    def accounts(self) -> list: ...                        # names already connected
    def add(self, name: str, client_id: str, client_secret: str, login_hint: str) -> tuple: ...
    def authorize(self, name: str) -> tuple: ...


class Files(Protocol):
    def propose_default(self) -> str: ...                  # the directory already configured, or ~/BrainFiles
    def check(self, path: str) -> tuple: ...               # creates it, proves it writable: (ok, absolute path | why)
    def persist(self, path: str) -> tuple: ...             # records it where files.py reads it: (ok, file | why)


class MailConfig(Protocol):
    def save(self, config: dict) -> str: ...               # the path written


class Mcp(Protocol):
    def vault(self) -> str: ...
    def snippets(self) -> dict: ...
    def claude_available(self) -> bool: ...
    def register_claude(self) -> tuple: ...
    def profile_path(self) -> str: ...
    def append_profile(self, line: str) -> tuple: ...      # backs the profile up first, never duplicates


class Scheduler(Protocol):
    def detect(self) -> str: ...                           # launchd | systemd | cron | none
    def preview(self, kind: str, jobs: list) -> str: ...
    def install(self, kind: str, jobs: list) -> list: ...  # [(label, ok, detail)]


class Routines(Protocol):
    def agent_available(self) -> tuple: ...                # (ok, the agent command or why not)
    def add_token(self, label: str, kp_ref: str, issued: str, account: str) -> tuple: ...


class Clock(Protocol):
    def now(self) -> dt.datetime: ...
