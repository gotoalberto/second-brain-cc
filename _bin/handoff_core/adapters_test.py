#!/usr/bin/env python3
"""Tests for handoff_core.adapters: openssl, the tar payload, the filesystem, the machine's own
configuration and kp.py init.

openssl is a fake runner that records argv and environment (and, when openssl is on PATH, the real
one once). The filesystem is a temporary directory. kp.py is a fake script. Run standalone:

    python3 _bin/handoff_core/adapters_test.py
"""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="handoff-adapters-")
    TMP.append(d)
    return d


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as exc:
        return None, exc


class Done:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class RecordingRunner:
    def __init__(self, result=None):
        self.calls, self.result = [], result or Done(0, b"CIPHERTEXT", b"")

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), dict(kw.get("env") or {}), kw.get("input")))
        return self.result


def test_openssl_argv():
    print("\n== openssl never sees the passphrase in argv ==")
    run = RecordingRunner()
    c = AD.OpensslCipher(openssl="/usr/bin/openssl", run=run, environ={"PATH": "/usr/bin"})
    secret = "s3cret-passphrase-abcdefghijkl"
    c.encrypt(b"plain", secret)
    run.result = Done(0, b"plain", b"")
    c.decrypt(b"CIPHERTEXT", secret)
    argvs = [a for a, _, _ in run.calls]
    check("two openssl runs were made", len(run.calls) == 2, argvs)
    check("the passphrase is in no argv element", all(secret not in " ".join(a) for a in argvs), argvs)
    check("the passphrase reaches openssl through its environment",
          all(env.get(D.PASS_ENV) == secret for _, env, _ in run.calls))
    check("the parent environment does not keep it", D.PASS_ENV not in os.environ)
    check("openssl reads it with -pass env:VAR", all(["-pass", "env:" + D.PASS_ENV] == a[a.index("-pass"):a.index("-pass") + 2]
                                                     for a in argvs))
    check("aes-256-cbc with pbkdf2, 200000 iterations and a salt",
          all(all(x in a for x in ("-aes-256-cbc", "-pbkdf2", "200000", "-salt")) for a in argvs), argvs)
    check("the plaintext travels on stdin, not through a file", run.calls[0][2] == b"plain" and "-in" not in argvs[0])
    check("decrypt passes -d", "-d" in argvs[1] and "-d" not in argvs[0])
    run.result = Done(1, b"", b"bad decrypt")
    _, exc = outcome(c.decrypt, b"x", secret)
    check("an openssl failure is a HandoffError that shows no secret",
          isinstance(exc, D.HandoffError) and secret not in str(exc), exc)
    check("availability follows the binary", not AD.OpensslCipher(openssl=None, which=lambda n: None).available()
          and AD.OpensslCipher(openssl=None, which=lambda n: "/x/openssl").available())


def test_openssl_real():
    print("\n== real openssl, when it is installed ==")
    c = AD.OpensslCipher()
    if not c.available():
        print("  (openssl not on PATH: skipped)")
        return
    ct = c.encrypt(b"hello keyfile", "pass-phrase-0123456789")
    check("the ciphertext is openssl's salted format", ct.startswith(b"Salted__") and b"hello" not in ct)
    check("it decrypts back", c.decrypt(ct, "pass-phrase-0123456789") == b"hello keyfile")
    _, exc = outcome(c.decrypt, ct, "another-pass-phrase-0000")
    check("a wrong passphrase fails", isinstance(exc, D.HandoffError), exc)


def test_archive():
    print("\n== the tar payload ==")
    a = AD.TarArchive()
    blob = a.pack([("settings.json", b"{}"), ("keyfile", b"\x00KEY")])
    got = a.unpack(blob)
    check("members round trip as regular files with their bytes",
          [(m.name, m.kind, d) for m, d in got] == [("settings.json", "file", b"{}"), ("keyfile", "file", b"\x00KEY")], got)

    def tar_with(*infos):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for info, data in infos:
                tf.addfile(info, io.BytesIO(data) if data is not None else None)
        return buf.getvalue()

    link = tarfile.TarInfo("keyfile")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    hard = tarfile.TarInfo("other")
    hard.type, hard.linkname = tarfile.LNKTYPE, "keyfile"
    d = tarfile.TarInfo("dir")
    d.type = tarfile.DIRTYPE
    up = tarfile.TarInfo("../escape")
    up.size = 1
    got = a.unpack(tar_with((link, None), (hard, None), (d, None), (up, b"x")))
    kinds = [(m.name, m.kind) for m, _ in got]
    check("links and directories are reported as such, and nothing is read through them",
          kinds == [("keyfile", "symlink"), ("other", "hardlink"), ("dir", "dir"), ("../escape", "file")]
          and all(data == b"" for m, data in got if m.kind != "file"), kinds)
    check("so the domain check refuses them",
          D.member_problem([m for m, _ in got], ["keyfile", "settings.json"]) is not None)
    _, exc = outcome(a.unpack, b"not a tar at all" * 10)
    check("garbage is a HandoffError", isinstance(exc, D.HandoffError), exc)
    check("unpacking writes nothing to disk (no extract call)", "extract(" not in open(AD.__file__).read())


def test_files():
    print("\n== the filesystem ==")
    root = tmpdir()
    f = AD.LocalFiles()
    target = os.path.join(root, "a", "b", "key")
    f.write_private(target, b"K", overwrite=False)
    check("a written file is mode 600", stat.S_IMODE(os.stat(target).st_mode) == 0o600)
    check("a created parent is mode 700", stat.S_IMODE(os.stat(os.path.dirname(target)).st_mode) == 0o700)
    _, exc = outcome(f.write_private, target, b"X", overwrite=False)
    check("it refuses to overwrite without the flag", isinstance(exc, D.HandoffError) and open(target, "rb").read() == b"K",
          exc)
    f.write_private(target, b"X", overwrite=True)
    check("with it, it overwrites and stays 600", open(target, "rb").read() == b"X"
          and stat.S_IMODE(os.stat(target).st_mode) == 0o600)
    other = os.path.join(root, "victim")
    open(other, "wb").write(b"V")
    link = os.path.join(root, "link")
    os.symlink(other, link)
    check("a symlink counts as existing", f.exists(link))
    f.write_private(link, b"NEW", overwrite=True)
    check("overwriting a symlink replaces the link, never writes through it",
          open(other, "rb").read() == b"V" and not os.path.islink(link))
    os.chmod(other, 0o644)
    check("a 644 file is not private, a 600 one is", not f.is_private(other) and f.is_private(target))
    f.make_private_dir(os.path.join(root, "handoff"))
    check("the handoff dir is 700", stat.S_IMODE(os.stat(os.path.join(root, "handoff")).st_mode) == 0o700)
    names = [n for n, _ in f.listdir(root)]
    check("listdir gives names and times", "victim" in names and all(isinstance(t, float) for _, t in f.listdir(root)))
    check("listdir of a missing dir is empty", f.listdir(os.path.join(root, "nope")) == [])
    f.remove(other)
    f.remove(other)
    check("remove is idempotent", not os.path.exists(other))


def test_machine():
    print("\n== what this machine knows about its credentials ==")
    home, state = tmpdir(), tmpdir()
    env = {"HOME": home, "BRAIN_STATE": state}
    with open(os.path.join(state, "kp-config.json"), "w") as fh:
        json.dump({"db": "~/Sync/brain.kdbx", "keyfile": os.path.join(home, "k.key"), "group": "Agents"}, fh)
    with open(os.path.join(state, "shared-dir.json"), "w") as fh:
        json.dump({"dir": "~/Sync"}, fh)
    with open(os.path.join(state, "files-dir.json"), "w") as fh:
        json.dump({"dir": "~/BrainFiles"}, fh)
    with open(os.path.join(state, "google-accounts.json"), "w") as fh:
        json.dump({"accounts": {"work": {"login_hint": "", "scopes": [], "port": 8766},
                                "personal": {"login_hint": "", "scopes": [], "port": 8767}}}, fh)
    m = AD.LocalMachine(environ=env, home=home)
    s = m.describe()
    check("the database comes from the kp config, ~ expanded", s.db == os.path.join(home, "Sync", "brain.kdbx"), s)
    check("the keyfile and group come from it too", s.keyfile == os.path.join(home, "k.key") and s.group == "Agents", s)
    check("the shared and files dirs come from their own configs",
          s.shared_dir == os.path.join(home, "Sync") and s.files_dir == os.path.join(home, "BrainFiles"), s)
    check("the Google account names are read, never anything else", sorted(s.google_accounts) == ["personal", "work"], s)
    m = AD.LocalMachine(environ=dict(env, BRAIN_KP_DB="/elsewhere/x.kdbx", BRAIN_KP_KEYFILE="/k2"), home=home)
    check("BRAIN_KP_DB and BRAIN_KP_KEYFILE win, as they do in kp.py",
          m.describe().db == "/elsewhere/x.kdbx" and m.describe().keyfile == "/k2")
    check("the state dir is the Brain state dir", m.state == state and m.home == home)
    check("the local shared dir is this machine's", m.local_shared() == os.path.join(home, "Sync"))
    bare = AD.LocalMachine(environ={"HOME": home, "BRAIN_STATE": tmpdir()}, home=home)
    check("an unconfigured machine describes nothing", bare.describe().db == "" and bare.local_shared() is None)


def fake_kp(root, accepts_keyfile):
    path = os.path.join(root, "kp.py")
    with open(path, "w") as fh:
        fh.write("import sys, json\n"
                 "args = sys.argv[1:]\n"
                 "open(%r, 'a').write(json.dumps(args) + '\\n')\n"
                 "if '--keyfile' in args and not %r:\n"
                 "    sys.stderr.write('usage: kp.py\\nkp.py: error: unrecognized arguments: --keyfile ' + args[-1] + '\\n')\n"
                 "    sys.exit(2)\n"
                 "print('recorded   : ' + args[args.index('--db') + 1])\n" % (os.path.join(root, "calls"), accepts_keyfile))
    return path


def test_kp_init():
    print("\n== kp.py init, and the fallback for a kp.py without --keyfile ==")
    root = tmpdir()
    config = os.path.join(root, "state", "kp-config.json")
    kp = AD.KpInitRunner(fake_kp(root, True), config_path=config)
    good, detail = kp.init("/d.kdbx", "/k.key", "Brain")
    calls = [json.loads(line) for line in open(os.path.join(root, "calls"))]
    check("kp.py init is run with --db, --keyfile and --group", good and calls[-1] == ["init", "--db", "/d.kdbx", "--keyfile",
                                                                                        "/k.key", "--group", "Brain"],
          (good, detail, calls))
    check("nothing is written by hand when kp.py did it", not os.path.exists(config))

    root = tmpdir()
    config = os.path.join(root, "state", "kp-config.json")
    os.makedirs(os.path.dirname(config))
    with open(config, "w") as fh:
        json.dump({"inbox": "/i"}, fh)
    kp = AD.KpInitRunner(fake_kp(root, False), config_path=config)
    good, detail = kp.init("/d.kdbx", "/k.key", "Brain")
    written = json.load(open(config))
    check("an older kp.py without --keyfile: the config is written the way kp.py writes it",
          good and written == {"db": "/d.kdbx", "keyfile": "/k.key", "group": "Brain", "inbox": "/i"}, (detail, written))
    check("and it is mode 600", stat.S_IMODE(os.stat(config).st_mode) == 0o600)
    check("kp.py init is not run with a secret on its command line either",
          all("pass" not in " ".join(json.loads(line)) for line in open(os.path.join(root, "calls"))))


def main():
    global AD, D
    try:
        from handoff_core import adapters as AD
        from handoff_core import domain as D
    except Exception as exc:
        check("handoff_core.adapters imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_openssl_argv, test_openssl_real, test_archive, test_files, test_machine, test_kp_init):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
