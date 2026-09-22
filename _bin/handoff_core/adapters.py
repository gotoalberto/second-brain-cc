"""handoff.py's adapters: openssl, a tar payload in memory, the local filesystem, this machine's own
configuration files and kp.py init.

Each class implements one port from ports.py. Everything that touches the machine is here.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time

from . import domain as D

BIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BIN not in sys.path:
    sys.path.insert(0, BIN)

import brain_files  # noqa: E402
import brain_paths  # noqa: E402
import brain_shared  # noqa: E402

KP = os.path.join(BIN, "kp.py")
_ACCOUNT = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def _expand(value, home):
    value = str(value or "").strip()
    if value == "~" or value.startswith("~/"):
        return home + value[1:]
    return value


# ---------------------------------------------------------------- openssl


class OpensslCipher:
    """`openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt`, over stdin and stdout. The passphrase
    reaches the child only through its environment (`-pass env:SBH_PASS`), never argv, and the
    plaintext never touches the disk."""

    def __init__(self, openssl=None, run=subprocess.run, environ=None, which=shutil.which):
        self.openssl = openssl or which("openssl")
        self.run, self.environ = run, environ

    def available(self):
        return bool(self.openssl)

    def _enc(self, extra, data, passphrase):
        if not self.openssl:
            raise D.HandoffError("openssl is not installed or not on PATH")
        env = dict(os.environ if self.environ is None else self.environ)
        env[D.PASS_ENV] = passphrase
        argv = [self.openssl, "enc"] + extra + list(D.OPENSSL_ENC) + ["-pass", "env:" + D.PASS_ENV]
        p = self.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if p.returncode != 0:
            why = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            raise D.HandoffError("openssl %s failed: %s" % ("decryption" if "-d" in extra else "encryption",
                                                             (why[0] if why else "exit %d" % p.returncode)[:200]))
        return p.stdout

    def encrypt(self, plaintext, passphrase):
        return self._enc([], plaintext, passphrase)

    def decrypt(self, ciphertext, passphrase):
        return self._enc(["-d"], ciphertext, passphrase)


# ---------------------------------------------------------------- the payload


class TarArchive:
    """A plain tar in memory. unpack reads members without extracting anything: the caller checks
    names and types by hand (domain.member_problem), so no tarfile extraction filter is needed."""

    def pack(self, members):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o600, 0
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def unpack(self, data):
        out = []
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
                for info in tf.getmembers():
                    if info.issym():
                        kind = "symlink"
                    elif info.islnk():
                        kind = "hardlink"
                    elif info.isdir():
                        kind = "dir"
                    elif info.isreg():
                        kind = "file"
                    else:
                        kind = "other"
                    blob = b""
                    if kind == "file":
                        fh = tf.extractfile(info)
                        blob = fh.read() if fh is not None else b""
                    out.append((D.Member(info.name, kind), blob))
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise D.HandoffError("the decrypted payload is not a valid archive (%s)" % type(exc).__name__)
        return out


# ---------------------------------------------------------------- files


class LocalFiles:
    def exists(self, path):
        return os.path.lexists(path)

    def is_private(self, path):
        return not (os.stat(path).st_mode & 0o077)

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def write_private(self, path, data, overwrite):
        """Mode 600, atomic. os.replace swaps a symlink for the file, it never writes through it."""
        if os.path.lexists(path) and not overwrite:
            raise D.HandoffError("%s already exists; pass --force to overwrite" % path)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, mode=0o700, exist_ok=True)
        tmp = "%s.handoff-tmp.%d" % (path, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def make_private_dir(self, path):
        os.makedirs(path, mode=0o700, exist_ok=True)

    def listdir(self, path):
        try:
            names = os.listdir(path)
        except OSError:
            return []
        out = []
        for name in names:
            try:
                out.append((name, float(os.lstat(os.path.join(path, name)).st_mtime)))
            except OSError:
                continue
        return out

    def remove(self, path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- this machine


def kp_config_path(environ=None, home=None):
    """<state>/kp-config.json, the state kp.py itself uses (BRAIN_KP_STATE wins, as in kp.py)."""
    environ = os.environ if environ is None else environ
    state = (environ.get("BRAIN_KP_STATE") or "").strip() or brain_paths.effective_state_dir(environ, home)
    return os.path.join(state, "kp-config.json")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class LocalMachine:
    def __init__(self, environ=None, home=None):
        self.environ = os.environ if environ is None else environ
        self.home = home or os.path.expanduser("~")
        self.state = brain_paths.effective_state_dir(self.environ, self.home)

    def describe(self):
        """What kp.py would use here: BRAIN_KP_DB and BRAIN_KP_KEYFILE, then <state>/kp-config.json."""
        env, home = self.environ, self.home
        cfg = _load_json(kp_config_path(env, home))
        db = _expand(env.get("BRAIN_KP_DB") or cfg.get("db"), home)
        keyfile = _expand(env.get("BRAIN_KP_KEYFILE") or cfg.get("keyfile"), home)
        group = str(env.get("BRAIN_KP_GROUP") or cfg.get("group") or "")
        registry = _load_json(os.path.join(brain_paths.state_dir(env, home), "google-accounts.json"))
        accounts = registry.get("accounts") if isinstance(registry.get("accounts"), dict) else {}
        return D.Source(db=db, keyfile=keyfile, group=group,
                        shared_dir=brain_shared.shared_dir(env, home),
                        files_dir=brain_files.files_dir(env, home),
                        google_accounts=sorted(n for n in accounts if _ACCOUNT.match(n)),
                        home=home)

    def local_shared(self):
        return brain_shared.shared_dir(self.environ, self.home)


# ---------------------------------------------------------------- kp.py init


class KpInitRunner:
    """`kp.py init --db PATH [--keyfile PATH] [--group NAME]`, never interactive (no --create). A kp.py
    whose init has no --keyfile yet gets the same config written the way kp.py writes it."""

    def __init__(self, kp=KP, python=None, run=subprocess.run, config_path=None, environ=None):
        self.kp, self.python, self.run = kp, python or sys.executable, run
        self.environ = os.environ if environ is None else environ
        self.config_path = config_path or kp_config_path(self.environ)

    def init(self, db, keyfile, group):
        argv = [self.python, self.kp] + D.kp_init_args(db, keyfile, group)
        env = dict(self.environ, BRAIN_KP_NOPROMPT="1")
        try:
            p = self.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=env, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, "kp.py init could not run: %s" % exc
        if p.returncode == 0:
            return True, (p.stdout or "").strip()
        if not D.kp_lacks_keyfile_flag(p.returncode, p.stderr):
            return False, ((p.stderr or p.stdout or "").strip().splitlines() or ["exit %d" % p.returncode])[-1]
        wanted = D.merged_kp_config(_load_json(self.config_path), db, keyfile, group)
        folder = os.path.dirname(self.config_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.config_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(wanted, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.config_path)
        return True, "recorded   : %s -> %s" % (db, self.config_path)


# ---------------------------------------------------------------- clock and randomness


class SystemClock:
    def now(self):
        return time.time()


class SystemRandom:
    def passphrase(self):
        return secrets.token_urlsafe(24)

    def new_id(self):
        return secrets.token_hex(16)


def build_ports(environ=None):
    from .application import Ports

    environ = os.environ if environ is None else environ
    return Ports(cipher=OpensslCipher(environ=environ), archive=TarArchive(), files=LocalFiles(),
                 machine=LocalMachine(environ), kp=KpInitRunner(environ=environ), clock=SystemClock(),
                 rand=SystemRandom())
