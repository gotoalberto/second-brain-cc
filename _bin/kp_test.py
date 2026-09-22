#!/usr/bin/env python3
"""Tests for kp.py — the vault's only path to the local KeePass database.

Everything runs against a scratch HOME and state directory. keepassxc-cli is a fake shell
script that records what it was given; no real database, keychain, dialog or clipboard is
touched (BRAIN_KP_CACHE_BACKEND=none, BRAIN_KP_NOPROMPT=1). Run standalone:

    python3 _bin/kp_test.py
"""
import json
import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KP = os.path.join(HERE, "kp.py")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


FAKE_CLI = """#!/bin/sh
# Fake keepassxc-cli: records argv and stdin, answers like a database that opens.
printf '%s\\n' "$@" > "{dir}/argv"
cat > "{dir}/stdin"
exit 0
"""


def world(root, db=None):
    home, state = os.path.join(root, "home"), os.path.join(root, "state")
    os.makedirs(home, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    fake = os.path.join(root, "keepassxc-cli")
    with open(fake, "w") as fh:
        fh.write(FAKE_CLI.replace("{dir}", root))
    os.chmod(fake, 0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
    env.update(HOME=home, BRAIN_STATE=state, BRAIN_KP_STATE=state, BRAIN_VAULT=os.path.dirname(HERE),
               BRAIN_KP_CLI=fake, BRAIN_KP_NOPROMPT="1", BRAIN_KP_CACHE_BACKEND="none")
    if db:
        env["BRAIN_KP_DB"] = db
    return env, state


# A fake keepassxc-cli for a keyfile-only store: it opens only with `--no-password`, the way
# the real one refuses an empty password next to a key file.
FAKE_KEYFILE_ONLY_CLI = """#!/bin/sh
printf '%s\\n' "$@" >> "{dir}/argv-all"
printf '%s\\n' "$@" > "{dir}/argv"
cat > "{dir}/stdin"
for a in "$@"; do [ "$a" = "--no-password" ] && exit 0; done
echo "Error while reading the database: Invalid credentials were provided" >&2
exit 1
"""


def keyfile_world(root, fake_body):
    env, state = world(root)
    fake = os.path.join(root, "keepassxc-cli")
    with open(fake, "w") as fh:
        fh.write(fake_body.replace("{dir}", root))
    os.chmod(fake, 0o755)
    db = os.path.join(root, "store.kdbx")
    open(db, "wb").write(b"\x03\xd9\xa2\x9a" + b"\0" * 2048)
    keyfile = os.path.join(root, "store.key")
    open(keyfile, "wb").write(os.urandom(64))
    env.update(BRAIN_KP_DB=db, BRAIN_KP_KEYFILE=keyfile)
    return env, db, keyfile


def test_keyfile_only(root):
    print("\n== keyfile-only stores ==")
    env, db, keyfile = keyfile_world(os.path.join(root, "kf"), FAKE_KEYFILE_ONLY_CLI)
    argv_all = os.path.join(root, "kf", "argv-all")
    K = import_kp(env)
    asked = []
    K.get_master = lambda interactive=True: asked.append(1) or ("typed", False)
    pw = K.unlocked(interactive=False)
    probe = open(os.path.join(root, "kf", "argv")).read().split("\n")
    check("with a key file configured the store is probed once with --no-password",
          "-k" in probe and keyfile in probe and "--no-password" in probe, probe)
    check("the probe hands over no master, not even an empty line",
          open(os.path.join(root, "kf", "stdin")).read() == "")
    check("when it opens, unlocked() returns no master and never asks for one", pw is None and asked == [],
          (pw, asked))
    os.remove(argv_all)
    K.unlocked(interactive=False)
    check("the answer is kept: a second unlocked() does not probe again", not os.path.exists(argv_all))
    K.cli(["ls", K.DB], None)
    argv = open(os.path.join(root, "kf", "argv")).read().split("\n")
    check("every later call carries -k and --no-password", "-k" in argv and "--no-password" in argv, argv)
    check("and sends no master on stdin", open(os.path.join(root, "kf", "stdin")).read() == "")

    rc, out, err = run(env, "ls")
    check("a keyfile-only store opens with no master and asks for none (headless, no cache)",
          rc == 0 and "master" not in err.lower(), (rc, err))
    rc, out, err = run(env, "status")
    check("status says the keyfile is the whole key, not that a master is missing",
          "the keyfile is the whole key" in out and "not available" not in out, out)
    rc, out, err = run(env, "unlock")
    check("unlock on a keyfile-only store has nothing to cache and says so",
          rc == 0 and "keyfile is the whole key" in out, (rc, out, err))

    env_skip = dict(env, BRAIN_KP_NO_PASSWORD="1")
    K = import_kp(env_skip)
    if os.path.exists(argv_all):
        os.remove(argv_all)
    check("BRAIN_KP_NO_PASSWORD=1 skips the probe and treats the key file as the whole key",
          K.keyfile_only() is True and not os.path.exists(argv_all))

    env_both, db2, kf2 = keyfile_world(os.path.join(root, "kf2"), FAKE_CLI)
    # This fake opens with anything, so make it refuse --no-password: a password + key file store.
    fake2 = os.path.join(root, "kf2", "keepassxc-cli")
    with open(fake2, "w") as fh:
        fh.write(FAKE_CLI.replace("{dir}", os.path.join(root, "kf2")).replace(
            "exit 0", 'for a in "$@"; do [ "$a" = "--no-password" ] && exit 1; done\nexit 0'))
    K = import_kp(env_both)
    check("a store that also has a password is not taken for keyfile-only", K.keyfile_only() is False)
    rc, out, err = run(env_both, "ls")
    check("and headless with no cached master it still exits EXIT_NOMASTER",
          rc == K.EXIT_NOMASTER, (rc, err))
    K.get_master = lambda interactive=True: ("typed-master", False)
    K.cache_put = lambda pw, ttl=None: None
    pw = K.unlocked(interactive=False)
    K.cli(["ls", K.DB], pw)
    argv = open(os.path.join(root, "kf2", "argv")).read().split("\n")
    stdin = open(os.path.join(root, "kf2", "stdin")).read()
    check("password plus key file: -k is passed, --no-password is not, the master goes on stdin",
          "-k" in argv and "--no-password" not in argv and stdin.startswith("typed-master\n"), (argv, stdin))

    # ---- init records a key file, for a caller that sets up a new machine without a prompt
    env_init, state = world(os.path.join(root, "init"))
    db3 = os.path.join(root, "init", "new.kdbx")
    kf3 = os.path.join(root, "init", "new.key")
    rc, out, err = run(env_init, "init", "--db", db3, "--keyfile", kf3)
    cfg = json.load(open(os.path.join(state, "kp-config.json")))
    check("init --db --keyfile records both, non-interactively",
          rc == 0 and cfg.get("db") == db3 and cfg.get("keyfile") == kf3, (rc, out, err, cfg))
    rc, out, err = run(env_init, "init", "--db", db3, "--no-password")
    check("init --no-password without a key file is refused (nothing would open the store)",
          rc != 0 and "--keyfile" in err, (rc, err))


def test_keyfile_real_cli(root):
    print("\n== keyfile stores against the real keepassxc-cli ==")
    real = shutil.which("keepassxc-cli")
    if not real:
        print("  (skipped: keepassxc-cli is not installed on this machine)")
        return
    env, state = world(os.path.join(root, "real"))
    env["BRAIN_KP_CLI"] = real
    env.pop("BRAIN_KP_BACKEND", None)
    env["BRAIN_KP_BACKEND"] = "keepassxc"
    db = os.path.join(root, "real", "store.kdbx")
    kf = os.path.join(root, "real", "store.key")
    rc, out, err = run(env, "init", "--db", db, "--keyfile", kf, "--create", "--no-password")
    check("init --create --no-password makes a keyfile-only database and its key file",
          rc == 0 and os.path.exists(db) and os.path.exists(kf), (rc, out, err))
    rc, out, err = run(env, "status")
    check("status on it says the keyfile is the whole key",
          "the keyfile is the whole key" in out and "not available" not in out, out)
    rc, out, err = run(env, "put", "apis/demo", "--stdin", stdin="demo-secret\n")
    check("a write lands with no master anywhere", rc == 0, (rc, out, err))
    rc, out, err = run(env, "get", "demo", "--pipe", "cat")
    check("and reads back through a pipe, bare name resolved",
          rc == 0 and out.strip() == "demo-secret", (rc, out, err))

    env2, state2 = world(os.path.join(root, "real2"))
    env2.update(BRAIN_KP_CLI=real, BRAIN_KP_BACKEND="keepassxc")
    db2 = os.path.join(root, "real2", "store.kdbx")
    kf2 = os.path.join(root, "real2", "store.key")
    rc, out, err = run(env2, "init", "--db", db2, "--keyfile", kf2, "--create",
                       stdin="swordfish-test\nswordfish-test\n")
    check("init --create with a key file and no --no-password makes a password plus key file database",
          rc == 0 and os.path.exists(db2) and os.path.exists(kf2), (rc, out, err))
    p = subprocess.run([real, "ls", "-q", "-k", kf2, db2], input="swordfish-test\n",
                       capture_output=True, text=True)
    check("it opens with both", p.returncode == 0, p.stderr)
    p = subprocess.run([real, "ls", "-q", "-k", kf2, "--no-password", db2], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    check("and not with the key file alone", p.returncode != 0, p.stdout)
    rc, out, err = run(env2, "ls")
    check("kp.py does not take it for keyfile-only: headless with no master it exits EXIT_NOMASTER",
          rc == 4, (rc, err))


def run(env, *args, stdin=""):
    p = subprocess.run([sys.executable, KP] + list(args), env=env, input=stdin, capture_output=True,
                       text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def import_kp(env):
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        sys.modules.pop("kp", None)
        sys.path.insert(0, HERE)
        import kp  # noqa: F401
        return sys.modules["kp"]
    finally:
        os.environ.clear()
        os.environ.update(saved)


def main():
    root = tempfile.mkdtemp(prefix="kp-test-")
    try:
        if not os.path.exists(KP):
            check("kp.py exists", False, KP)
            print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
            return 1

        src = open(KP, encoding="utf-8").read()
        check("no absolute or remote database path is hardcoded as a default",
              not re.search(r"[\"'](?:/Users/|/home/|/Volumes/)", src)
              and not re.search(r"[\"'](?!kp://)[a-z][a-z0-9+.-]*://", src))

        # ------------------------------------------------ where the database is
        env, state = world(os.path.join(root, "a"))
        K = import_kp(env)
        check("with nothing configured there is no database",
              K.resolve_db({}, {}) == "", K.resolve_db({}, {}))
        check("the first-run config names it",
              K.resolve_db({}, {"db": "~/vault.kdbx"}) == os.path.join(env["HOME"], "vault.kdbx")
              or K.resolve_db({}, {"db": "~/vault.kdbx"}).endswith("/vault.kdbx"),
              K.resolve_db({}, {"db": "~/vault.kdbx"}))
        check("BRAIN_KP_DB wins over the config",
              K.resolve_db({"BRAIN_KP_DB": "/srv/x.kdbx"}, {"db": "/srv/y.kdbx"}) == "/srv/x.kdbx")
        check("the config lives in the state directory",
              os.path.dirname(K.CONFIG) == state, K.CONFIG)
        check("the inbox defaults inside the state directory, not a cloud drive",
              K.INBOX.startswith(state), K.INBOX)
        check("the default group is Brain", K.GROUP_DEF == "Brain", K.GROUP_DEF)

        rc, out, err = run(env, "get", "apis/example")
        check("with no database configured a read exits EXIT_NODB and says how to configure one",
              rc == K.EXIT_NODB and ("kp.py init" in err or "first run" in err.lower()), (rc, err))

        rc, out, err = run(env, "status")
        check("status works with no database configured", rc == 0 and "not configured" in out, (rc, out, err))

        # ------------------------------------------------ init
        db = os.path.join(root, "a", "creds.kdbx")
        rc, out, err = run(env, "init", "--db", db)
        cfg_path = os.path.join(state, "kp-config.json")
        cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        check("init records the database in the config", rc == 0 and cfg.get("db") == db, (rc, out, err, cfg))
        check("the config file is private (0600)",
              os.path.exists(cfg_path) and stat.S_IMODE(os.stat(cfg_path).st_mode) == 0o600)
        rc2, out2, _ = run(env, "init", "--db", db)
        check("init again with the same answer changes nothing", rc2 == 0 and "unchanged" in out2, out2)
        rc, out, err = run(env, "status")
        check("status shows the configured database", db in out, out)

        # ------------------------------------------------ headless: never prompts
        open(db, "wb").write(b"\x03\xd9\xa2\x9a" + b"\0" * 2048)
        rc, out, err = run(env, "get", "apis/example", "--pipe", "cat")
        check("headless with no cached master exits EXIT_NOMASTER instead of prompting",
              rc == K.EXIT_NOMASTER, (rc, err))

        # ------------------------------------------------ the master never reaches argv
        env_db = dict(env, BRAIN_KP_DB=db)
        K = import_kp(env_db)
        K.cli(["ls", K.DB], "correct-horse")
        argv = open(os.path.join(root, "a", "argv")).read()
        stdin = open(os.path.join(root, "a", "stdin")).read()
        check("keepassxc-cli gets the master on stdin", stdin.splitlines()[:1] == ["correct-horse"], stdin)
        check("and never in argv", "correct-horse" not in argv and db in argv, argv)

        # ------------------------------------------------ unlocked(): a transient probe
        # failure must not be treated as a rejected master. Only _BAD_KEY does that.
        import types

        def stub_probe(results):
            results = list(results)

            def fake(pw, path):
                rc, err = results.pop(0)
                return types.SimpleNamespace(returncode=rc, stdout="", stderr=err)
            return fake

        K.work_copy = lambda: None       # no local-copy fallback in play for this check

        cache_del_calls = []
        K.cache_del = lambda: cache_del_calls.append(1)
        get_master_calls = []

        def fake_get_master_cached(interactive=True):
            get_master_calls.append(interactive)
            return "cached-master", True

        K.get_master = fake_get_master_cached
        K._probe = stub_probe([(1, "connection reset"), (0, "")])
        pw = K.unlocked(interactive=False)
        check("a transient probe failure keeps the cached master and retries instead of "
              "dropping the cache",
              pw == "cached-master" and cache_del_calls == [] and len(get_master_calls) == 2,
              (pw, cache_del_calls, get_master_calls))

        cache_del_calls.clear()
        get_master_calls.clear()

        def fake_get_master_after_del(interactive=True):
            get_master_calls.append(interactive)
            if len(get_master_calls) == 1:
                return "cached-master", True
            return None, False           # headless, cache now empty: nobody to ask

        K.get_master = fake_get_master_after_del
        K._probe = stub_probe([(1, "Invalid credentials were provided")])
        try:
            K.unlocked(interactive=False)
            rc = 0
        except SystemExit as e:
            rc = e.code
        check("a genuinely rejected master (matching _BAD_KEY) still drops the cache",
              rc == K.EXIT_NOMASTER and cache_del_calls == [1], (rc, cache_del_calls))

        # ------------------------------------------------ platform backends
        which_none = lambda name: None
        which_all = lambda name: "/usr/bin/" + name
        check("macOS caches the master in the Keychain", K.cache_backend("darwin", which_none, {}) == "keychain")
        check("Linux with secret-tool caches through libsecret",
              K.cache_backend("linux", which_all, {}) == "secret-tool")
        check("Linux without secret-tool does not cache", K.cache_backend("linux", which_none, {}) == "none")
        check("BRAIN_KP_CACHE_BACKEND overrides the choice",
              K.cache_backend("darwin", which_all, {"BRAIN_KP_CACHE_BACKEND": "none"}) == "none")
        check("macOS asks through an osascript dialog", K.dialog_backend("darwin", {}, which_none) == "osascript")
        check("Linux with a display and zenity asks through zenity",
              K.dialog_backend("linux", {"DISPLAY": ":0"}, which_all) == "zenity")
        check("Linux with no display falls back to the terminal",
              K.dialog_backend("linux", {}, which_all) == "tty")
        paste, copy = K.clipboard_commands("darwin", {}, which_none)
        check("macOS clipboard is pbpaste/pbcopy", paste[0].endswith("pbpaste") and copy[0].endswith("pbcopy"))
        paste, copy = K.clipboard_commands("linux", {"WAYLAND_DISPLAY": "w"}, which_all)
        check("Wayland clipboard is wl-paste/wl-copy", paste[0].endswith("wl-paste") and copy[0].endswith("wl-copy"))
        paste, copy = K.clipboard_commands("linux", {}, which_none)
        check("no clipboard tool means no clipboard", paste is None and copy is None)

        boot = os.path.join(root, "boot_id")
        open(boot, "w").write("abc-123\n")
        check("Linux boot id comes from the kernel's boot_id", K.boot_id("linux", proc_path=boot) == "abc-123")
        mac = K.ping_command("darwin", "host", which_all)
        lin = K.ping_command("linux", "host", which_all)
        check("ping waits in milliseconds on macOS and seconds on Linux",
              "1500" in mac and "2" in lin and "1500" not in lin, (mac, lin))

        test_keyfile_only(root)
        test_keyfile_real_cli(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
