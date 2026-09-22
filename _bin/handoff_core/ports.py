"""What handoff.py's use cases need from the world, and nothing about how it is done.

application.py talks only to these. adapters.py implements them with openssl, tarfile, the local
filesystem and kp.py; the tests implement them in memory.
"""

from __future__ import annotations

from typing import Optional, Protocol

from .domain import HandoffError, Source, UsageError  # noqa: F401  (re-exported for adapters and callers)


class Cipher(Protocol):
    def available(self) -> bool: ...
    def encrypt(self, plaintext: bytes, passphrase: str) -> bytes: ...     # raises HandoffError
    def decrypt(self, ciphertext: bytes, passphrase: str) -> bytes: ...    # raises HandoffError


class Archive(Protocol):
    def pack(self, members: list) -> bytes: ...          # [(name, bytes)] -> a tar
    def unpack(self, data: bytes) -> list: ...           # a tar -> [(domain.Member, bytes)], nothing on disk


class Files(Protocol):
    def exists(self, path: str) -> bool: ...
    def is_private(self, path: str) -> bool: ...         # no group or other permission bits
    def read(self, path: str) -> bytes: ...
    def write_private(self, path: str, data: bytes, overwrite: bool) -> None: ...   # mode 600
    def make_private_dir(self, path: str) -> None: ...
    def listdir(self, path: str) -> list: ...            # [(name, mtime)]; [] when missing
    def remove(self, path: str) -> None: ...


class Machine(Protocol):
    home: str
    state: str

    def describe(self) -> Source: ...                    # the issuing side's credential setup
    def local_shared(self) -> Optional[str]: ...         # this machine's shared dir, or None


class KpInit(Protocol):
    def init(self, db: str, keyfile: Optional[str], group: Optional[str]) -> tuple: ...   # (ok, detail)


class Clock(Protocol):
    def now(self) -> float: ...


class Random(Protocol):
    def passphrase(self) -> str: ...
    def new_id(self) -> str: ...
