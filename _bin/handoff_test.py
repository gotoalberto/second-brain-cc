#!/usr/bin/env python3
"""End to end tests for handoff.py: two scratch machines (a HOME and a Brain state each), real openssl,
real kp.py init, the CLI run as a subprocess from an unrelated working directory.

Skipped (and says so) when openssl is not on PATH. Run standalone:

    python3 _bin/handoff_test.py
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "handoff.py")

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = os.path.realpath(tempfile.mkdtemp(prefix="handoff-e2e-"))
    TMP.append(d)
    return d


def machine(root, name, shared=None):
    home, state = os.path.join(root, name, "home"), os.path.join(root, name, "state")
    os.makedirs(home)
    os.makedirs(state)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
    env.update(HOME=home, BRAIN_STATE=state, BRAIN_VAULT=os.path.dirname(HERE), PYTHONDONTWRITEBYTECODE="1")
    if shared:
        env["BRAIN_SHARED_DIR"] = shared
    return {"home": home, "state": state, "env": env}


def run(m, *args):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), cwd="/", env=m["env"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def private_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, 0o600)


def kp_config(m, **cfg):
    with open(os.path.join(m["state"], "kp-config.json"), "w") as fh:
        json.dump(cfg, fh)


def token_of(out):
    found = re.search(r"redeem '([^']+)'", out)
    return found.group(1) if found else None


def test_shared(root):
    print("\n== through a shared directory ==")
    shared = os.path.join(root, "Sync")
    os.makedirs(shared)
    a = machine(root, "a", shared)
    key = os.path.join(a["home"], ".config", "brain", "brain.key")
    private_file(key, os.urandom(64))
    db = os.path.join(shared, "brain.kdbx")
    private_file(db, b"not really a kdbx, kp.py init does not open it")
    kp_config(a, db=db, keyfile=key, group="Brain")

    rc, out, err = run(a, "issue")
    token = token_of(out)
    check("issue succeeds and prints the redeem command with the token", rc == 0 and token, (rc, err))
    check("it prints the warning about the token", "as sensitive as the keyfile" in out and "never put it in a chat"
          in out.lower())
    files = os.listdir(os.path.join(shared, "handoff"))
    check("one handoff file sits in <shared>/handoff, mode 600", len(files) == 1
          and stat.S_IMODE(os.stat(os.path.join(shared, "handoff", files[0])).st_mode) == 0o600, files)
    check("the keyfile bytes are not readable in it", open(key, "rb").read()[:16]
          not in open(os.path.join(shared, "handoff", files[0]), "rb").read())

    b = machine(root, "b", shared)
    rc, out, err = run(b, "redeem", token)
    placed = os.path.join(b["home"], ".config", "brain", "brain.key")
    check("redeem succeeds from an unrelated working directory", rc == 0, (rc, out, err))
    check("the keyfile arrives byte for byte, mode 600", os.path.exists(placed)
          and open(placed, "rb").read() == open(key, "rb").read() and stat.S_IMODE(os.stat(placed).st_mode) == 0o600)
    cfg = json.load(open(os.path.join(b["state"], "kp-config.json")))
    check("kp.py init recorded the shared database and the keyfile", cfg.get("db") == db and cfg.get("keyfile") == placed,
          cfg)
    check("the handoff file is gone", os.listdir(os.path.join(shared, "handoff")) == [])
    check("it prints the next steps, kp.py status and unlock", "kp.py status" in out and "kp.py unlock" in out)
    rc, out, err = run(b, "redeem", token, "--force")
    check("a second redeem fails: single use", rc == 1 and "already redeemed" in err, (rc, err))

    rc, out, err = run(a, "issue")
    token = token_of(out)
    path = os.path.join(shared, "handoff", os.listdir(os.path.join(shared, "handoff"))[0])
    data = bytearray(open(path, "rb").read())
    data[40] ^= 0xFF
    open(path, "wb").write(bytes(data))
    rc, out, err = run(b, "redeem", token, "--force")
    check("a tampered handoff file is refused on the MAC", rc == 1 and "MAC" in err, (rc, err))

    rc, out, err = run(a, "issue")
    rc, out, err = run(b, "redeem", token_of(out))
    check("redeeming over an existing keyfile needs --force", rc == 1 and "--force" in err, (rc, err))
    old = os.path.join(shared, "handoff", "handoff-%s.enc" % ("e" * 32))
    private_file(old, b"stale")
    os.utime(old, (1, 1))
    rc, out, err = run(a, "issue")
    check("issue sweeps a stale handoff file", rc == 0 and not os.path.exists(old), (rc, err))


def test_inline_with_db(root):
    print("\n== inline, carrying the database ==")
    a = machine(root, "c")
    key = os.path.join(a["home"], "keys", "k.key")
    private_file(key, b"KEYFILE")
    db = os.path.join(a["home"], "Documents", "brain.kdbx")
    private_file(db, os.urandom(2048))
    kp_config(a, db=db, keyfile=key)
    rc, out, err = run(a, "issue", "--with-db")
    token = token_of(out)
    check("without a shared dir the default is inline", rc == 0 and token and token.count(".") == 2, (rc, err))
    b = machine(root, "d")
    rc, out, err = run(b, "redeem", token)
    check("redeem places the database and the keyfile under the new home",
          rc == 0 and open(os.path.join(b["home"], "Documents", "brain.kdbx"), "rb").read() == open(db, "rb").read()
          and open(os.path.join(b["home"], "keys", "k.key"), "rb").read() == b"KEYFILE", (rc, out, err))
    check("both mode 600", all(stat.S_IMODE(os.stat(p).st_mode) == 0o600
                               for p in (os.path.join(b["home"], "Documents", "brain.kdbx"),
                                         os.path.join(b["home"], "keys", "k.key"))))
    cfg = json.load(open(os.path.join(b["state"], "kp-config.json")))
    check("and records them with kp.py init", cfg.get("db") == os.path.join(b["home"], "Documents", "brain.kdbx"), cfg)

    private_file(db, os.urandom(80 * 1024))
    rc, out, err = run(a, "issue", "--with-db")
    check("a database too big to paste is refused inline, pointing at --to PATH", rc == 1 and "--to PATH" in err, (rc, err))
    stick = os.path.join(root, "stick")
    os.makedirs(stick)
    rc, out, err = run(a, "issue", "--with-db", "--to", stick)
    check("--to PATH takes it", rc == 0 and len(os.listdir(stick)) == 1, (rc, err))


def test_no_openssl(root):
    print("\n== without openssl ==")
    a = machine(root, "e")
    private_file(os.path.join(a["home"], "k"), b"K")
    kp_config(a, db="/nowhere.kdbx", keyfile=os.path.join(a["home"], "k"))
    empty = os.path.join(root, "empty-bin")
    os.makedirs(empty)
    a["env"]["PATH"] = empty
    rc, out, err = run(a, "issue")
    check("issue refuses with a clear message", rc == 1 and "openssl is not installed" in err, (rc, err))
    rc, out, err = run(a, "issue", "--ttl-min", "999")
    check("a bad ttl is a usage error, exit 2", rc == 2, (rc, err))
    rc, out, err = run(a, "redeem", "garbage")
    check("a garbage token is refused, exit 1", rc == 1 and "handoff token" in err, (rc, err))


def main():
    root = tmpdir()
    try:
        if not shutil.which("openssl"):
            print("  (openssl not on PATH: the end to end runs are skipped)")
            test_no_openssl(root)
        else:
            for t in (test_shared, test_inline_with_db, test_no_openssl):
                try:
                    t(root)
                except Exception as exc:
                    import traceback
                    traceback.print_exc()
                    check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        for d in TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
