#!/usr/bin/env python3
"""Tests for handoff_core.application: issue and redeem, on in-memory ports.

The cipher is a reversible fake (so the tests do not need openssl), the archive keeps members in a
list, the filesystem is a dict with modes and mtimes, kp.py is a recorder. Run standalone:

    python3 _bin/handoff_core/application_test.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as exc:
        return None, exc


class FakeCipher:
    """XOR with the passphrase, plus a marker, so a wrong passphrase is detected like openssl's bad decrypt."""

    def __init__(self, available=True):
        self._available, self.calls = available, []

    def available(self):
        return self._available

    def _xor(self, data, passphrase):
        key = passphrase.encode()
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def encrypt(self, plaintext, passphrase):
        self.calls.append("encrypt")
        return b"FAKE" + self._xor(b"OK" + plaintext, passphrase)

    def decrypt(self, ciphertext, passphrase):
        self.calls.append("decrypt")
        plain = self._xor(ciphertext[4:], passphrase)
        if not plain.startswith(b"OK"):
            raise D.HandoffError("bad decrypt")
        return plain[2:]


class FakeArchive:
    def __init__(self, override=None):
        self.override = override

    def pack(self, members):
        return json.dumps([[n, d.decode("latin-1")] for n, d in members]).encode()

    def unpack(self, data):
        if self.override is not None:
            return self.override
        return [(D.Member(n, "file"), d.encode("latin-1")) for n, d in json.loads(data.decode())]


class FakeFiles:
    def __init__(self, files=None, now=10000.0):
        self.files = {}          # path -> [data, mode, mtime]
        self.dirs, self.removed, self.now = set(), [], now
        for path, spec in (files or {}).items():
            data, mode = spec if isinstance(spec, tuple) else (spec, 0o600)
            self.files[path] = [data, mode, now]

    def exists(self, path):
        return path in self.files

    def is_private(self, path):
        return not (self.files[path][1] & 0o077)

    def read(self, path):
        return self.files[path][0]

    def write_private(self, path, data, overwrite):
        if path in self.files and not overwrite:
            raise D.HandoffError("exists: %s" % path)
        self.files[path] = [data, 0o600, self.now]

    def make_private_dir(self, path):
        self.dirs.add(path)

    def listdir(self, path):
        pre = path.rstrip("/") + "/"
        return [(p[len(pre):], v[2]) for p, v in self.files.items() if p.startswith(pre) and "/" not in p[len(pre):]]

    def remove(self, path):
        self.removed.append(path)
        del self.files[path]


class FakeMachine:
    def __init__(self, source=None, local_shared=None, home="/home/b", state="/state/b"):
        self.source, self._shared, self.home, self.state = source, local_shared, home, state

    def describe(self):
        return self.source

    def local_shared(self):
        return self._shared


class FakeKp:
    def __init__(self, result=(True, "recorded")):
        self.calls, self.result = [], result

    def init(self, db, keyfile, group):
        self.calls.append((db, keyfile, group))
        return self.result


class Clock:
    def __init__(self, t=10000.0):
        self.t = t

    def now(self):
        return self.t


class Rand:
    def passphrase(self):
        return "one-time-passphrase-0123456789"

    def new_id(self):
        return "ab" * 16


SOURCE = None


def source(**over):
    kw = dict(db="/home/a/Sync/brain.kdbx", keyfile="/home/a/.config/brain/brain.key", group="Brain",
              shared_dir="/home/a/Sync", files_dir="/home/a/BrainFiles", google_accounts=["personal"], home="/home/a")
    kw.update(over)
    return D.Source(**kw)


def issuer(src=None, files=None, cipher=None, clock=None):
    fs = FakeFiles(files if files is not None else {"/home/a/.config/brain/brain.key": b"KEYFILE-BYTES",
                                                     "/home/a/Sync/brain.kdbx": b"KDBX-BYTES"})
    return A.Ports(cipher=cipher or FakeCipher(), archive=FakeArchive(), files=fs,
                   machine=FakeMachine(src or source(), home="/home/a", state="/state/a"), kp=FakeKp(),
                   clock=clock or Clock(), rand=Rand())


def redeemer(issued_files=None, local_shared=None, clock=None, kp=None, extra=None, archive=None):
    fs = FakeFiles()
    for path, v in (issued_files or {}).items():
        if "/handoff/" in path or path.startswith("/media/"):
            fs.files[path] = list(v)
    for path, data in (extra or {}).items():
        fs.files[path] = [data, 0o600, 0]
    return A.Ports(cipher=FakeCipher(), archive=archive or FakeArchive(), files=fs,
                   machine=FakeMachine(None, local_shared=local_shared), kp=kp or FakeKp(),
                   clock=clock or Clock(10060.0), rand=Rand())


def test_issue_shared():
    print("\n== issue through the shared directory ==")
    p = issuer()
    res = A.issue(p)
    path = "/home/a/Sync/handoff/handoff-%s.enc" % ("ab" * 16)
    check("with a shared dir the payload goes to <shared>/handoff/handoff-<id>.enc", res.transport == "shared"
          and res.location == path and path in p.files.files, (res, list(p.files.files)))
    check("the file is written private", p.files.files[path][1] == 0o600)
    check("the handoff directory is created private", "/home/a/Sync/handoff" in p.files.dirs)
    t = D.decode_token(res.token)
    check("the token carries id, passphrase, time, ttl, MAC and the directory, not the ciphertext",
          t.id == "ab" * 16 and t.passphrase == Rand().passphrase() and t.issued_at == 10000 and t.ttl == 1200
          and t.directory == "/home/a/Sync/handoff" and t.ciphertext is None
          and D.mac_ok(t.passphrase, p.files.files[path][0], t.mac), t)
    check("the database under the shared dir is not flagged for copying", not res.notes, res.notes)
    check("the plaintext never lands on disk", not any(b"KEYFILE-BYTES" in v[0] for k, v in p.files.files.items()
                                                       if k.startswith("/home/a/Sync/handoff")))


def test_issue_refusals():
    print("\n== issue refuses what it should ==")
    _, exc = outcome(A.issue, issuer(cipher=FakeCipher(available=False)))
    check("no openssl: a clear refusal", isinstance(exc, D.HandoffError) and "openssl" in str(exc), exc)
    _, exc = outcome(A.issue, issuer(files={"/home/a/.config/brain/brain.key": (b"K", 0o644)}))
    check("a keyfile readable by others is refused with the chmod to fix it",
          isinstance(exc, D.HandoffError) and "chmod 600" in str(exc), exc)
    _, exc = outcome(A.issue, issuer(files={}))
    check("a configured keyfile that is missing is refused", isinstance(exc, D.HandoffError) and "missing" in str(exc), exc)
    _, exc = outcome(A.issue, issuer(src=source(db="", keyfile="")))
    check("nothing configured: refused, pointing at kp.py init", isinstance(exc, D.HandoffError) and "kp.py init" in str(exc),
          exc)
    _, exc = outcome(A.issue, issuer(), to="shared", ttl_min=90)
    check("a ttl over an hour is a usage error", isinstance(exc, D.UsageError), exc)
    big = issuer(files={"/home/a/.config/brain/brain.key": b"K", "/home/a/Sync/brain.kdbx": b"x" * (70 * 1024)})
    _, exc = outcome(A.issue, big, to="inline", with_db=True)
    check("an inline payload over the limit is refused, pointing at --to PATH",
          isinstance(exc, D.HandoffError) and "--to PATH" in str(exc), exc)
    check("and nothing was written", not any("/handoff" in k for k in big.files.files), list(big.files.files))


def test_issue_inline_and_path():
    print("\n== issue inline and to a named path ==")
    p = issuer(src=source(shared_dir=None, db="/home/a/Documents/brain.kdbx"))
    res = A.issue(p)
    t = D.decode_token(res.token)
    check("without a shared dir the default is inline and the token carries the ciphertext",
          res.transport == "inline" and t.ciphertext and res.location is None, res)
    check("a database neither shared nor carried is flagged for copying",
          any("--with-db" in n for n in res.notes), res.notes)
    p = issuer(src=source(shared_dir=None), files={"/home/a/.config/brain/brain.key": b"K",
                                                    "/media/usb/handoff-%s.enc" % ("cd" * 16): b"old"})
    p.files.files["/media/usb/handoff-%s.enc" % ("cd" * 16)][2] = 10000.0 - 3700
    p.files.files["/media/usb/keep.txt"] = [b"mine", 0o644, 0.0]
    res = A.issue(p, to="/media/usb")
    check("--to PATH writes the file there", res.transport == "path"
          and res.location == "/media/usb/handoff-%s.enc" % ("ab" * 16), res)
    check("issue sweeps handoff files older than an hour there, and nothing else",
          p.files.removed == ["/media/usb/handoff-%s.enc" % ("cd" * 16)] and "/media/usb/keep.txt" in p.files.files,
          p.files.removed)


def test_redeem_shared():
    print("\n== redeem from the shared directory ==")
    i = issuer()
    res = A.issue(i)
    r = redeemer(i.files.files, local_shared="/home/a/Sync",
                 extra={"/home/a/Sync/brain.kdbx": b"KDBX-BYTES"})
    out = A.redeem(r, res.token)
    key = "/home/b/.config/brain/brain.key"
    check("the keyfile lands at the same place under this home, mode 600",
          r.files.files.get(key, [None])[0] == b"KEYFILE-BYTES" and r.files.files[key][1] == 0o600, list(r.files.files))
    check("the shared file is deleted after a successful redeem, so it is single use",
          res.location in r.files.removed and res.location not in r.files.files, r.files.removed)
    check("kp.py init is run with the database found under the shared dir and the keyfile",
          r.kp.calls == [("/home/a/Sync/brain.kdbx", key, "Brain")], r.kp.calls)
    check("the result says what was written and what was deleted",
          out.written == {"keyfile": key} and out.deleted == res.location and out.db == "/home/a/Sync/brain.kdbx", out)
    again, exc = outcome(A.redeem, r, res.token)
    check("a second redeem finds nothing: the file is gone",
          isinstance(exc, D.HandoffError) and "already redeemed" in str(exc), exc)


def test_redeem_refusals():
    print("\n== redeem refuses what it should ==")
    i = issuer()
    res = A.issue(i)
    path = res.location
    tampered = dict(i.files.files)
    data = bytearray(tampered[path][0])
    data[-1] ^= 1
    tampered[path] = [bytes(data), 0o600, 0]
    r = redeemer(tampered, local_shared="/home/a/Sync")
    _, exc = outcome(A.redeem, r, res.token)
    check("a tampered payload is refused before anything is decrypted",
          isinstance(exc, D.HandoffError) and "MAC" in str(exc) and "decrypt" not in r.cipher.calls, (exc, r.cipher.calls))
    check("and the tampered file is left alone (it may be evidence)", path in r.files.files)

    r = redeemer(i.files.files, local_shared="/home/a/Sync", clock=Clock(10000.0 + 1201))
    _, exc = outcome(A.redeem, r, res.token)
    check("an expired token is refused", isinstance(exc, D.HandoffError) and "expired" in str(exc), exc)
    r = redeemer(i.files.files, local_shared="/home/a/Sync", clock=Clock(10000.0 + 1800),
                 extra={"/home/a/Sync/brain.kdbx": b"K"})
    out, exc = outcome(A.redeem, r, res.token, ignore_expiry=True)
    check("--ignore-expiry lets a file token through inside the hour", exc is None, exc)
    r = redeemer(i.files.files, local_shared="/home/a/Sync", clock=Clock(10000.0 + 3700))
    _, exc = outcome(A.redeem, r, res.token, ignore_expiry=True)
    check("but not a file token older than an hour", isinstance(exc, D.HandoffError) and "hour" in str(exc), exc)

    key = "/home/b/.config/brain/brain.key"
    r = redeemer(i.files.files, local_shared="/home/a/Sync", extra={key: b"EXISTING"})
    _, exc = outcome(A.redeem, r, res.token)
    check("an existing keyfile is not overwritten without --force",
          isinstance(exc, D.HandoffError) and "--force" in str(exc) and r.files.files[key][0] == b"EXISTING", exc)
    check("and the handoff file stays, so the redeem can be retried with --force", path in r.files.files)
    out, exc = outcome(A.redeem, r, res.token, force=True)
    check("with --force it is overwritten", exc is None and r.files.files[key][0] == b"KEYFILE-BYTES", exc)

    evil = [(D.Member("settings.json", "file"), json.dumps(D.settings_for(source(), False)).encode()),
            (D.Member("keyfile", "symlink"), b"")]
    r = redeemer(i.files.files, local_shared="/home/a/Sync", archive=FakeArchive(evil))
    _, exc = outcome(A.redeem, r, res.token)
    check("a payload with a link in it is refused and nothing is written",
          isinstance(exc, D.HandoffError) and "symlink" in str(exc) and key not in r.files.files, exc)
    evil = [(D.Member("settings.json", "file"), json.dumps(D.settings_for(source(), False)).encode()),
            (D.Member("keyfile", "file"), b"K"), (D.Member("database.kdbx", "file"), b"D")]
    r = redeemer(i.files.files, local_shared="/home/a/Sync", archive=FakeArchive(evil))
    _, exc = outcome(A.redeem, r, res.token)
    check("a member the settings do not announce is refused", isinstance(exc, D.HandoffError), exc)


def test_redeem_inline_with_db():
    print("\n== redeem an inline token that carries the database ==")
    i = issuer(src=source(shared_dir=None, db="/home/a/Documents/brain.kdbx"),
               files={"/home/a/.config/brain/brain.key": b"KEY", "/home/a/Documents/brain.kdbx": b"KDBX"})
    res = A.issue(i, with_db=True)
    r = redeemer()
    out = A.redeem(r, res.token)
    db = "/home/b/Documents/brain.kdbx"
    check("the database lands under this home, mode 600", r.files.files[db][0] == b"KDBX" and r.files.files[db][1] == 0o600)
    check("kp.py init points at it", r.kp.calls == [(db, "/home/b/.config/brain/brain.key", "Brain")], r.kp.calls)
    check("nothing is deleted for an inline token", out.deleted is None and r.files.removed == [])
    check("the non-secret settings come back for the next steps",
          out.settings["files_dir"] == "/home/a/BrainFiles" and out.settings["google_accounts"] == ["personal"])


def test_redeem_without_db():
    print("\n== redeem when the database is not on this machine yet ==")
    i = issuer(src=source(shared_dir=None, db="/home/a/Documents/brain.kdbx"),
               files={"/home/a/.config/brain/brain.key": b"KEY"})
    res = A.issue(i)
    r = redeemer()
    out = A.redeem(r, res.token)
    check("the keyfile is written but kp.py init is not run", "keyfile" in out.written and r.kp.calls == [], r.kp.calls)
    check("the result carries the kp.py init command to run once the database is there",
          out.db is None and out.kp_args == ["init", "--db", "/home/b/Documents/brain.kdbx", "--keyfile",
                                             "/home/b/.config/brain/brain.key", "--group", "Brain"], out.kp_args)
    i = issuer()
    res = A.issue(i)
    r = redeemer(i.files.files, local_shared="/home/a/Sync", kp=FakeKp((False, "kp.py init failed")),
                 extra={"/home/a/Sync/brain.kdbx": b"K"})
    out = A.redeem(r, res.token)
    check("a failing kp.py init is reported, and the delivered file is still deleted",
          out.kp_result == (False, "kp.py init failed") and res.location in r.files.removed, out)


def test_redeem_from_dir():
    print("\n== redeem from a directory the issuer named ==")
    i = issuer(src=source(shared_dir=None), files={"/home/a/.config/brain/brain.key": b"K"})
    res = A.issue(i, to="/media/usb")
    moved = {"/media/stick/" + os.path.basename(res.location): i.files.files[res.location]}
    r = redeemer(moved)
    _, exc = outcome(A.redeem, r, res.token)
    check("a stick mounted elsewhere is not found by itself, and the error says --from",
          isinstance(exc, D.HandoffError) and "--from" in str(exc), exc)
    out, exc = outcome(A.redeem, r, res.token, from_dir="/media/stick")
    check("with --from it is found, redeemed and deleted",
          exc is None and ("/media/stick/" + os.path.basename(res.location)) in r.files.removed, exc)


def main():
    global A, D
    try:
        from handoff_core import application as A
        from handoff_core import domain as D
    except Exception as exc:
        check("handoff_core.application imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_issue_shared, test_issue_refusals, test_issue_inline_and_path, test_redeem_shared,
                  test_redeem_refusals, test_redeem_inline_with_db, test_redeem_without_db, test_redeem_from_dir):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
