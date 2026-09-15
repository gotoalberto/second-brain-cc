"""What google.py's use cases need from the world, and nothing about how it is done.

application.py talks only to these. adapters.py implements them against KeePass (kp.py), urllib,
JSON files and a loopback HTTP server; the tests implement them in memory.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from .domain import GoogleError, Unavailable  # noqa: F401  (re-exported for adapters and callers)


class HttpError(Exception):
    """Google answered with an HTTP error. `body` is its reply, for the caller to show verbatim."""

    def __init__(self, status: int, body: str = ""):
        super().__init__("HTTP %d: %s" % (status, (body or "")[:200]))
        self.status, self.body = status, body or ""


class SecretStore(Protocol):
    def read(self, entry: str, attr: str = "Password", timeout: int = 20) -> str: ...  # raises Unavailable
    def write(self, entry: str, value: str, username=None, notes=None) -> None: ...     # raises GoogleError


class Http(Protocol):
    def post_form(self, url: str, fields: dict, timeout: int = 20) -> dict: ...          # raises HttpError, Unavailable
    def request(self, method: str, url: str, token: str, body=None, timeout: int = 30) -> dict: ...


class AccountStore(Protocol):
    def load(self) -> dict: ...                       # {name: domain.Account}
    def save(self, accounts: dict) -> None: ...


class ConsentReceiver(Protocol):
    def wait(self, port: int, url: str, state: str, timeout: int) -> dict: ...  # the callback's query parameters


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, html: bool = False): ...   # the message id, or None; raises


class SendLog(Protocol):
    def append(self, record: dict) -> None: ...


class Clock(Protocol):
    def now(self) -> dt.datetime: ...
