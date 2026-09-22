"""The rules behind handoff.py, the one-time handoff of a new machine's credentials. Pure: no IO,
no clock, no randomness.

What travels is a small tar payload: the keyfile the local KeePass database uses (if any), the
`.kdbx` itself only when asked, and settings.json, a handful of non-secret settings the new machine
needs (where the database was recorded, the shared and files directories, the KeePass group, the
names of the Google accounts). Never the master password, never a refresh token: those live in the
database, or in the human's head.

The payload is encrypted by `openssl enc` with a random one-time passphrase, and a MAC over the
ciphertext, keyed from the same passphrase, is checked before anything is decrypted. The token the
human pastes on the new machine carries the passphrase, the MAC and either the ciphertext itself
(inline) or the id of a file written into a shared or named directory, deleted when redeemed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import posixpath
import re
from dataclasses import dataclass, field
from typing import List, Optional

TOKEN_PREFIX = "sbh1."
TRANSPORTS = ("shared", "path", "inline")
FILE_TRANSPORTS = ("shared", "path")
DEFAULT_TTL_MIN = 20
MAX_TTL_MIN = 60
SWEEP_AGE_S = 60 * 60                 # every issue deletes handoff files older than this
INLINE_MAX = 64 * 1024                # ciphertext bytes an inline token may carry
HANDOFF_SUBDIR = "handoff"
PASS_ENV = "SBH_PASS"                 # the variable openssl reads the passphrase from
OPENSSL_ENC = ("-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt")

SETTINGS = "settings.json"
KEYFILE = "keyfile"
DATABASE = "database.kdbx"
ALL_MEMBERS = (SETTINGS, KEYFILE, DATABASE)

_ID = re.compile(r"^[0-9a-f]{32}$")
_FILE = re.compile(r"^handoff-([0-9a-f]{32})\.enc$")
_MAC_CONTEXT = b"second-brain handoff v1 mac key"


class HandoffError(Exception):
    """Something handoff.py cannot do, said in one line: exit 1."""


class UsageError(HandoffError):
    """The command was asked wrongly: exit 2."""


# ---------------------------------------------------------------- the token


@dataclass
class Token:
    transport: str
    id: str
    passphrase: str
    issued_at: int
    ttl: int
    mac: str
    directory: Optional[str] = None       # file transports: where the issuer wrote the file
    ciphertext: Optional[bytes] = None    # inline: the payload itself


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    if not re.match(r"^[A-Za-z0-9_-]*$", text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encode_token(t: Token) -> str:
    """`sbh1.<base64url(JSON)>`, and for inline a third segment with the ciphertext, so the
    payload is base64-encoded once rather than twice. Still one string to copy."""
    body = {"v": 1, "t": t.transport, "id": t.id, "p": t.passphrase, "iat": int(t.issued_at),
            "ttl": int(t.ttl), "mac": t.mac}
    if t.directory:
        body["d"] = t.directory
    out = TOKEN_PREFIX + b64e(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if t.transport == "inline":
        out += "." + b64e(t.ciphertext or b"")
    return out


def decode_token(text: str) -> Token:
    bad = HandoffError("that does not look like a handoff token (a character may have been lost in the "
                       "copy); ask for a new one with `handoff.py issue`")
    text = (text or "").strip()
    if not text.startswith(TOKEN_PREFIX):
        raise bad
    parts = text[len(TOKEN_PREFIX):].split(".")
    if len(parts) not in (1, 2) or not parts[0]:
        raise bad
    try:
        body = json.loads(b64d(parts[0]).decode("utf-8"))
        ciphertext = b64d(parts[1]) if len(parts) == 2 else None
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise bad
    if not isinstance(body, dict) or body.get("v") != 1:
        raise bad
    transport, tid, passphrase, mac_hex = body.get("t"), body.get("id"), body.get("p"), body.get("mac")
    iat, ttl, directory = body.get("iat"), body.get("ttl"), body.get("d")
    if transport not in TRANSPORTS:
        raise HandoffError("unknown handoff transport %r" % (transport,))
    if not isinstance(tid, str) or not valid_id(tid):
        raise bad
    if not isinstance(passphrase, str) or len(passphrase) < 16 or not isinstance(mac_hex, str):
        raise bad
    if not isinstance(iat, int) or not isinstance(ttl, int) or ttl <= 0:
        raise bad
    if directory is not None and not isinstance(directory, str):
        raise bad
    if transport == "inline" and not ciphertext:
        raise bad
    if transport != "inline" and ciphertext is not None:
        raise bad
    return Token(transport, tid, passphrase, iat, ttl, mac_hex, directory, ciphertext)


def valid_id(value) -> bool:
    return bool(_ID.match(value or ""))


def handoff_file_name(handoff_id: str) -> str:
    return "handoff-%s.enc" % handoff_id


# ---------------------------------------------------------------- the MAC


def mac_key(passphrase: str) -> bytes:
    """A key for the MAC, derived from the passphrase, so the passphrase itself keys nothing twice.
    The passphrase is 24 random bytes, so one HMAC step is enough; no stretching is needed."""
    return hmac.new(passphrase.encode("utf-8"), _MAC_CONTEXT, hashlib.sha256).digest()


def mac(passphrase: str, ciphertext: bytes) -> str:
    return hmac.new(mac_key(passphrase), ciphertext, hashlib.sha256).hexdigest()


def mac_ok(passphrase: str, ciphertext: bytes, expected: str) -> bool:
    return hmac.compare_digest(mac(passphrase, ciphertext), (expected or "").lower()) if len(expected or "") == 64 \
        else False


# ---------------------------------------------------------------- time


def ttl_seconds(minutes) -> int:
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_TTL_MIN:
        raise UsageError("--ttl-min must be a whole number of minutes between 1 and %d" % MAX_TTL_MIN)
    return minutes * 60


def expiry_problem(transport: str, issued_at: int, ttl: int, now: float, ignore_expiry: bool):
    """None when the token may be redeemed now, else the reason, in one line."""
    age = max(0.0, now - issued_at)
    if age <= ttl:
        return None
    if not ignore_expiry:
        return ("this token expired %d minutes after it was issued; issue a new one on the machine that "
                "works (`handoff.py issue`)" % (ttl // 60))
    if transport in FILE_TRANSPORTS and age > SWEEP_AGE_S:
        return ("this token is more than an hour old, and a handoff file that old is never redeemed, even "
                "with --ignore-expiry; issue a new one")
    return None


# ---------------------------------------------------------------- transport


def choose_transport(requested: Optional[str], shared_dir: Optional[str]):
    """(transport, directory) from --to and the configured shared dir."""
    if requested in (None, ""):
        return ("shared", posixpath.join(shared_dir, HANDOFF_SUBDIR)) if shared_dir else ("inline", None)
    if requested == "inline":
        return "inline", None
    if requested == "shared":
        if not shared_dir:
            raise UsageError("--to shared needs a shared directory (BRAIN_SHARED_DIR, or the first run's "
                             "multi_machine step); use --to inline or --to PATH")
        return "shared", posixpath.join(shared_dir, HANDOFF_SUBDIR)
    if not requested.startswith("/"):
        raise UsageError("--to takes shared, inline or an absolute directory path, not %r" % requested)
    return "path", requested


def inline_problem(size: int):
    if size <= INLINE_MAX:
        return None
    return ("the encrypted payload is %d KiB, too big to paste as one token (limit %d KiB); write it to a "
            "USB stick or a synced folder with --to PATH" % ((size + 1023) // 1024, INLINE_MAX // 1024))


def to_sweep(entries, now: float, max_age: float = SWEEP_AGE_S) -> list:
    """Names among (name, mtime) pairs that are handoff files older than max_age. Nothing else."""
    return sorted(name for name, mtime in entries if _FILE.match(name) and now - mtime > max_age)


# ---------------------------------------------------------------- the payload


@dataclass
class Source:
    """What the issuing machine knows about its own credential setup."""
    db: str = ""
    keyfile: str = ""
    group: str = ""
    shared_dir: Optional[str] = None
    files_dir: Optional[str] = None
    google_accounts: List[str] = field(default_factory=list)
    home: str = ""


def relative_under(path: str, root: Optional[str]):
    """path relative to root when it is strictly inside it, else None. Plain string logic."""
    if not path or not root:
        return None
    path, root = posixpath.normpath(path), posixpath.normpath(root)
    if not path.startswith(root.rstrip("/") + "/"):
        return None
    return path[len(root.rstrip("/")) + 1:]


def settings_for(src: Source, with_db: bool) -> dict:
    """settings.json: non-secret settings the new machine needs to find its way."""
    return {
        "version": 1,
        "db": src.db or None,
        "db_name": posixpath.basename(src.db) if src.db else None,
        "db_shared_rel": relative_under(src.db, src.shared_dir),
        "db_home_rel": relative_under(src.db, src.home),
        "db_carried": bool(with_db),
        "keyfile_name": posixpath.basename(src.keyfile) if src.keyfile else None,
        "keyfile_home_rel": relative_under(src.keyfile, src.home),
        "kp_group": src.group or None,
        "shared_dir": src.shared_dir or None,
        "files_dir": src.files_dir or None,
        "google_accounts": sorted(src.google_accounts or []),
    }


def expected_members(settings: dict) -> list:
    names = [SETTINGS]
    if settings.get("keyfile_name"):
        names.append(KEYFILE)
    if settings.get("db_carried"):
        names.append(DATABASE)
    return sorted(names)


def db_needs_copy(settings: dict) -> bool:
    """True when the new machine will not find the database by itself: not carried, not shared."""
    return bool(settings.get("db")) and not settings.get("db_carried") and not settings.get("db_shared_rel")


def parse_settings(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HandoffError("the payload's settings do not parse")
    if not isinstance(data, dict) or data.get("version") != 1:
        raise HandoffError("the payload's settings are not a version this handoff.py understands")
    return data


@dataclass
class Member:
    name: str
    kind: str              # file, dir, symlink, hardlink, other


def member_problem(members, expected) -> Optional[str]:
    """None when the archive holds exactly the expected flat regular files, else what is wrong.
    Done by hand, so no tarfile extraction filter (Python 3.12 and later) is needed."""
    seen = []
    for m in members:
        name = m.name
        if name.startswith("/") or "\\" in name:
            return "the payload holds an absolute path (%r)" % name
        if ".." in name.split("/"):
            return "the payload holds a path with .. (%r)" % name
        if "/" in name or name in ("", "."):
            return "the payload holds a nested path (%r)" % name
        if m.kind != "file":
            return "the payload holds a %s, not a regular file (%r)" % (m.kind, name)
        if name not in expected:
            return "the payload holds an unexpected member (%r)" % name
        if name in seen:
            return "the payload holds %r twice" % name
        seen.append(name)
    if SETTINGS not in expected or sorted(seen) != sorted(expected):
        return "the payload does not hold exactly %s (it holds %s)" % (", ".join(sorted(expected)),
                                                                      ", ".join(sorted(seen)) or "nothing")
    return None


# ---------------------------------------------------------------- redeem


def _safe_name(name) -> str:
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in (".", ".."):
        raise HandoffError("the payload names a file with a path in it (%r)" % (name,))
    return name


def _safe_rel(rel):
    if rel is None:
        return None
    if not isinstance(rel, str) or rel.startswith("/") or ".." in rel.split("/"):
        raise HandoffError("the payload records a location outside the home directory (%r)" % (rel,))
    return rel


def redeem_targets(settings: dict, home: str, state: str) -> dict:
    """Where each carried file lands: the same place under this home when it lived under the issuer's
    home, else this machine's state directory. {member: absolute path}."""
    out = {}
    if settings.get("keyfile_name"):
        name, rel = _safe_name(settings["keyfile_name"]), _safe_rel(settings.get("keyfile_home_rel"))
        out[KEYFILE] = posixpath.join(home, rel) if rel else posixpath.join(state, name)
    if settings.get("db_carried"):
        name, rel = _safe_name(settings.get("db_name")), _safe_rel(settings.get("db_home_rel"))
        out[DATABASE] = posixpath.join(home, rel) if rel else posixpath.join(state, name)
    return out


def db_candidates(settings: dict, home: str, local_shared: Optional[str]) -> list:
    """Where a database that was not carried may already be on this machine, most likely first:
    under this machine's shared dir (else the issuer's, often mounted at the same path), the same
    place under this home, then the path exactly as the issuer recorded it."""
    out = []
    shared_rel, home_rel = _safe_rel(settings.get("db_shared_rel")), _safe_rel(settings.get("db_home_rel"))
    shared = local_shared or settings.get("shared_dir")
    if shared and shared_rel:
        out.append(posixpath.join(shared, shared_rel))
    if home_rel:
        out.append(posixpath.join(home, home_rel))
    if settings.get("db"):
        out.append(settings["db"])
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen


def kp_init_args(db: str, keyfile: Optional[str], group: Optional[str] = None) -> list:
    args = ["init", "--db", db]
    if keyfile:
        args += ["--keyfile", keyfile]
    if group:
        args += ["--group", group]
    return args


def kp_lacks_keyfile_flag(returncode: int, stderr: str) -> bool:
    """An older kp.py whose init has no --keyfile answers with argparse's usage error."""
    return returncode == 2 and "unrecognized arguments" in (stderr or "") and "--keyfile" in (stderr or "")


def merged_kp_config(current: dict, db: str, keyfile: Optional[str], group: Optional[str]) -> dict:
    """What `kp.py init --db --keyfile` records, for the fallback that writes the config itself."""
    out = dict(current or {}, db=db)
    if keyfile:
        out["keyfile"] = keyfile
    if group and not out.get("group"):
        out["group"] = group
    return out
