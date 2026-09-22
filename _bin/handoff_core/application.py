"""handoff.py's use cases: issue a one-time handoff on a machine that works, redeem it on a new one.

Only the ports are touched. What a token is, what the payload may hold, when a token has expired and
where redeemed files land are decided in domain.py.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass, field
from typing import Optional

from . import domain as D

NO_OPENSSL = ("openssl is not installed or not on PATH; install it (it ships with macOS and every Linux "
              "distribution's openssl package) and run this again")


@dataclass
class Ports:
    cipher: object                  # ports.Cipher
    archive: object                 # ports.Archive
    files: object                   # ports.Files
    machine: object                 # ports.Machine
    kp: object                      # ports.KpInit
    clock: object                   # ports.Clock
    rand: object                    # ports.Random


@dataclass
class Issued:
    token: str
    transport: str
    location: Optional[str]         # the file written, for shared and path
    ttl: int
    settings: dict
    swept: int = 0
    notes: list = field(default_factory=list)


@dataclass
class Redeemed:
    written: dict                   # {member: path}
    settings: dict
    db: Optional[str]               # the database kp.py was pointed at, or None when it is not here yet
    kp_args: list                   # the kp.py init arguments, run or to run by hand
    kp_result: Optional[tuple]      # (ok, detail) when kp.py init ran
    deleted: Optional[str]          # the handoff file removed, for shared and path
    local_shared: Optional[str]


# ---------------------------------------------------------------- issue


def _sweep(ports, directory) -> int:
    n = 0
    for name in D.to_sweep(ports.files.listdir(directory), ports.clock.now()):
        ports.files.remove(posixpath.join(directory, name))
        n += 1
    return n


def issue(ports, to=None, with_db=False, ttl_min=D.DEFAULT_TTL_MIN) -> Issued:
    ttl = D.ttl_seconds(ttl_min)
    if not ports.cipher.available():
        raise D.HandoffError(NO_OPENSSL)
    src = ports.machine.describe()
    if not src.db and not src.keyfile:
        raise D.HandoffError("no KeePass database is configured on this machine, so there is nothing to hand off; "
                             "set it up first with kp.py init --db PATH [--keyfile PATH]")
    transport, directory = D.choose_transport(to, src.shared_dir)

    members = []
    if src.keyfile:
        if not ports.files.exists(src.keyfile):
            raise D.HandoffError("the keyfile kp.py is configured with is missing: %s" % src.keyfile)
        if not ports.files.is_private(src.keyfile):
            raise D.HandoffError("%s is readable by others; chmod 600 it before handing it off" % src.keyfile)
        members.append((D.KEYFILE, ports.files.read(src.keyfile)))
    if with_db:
        if not src.db or not ports.files.exists(src.db):
            raise D.HandoffError("--with-db: the database is not here (%s)" % (src.db or "none configured"))
        members.append((D.DATABASE, ports.files.read(src.db)))
    settings = D.settings_for(src, with_db)
    members.append((D.SETTINGS, json.dumps(settings, indent=2, sort_keys=True).encode("utf-8")))

    notes = []
    if D.db_needs_copy(settings):
        notes.append("the database (%s) is not under the shared directory and is not in this handoff: copy it to "
                     "the new machine yourself, or issue again with --with-db" % settings["db"])
    if not src.keyfile:
        notes.append("no keyfile is configured, so the handoff carries only settings%s"
                     % (" and the database" if with_db else ""))

    passphrase, handoff_id = ports.rand.passphrase(), ports.rand.new_id()
    issued_at = int(ports.clock.now())
    ciphertext = ports.cipher.encrypt(ports.archive.pack(members), passphrase)
    mac = D.mac(passphrase, ciphertext)

    swept = 0
    shared_handoff = posixpath.join(src.shared_dir, D.HANDOFF_SUBDIR) if src.shared_dir else None
    if shared_handoff and shared_handoff != directory:
        swept += _sweep(ports, shared_handoff)
    if transport == "inline":
        problem = D.inline_problem(len(ciphertext))
        if problem:
            raise D.HandoffError(problem)
        token = D.Token("inline", handoff_id, passphrase, issued_at, ttl, mac, ciphertext=ciphertext)
        return Issued(D.encode_token(token), transport, None, ttl, settings, swept, notes)

    ports.files.make_private_dir(directory)
    swept += _sweep(ports, directory)
    location = posixpath.join(directory, D.handoff_file_name(handoff_id))
    ports.files.write_private(location, ciphertext, overwrite=False)
    token = D.Token(transport, handoff_id, passphrase, issued_at, ttl, mac, directory=directory)
    return Issued(D.encode_token(token), transport, location, ttl, settings, swept, notes)


# ---------------------------------------------------------------- redeem


def _find_file(ports, token, from_dir):
    name = D.handoff_file_name(token.id)
    dirs = []
    if from_dir:
        dirs.append(from_dir)
    local_shared = ports.machine.local_shared()
    if token.transport == "shared" and local_shared:
        dirs.append(posixpath.join(local_shared, D.HANDOFF_SUBDIR))
    if token.directory:
        dirs.append(token.directory)
    dirs = [d for i, d in enumerate(dirs) if d not in dirs[:i]]
    for d in dirs:
        path = posixpath.join(d, name)
        if ports.files.exists(path):
            return path
    raise D.HandoffError("%s is not in %s: it was already redeemed, swept after an hour, or the folder has not "
                         "synced to this machine yet. If it sits somewhere else (a stick mounted at another "
                         "path), pass --from DIR" % (name, " or ".join(dirs) or "any known directory"))


def redeem(ports, token_text, force=False, ignore_expiry=False, from_dir=None) -> Redeemed:
    token = D.decode_token(token_text)
    problem = D.expiry_problem(token.transport, token.issued_at, token.ttl, ports.clock.now(), ignore_expiry)
    if problem:
        raise D.HandoffError(problem)
    if not ports.cipher.available():
        raise D.HandoffError(NO_OPENSSL)

    path = None
    if token.transport == "inline":
        ciphertext = token.ciphertext
    else:
        path = _find_file(ports, token, from_dir)
        ciphertext = ports.files.read(path)
    if not D.mac_ok(token.passphrase, ciphertext, token.mac):
        raise D.HandoffError("the payload does not match the token's MAC: it was altered, or it belongs to "
                             "another token. Nothing was decrypted; issue a new one")
    plain = ports.cipher.decrypt(ciphertext, token.passphrase)

    entries = ports.archive.unpack(plain)
    members = [m for m, _ in entries]
    names = [m.name for m in members]
    problem = D.member_problem(members, [n for n in D.ALL_MEMBERS if n in names or n == D.SETTINGS])
    if problem:
        raise D.HandoffError(problem)
    data = {m.name: blob for m, blob in entries}
    settings = D.parse_settings(data[D.SETTINGS])
    problem = D.member_problem(members, D.expected_members(settings))
    if problem:
        raise D.HandoffError(problem)

    machine = ports.machine
    targets = D.redeem_targets(settings, machine.home, machine.state)
    existing = sorted(p for p in targets.values() if ports.files.exists(p))
    if existing and not force:
        raise D.HandoffError("%s already exists; pass --force to overwrite (the handoff file is kept until then)"
                             % ", ".join(existing))
    for member, dest in sorted(targets.items()):
        ports.files.write_private(dest, data[member], overwrite=force)
    if path:
        ports.files.remove(path)

    local_shared = machine.local_shared()
    if D.DATABASE in targets:
        db = targets[D.DATABASE]
    else:
        candidates = D.db_candidates(settings, machine.home, local_shared)
        found = [c for c in candidates if ports.files.exists(c)]
        db = found[0] if found else None
    shown_db = db or (D.db_candidates(settings, machine.home, local_shared) or ["PATH"])[0]
    kp_args = D.kp_init_args(shown_db, targets.get(D.KEYFILE), settings.get("kp_group"))
    kp_result = ports.kp.init(db, targets.get(D.KEYFILE), settings.get("kp_group")) if db else None
    return Redeemed(targets, settings, db, kp_args, kp_result, path, local_shared)
