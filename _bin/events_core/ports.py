"""What the event layer's use cases need from the world.

Imports nothing from guardian_core on purpose: the event layer and the guardian are
separate hexagons that meet only in adapters (the alert sink writes into the guardian's
raised-alerts file), so either can change its internals without the other noticing.
"""

from __future__ import annotations

from typing import Protocol


class Snapshot(Protocol):
    def read(self, paths: list) -> dict: ...          # {relative path: mtime} under the listed paths


class WatchState(Protocol):
    def load(self) -> dict: ...                        # {"snapshot", "memory", "last_tick", ...}
    def save(self, data: dict) -> None: ...


class ProcessRunner(Protocol):
    def run(self, argv: list, timeout: int) -> tuple: ...  # (rc, stdout, stderr); argv, never a shell string


class SessionIdSource(Protocol):
    def resolve(self) -> str: ...                      # a session id, or "system" when there is none


class AlertSink(Protocol):
    def raise_alert(self, key: str, summary: str, severity: str = "warn") -> None: ...
    def clear_alert(self, key: str) -> None: ...


class GitProbe(Protocol):
    def oldest_unsynced_mtime(self): ...               # epoch seconds of the oldest unsynced change, or None


class FileStore(Protocol):
    def read(self, rel: str): ...                      # text, or None when missing
    def write(self, rel: str, text: str, executable: bool = False) -> None: ...


class Clock(Protocol):
    def now(self) -> float: ...                        # epoch seconds


class SettingsHooks(Protocol):
    def hooks(self): ...                               # an agent's live hooks block (dict); None when the agent is
                                                       # absent or its config unreadable. Read-only.


class LogTail(Protocol):
    def read_new(self) -> tuple: ...                   # (whole lines appended since the last read, fresh: first read)


class HookLiveness(Protocol):
    def findings(self, now: float) -> list: ...        # [(key, severity, summary)]: are Brain's hooks firing?
                                                       # The cheap verdict: no probe, no silent window.
