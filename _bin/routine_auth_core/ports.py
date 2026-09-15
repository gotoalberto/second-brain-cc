"""What run_routine needs from the world, and nothing about how it is done.

application.py talks only to these. adapters.py implements them against the real machine
(KeePass through kp.py, JSON files, the CLI), the tests implement them in memory.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class TokenUnavailable(Exception):
    """The token could not be read. Never an Anthropic-side failure: `kind` is one of
    domain.KEEPASS_LOCKED or domain.KEEPASS_UNAVAILABLE, and the message never carries a value."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


class PoolSource(Protocol):
    def entries(self) -> list: ...                   # [domain.PoolEntry]; raises domain.PoolConfigError


class TokenSource(Protocol):
    def read(self, kp_ref: str, timeout: int) -> str: ...  # the stored value; raises TokenUnavailable


class StateStore(Protocol):
    def load(self) -> dict: ...                       # {label: {"status", "until", "last_kind", "last_at"}}
    def save(self, data: dict) -> None: ...


class Clock(Protocol):
    def now(self) -> dt.datetime: ...
    def monotonic(self) -> float: ...


class CliHealth(Protocol):
    def check(self): ...                              # domain.CliStatus; asked once per process


class RunOnce(Protocol):
    def run(self, prompt: str, agent_args: list, env: dict, timeout: int) -> tuple: ...  # (rc, stdout, stderr)


class RawLog(Protocol):
    def record(self, routine_id: str, label: str, cls, rc, stdout: str, stderr: str, secrets=(),
               run_id=None) -> None: ...


class ScratchDirs(Protocol):
    def create(self, run_id: str) -> str: ...         # a new private directory for one attempt; raises OSError
    def remove(self, path: str) -> None: ...          # only a directory it created
    def prune(self, now: dt.datetime) -> list: ...    # removes the ones older than domain.SCRATCH_KEEP_DAYS


class RunIds(Protocol):
    def new(self, routine_id: str, now: dt.datetime) -> str: ...  # unique per attempt


class SendLog(Protocol):
    def records(self) -> list: ...                    # every google.py send record, as dicts


class AlertSink(Protocol):
    def raise_alert(self, key: str, summary: str, severity: str = "fail") -> None: ...
    def clear_alert(self, key: str) -> None: ...
